#!/bin/bash
set -u
#set -e                      # 如需遇错立即退出可打开
set -o pipefail
set -E                       # 让 ERR 在函数里也生效

# STATE_IDLE        = 0
# STATE_IN_PROGRESS = 1
# STATE_FAILED      = 2
# STATE_DONE        = 3
# STATE_ERROR       = -1

# ========= 环境与路径 =========
export PATH="/home/zlg/myenv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
JOB_ID_FILE="/home/zlg/upgrade/job_id"
REL_VERSION_FILE="/home/zlg/upgrade/release_version"
# 启动时读取，防止后续清理升级目录删除该文件。
PACKAGE_SHA256=""
if [ -f "/home/zlg/upgrade/package_sha256" ]; then
  PACKAGE_SHA256="$(tr -d '\n' < /home/zlg/upgrade/package_sha256)"
fi
BASE_DIR="/home/zlg"
# 在覆盖/回退 app 前保留数据库工具代码，避免新旧 app 切换导致工具缺失。
PACKAGE_DB_TOOL=""
if [ -f "$BASE_DIR/app/script/manage_upgrade_db.py" ]; then
  PACKAGE_DB_TOOL="$(cat "$BASE_DIR/app/script/manage_upgrade_db.py")"
fi
UPGRADE_STATUS_DIR="/home/zlg/upgrade/status/"
# 自动识别升级入口：优先 LC 子目录，否则用根 upgrade/
if [ -d "/home/zlg/upgrade/LC" ]; then
  UPGRADE_DIR="/home/zlg/upgrade/LC"
else
  UPGRADE_DIR="/home/zlg/upgrade"
fi
REL_VERSION=$(date +%Y%m%d%H%M%S)
# 文件存在则替换
if [ -f "$REL_VERSION_FILE" ]; then
  REL_VERSION="$(tr -d '\n' < "$REL_VERSION_FILE")"
fi
# 集中快照式备份目录：/home/zlg/upgrade/backups/<TIMESTAMP>/
BACKUP_ROOT="/home/zlg/upgrade/backups"
BACKUP_TS="$(date +%Y%m%d%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/${BACKUP_TS}_${REL_VERSION}"
BACKUP_KEEP=5      # 仅保留最近 N 份备份

# 升级状态查询服务（9000 端口）。它必须在整个升级过程中保持存活，
# 否则升级期间无法查询进度；因此只在最终状态上报完成之后重启一次，
# 让它加载新版本代码。注意：重启必须排在 send_status 之后，
# 否则最后一条终态会由新代码写入。
STATUS_SVC="upgrade_status.service"

# ========= 日志 =========
LOG_DIR="/var/log/ems/upgrade"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/upgrade_$(date +%F_%H-%M-%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "===================== 升级开始 $(date '+%F %T') ====================="
echo "[日志] 本次日志：$LOG_FILE"
echo "[环境] BASE_DIR=$BASE_DIR"
echo "[环境] UPGRADE_DIR=$UPGRADE_DIR"
echo "[环境] BACKUP_DIR=$BACKUP_DIR (集中备份)"
echo "[环境] BACKUP_KEEP=$BACKUP_KEEP"

mkdir -p "$BACKUP_DIR"

# ========= 状态上报（curl→wget→python3 回退，打到本机 8000） =========
STATUS_HOST="${UP_STATUS_HOST:-${APP_HOST:-127.0.0.1}}"
STATUS_PORT="${UP_STATUS_PORT:-8000}"
API_URL="${UP_STATUS_URL:-http://${STATUS_HOST}:${STATUS_PORT}/status/update}"
if [ -f "$JOB_ID_FILE" ]; then
  JOB_ID="$(cat "$JOB_ID_FILE")"
else
  JOB_ID="${UPGRADE_JOB_ID:-unknown}"
fi
log(){ echo "[$(date '+%F %T')] $*"; }
mkdir -p "$UPGRADE_STATUS_DIR"
JSON_OUTPUT_FILE="${UPGRADE_STATUS_DIR%/}/${JOB_ID}.json"
FINALIZED=false
UPGRADE_HAD_ERROR=0
# _post_json() {
#   local payload="$1"
#   if command -v curl >/dev/null 2>&1; then
#     curl -sS -m 2 -H 'Content-Type: application/json' -X POST -d "$payload" "$API_URL" >/dev/null 2>&1 && return 0
#   fi
#   if command -v wget >/dev/null 2>&1; then
#     wget -qO- --header='Content-Type: application/json' --post-data="$payload" "$API_URL" >/dev/null 2>&1 && return 0
#   fi
#   if command -v python3 >/dev/null 2>&1; then
#     python3 - "$API_URL" "$payload" >/dev/null 2>&1 <<'PY'
# import sys, urllib.request
# req = urllib.request.Request(sys.argv[1], data=sys.argv[2].encode(),
#                              headers={'Content-Type':'application/json'})
# urllib.request.urlopen(req, timeout=2).read()
# PY
#     return 0
#   fi
#   return 1
# }

_post_json() {
  local payload="$1"
  local write_status=0
  local err_msg=""

  mkdir -p "$UPGRADE_STATUS_DIR" 2>/dev/null || true

  # 直接将payload写入本地JSON文件，覆盖原有内容
  if ! printf '%s\n' "$payload" > "${JSON_OUTPUT_FILE}.tmp.$$" 2>"$LOG_DIR/status_write_err.log"; then
    write_status=1
    err_msg="$(cat "$LOG_DIR/status_write_err.log" 2>/dev/null || echo 'unknown write error')"
    log "[status-write] 写入失败: $JSON_OUTPUT_FILE, reason=$err_msg"
    rm -f "$LOG_DIR/status_write_err.log" 2>/dev/null || true
    return 1
  fi

  mv -f "${JSON_OUTPUT_FILE}.tmp.$$" "$JSON_OUTPUT_FILE" || return 1
  rm -f "$LOG_DIR/status_write_err.log" 2>/dev/null || true
  return 0
}


send_status() {
  # 用法：send_status <state-int> <progress> [msg...]
  local st="$1"; shift
  local progress="$1"; shift
  local msg="${*:-}"
  local payload
  payload=$(printf '{"job":"%s","state":%d,"progress":%d,"msg":"%s","finalized":%s}' \
            "$JOB_ID" "$st" "$progress" "$(echo "$msg" | sed 's/"/\\"/g')" "$FINALIZED")
  if ! _post_json "$payload"; then
    log "[status] job=$JOB_ID state=$st progress=$progress msg=$msg (write failed)"
  else
    log "[status] job=$JOB_ID state=$st progress=$progress msg=$msg"
  fi
}

log "[debug] JOB_ID=$JOB_ID"

# ========= 绝对路径命令 =========
SYSTEMCTL="$(command -v systemctl || echo /usr/bin/systemctl)"
CP="$(command -v cp     || echo /bin/cp)"
MV="$(command -v mv     || echo /bin/mv)"
CHMOD="$(command -v chmod  || echo /bin/chmod)"
RM="$(command -v rm     || echo /bin/rm)"
FIND="$(command -v find   || echo /usr/bin/find)"
LS="$(command -v ls     || echo /bin/ls)"
GREP="$(command -v grep   || echo /bin/grep)"

# ========= 全局升级结果跟踪 =========
# FAILED_SVCS  记录所有升级失败（含回滚失败）的服务名，用于最终状态上报
# ITEM_RESULTS 关联数组：key=显示名, value="status|备注"（升级流程中实时写入）
# ITEM_ORDER   有序数组：保证汇总按执行顺序输出
declare -a FAILED_SVCS=()
declare -A ITEM_RESULTS=()
declare -a ITEM_ORDER=()

# record_result <显示名> <ok|fail|skip|rollback> <备注>
record_result() {
  local _key="$1" _st="$2" _note="$3"
  case "$_st" in fail|rollback) UPGRADE_HAD_ERROR=1 ;; esac
  ITEM_RESULTS["$_key"]="${_st}|${_note}"
  ITEM_ORDER+=("$_key")
}

# 未捕获错误：仅记日志与状态，不中断后续流程
trap 'UPGRADE_HAD_ERROR=1; send_status 1 0 "unexpected error on line $LINENO" >&2' ERR

# ========= 工具函数 =========

# svc_active_check: 检查服务是否真正运行中
# 用法：svc_active_check <service> [wait_seconds]
svc_active_check() {
  local svc="$1"
  local wait="${2:-0}"
  [ "$wait" -gt 0 ] && sleep "$wait"
  "$SYSTEMCTL" is-active --quiet "$svc"
}

# svc_health_check: 多维度健康判断
# 检查顺序：active 状态 → 进程存活 → 无 Failed/error 日志（近10条）
# 返回 0=健康，1=不健康
svc_health_check() {
  local svc="$1"

  # 1) systemd active 状态
  if ! "$SYSTEMCTL" is-active --quiet "$svc"; then
    log "[健康检查] $svc: is-active=failed"
    return 1
  fi

  # 2) 查询 MainPID 并确认进程存在
  local pid
  pid=$("$SYSTEMCTL" show -p MainPID --value "$svc" 2>/dev/null || echo 0)
  if [ "${pid:-0}" -le 0 ] || ! kill -0 "$pid" 2>/dev/null; then
    log "[健康检查] $svc: MainPID=$pid 进程不存在"
    return 1
  fi

#   # 3) 近期日志中是否含致命关键字（忽略大小写）
#   if journalctl -u "$svc" -n 20 --no-pager 2>/dev/null \
#        | grep -qiE '(traceback|panic|fatal|segfault|killed|oom)'; then
#     log "[健康检查] $svc: 日志中检测到致命关键字"
#     return 1
#   fi

  log "[健康检查] $svc: 通过 (pid=$pid)"
  return 0
}

# svc_restart: 重启服务并做健康检查
# 重启后等待 SVC_INIT_WAIT 秒给程序初始化，再执行健康检查
# 返回 0=成功，1=失败
SVC_INIT_WAIT=5        # 服务启动后初始化等待秒数（可按需调整）
SVC_RESTART_TIMEOUT=30 # systemctl restart 超时秒数

svc_restart() {
  local svc="$1"

  log "[重启] 正在重启 $svc ..."
  timeout "$SVC_RESTART_TIMEOUT" "$SYSTEMCTL" restart "$svc" >/dev/null 2>&1
  local ret=$?
  if [ "$ret" -ne 0 ]; then
    if [ "$ret" -eq 124 ]; then
      log "[失败] $svc 重启命令超时 ${SVC_RESTART_TIMEOUT}s"
    else
      log "[失败] $svc 重启命令异常，返回码: $ret"
    fi
    return 1
  fi

  # 等待程序初始化完成再做健康检查
  log "[等待] $svc 初始化等待 ${SVC_INIT_WAIT}s ..."
  if svc_health_check "$svc" "$SVC_INIT_WAIT"; then
    log "[成功] $svc 重启并健康检查通过"
    return 0
  else
    log "[失败] $svc 健康检查未通过"
    "$SYSTEMCTL" status "$svc" --no-pager -l 2>/dev/null || true
    return 1
  fi
}

# do_rollback: 回滚单个服务的文件并重启
# 用法：do_rollback <service> <old_path> <backup_path>
do_rollback() {
  local svc="$1"
  local old_path="$2"
  local backup_path="$3"

  log "[回滚] 还原 $svc: $backup_path -> $old_path"
  $RM -rf "$old_path"
  if [ -e "$backup_path" ]; then
    $MV -f "$backup_path" "$old_path"
    log "[回滚] 文件已还原: $old_path"
  else
    log "[警告] 无备份可回滚: $backup_path"
  fi

  if svc_restart "$svc"; then
    log "[回滚成功] $svc 服务已恢复"
    return 0
  else
    log "[严重] 回滚后 $svc 仍无法启动，请人工介入"
    FAILED_SVCS+=("$svc")
    return 1
  fi
}

# ZIP必须全部解压准备成功后，才允许替换任何正在使用的程序。
# 使用独立临时目录，避免上次残留目录或解压失败产生的空目录被安装。
declare -a PREPARED_DIRS=()
cleanup_prepared() {
  local prepared
  for prepared in "${PREPARED_DIRS[@]}"; do
    if ! "$RM" -rf -- "$prepared"; then
      log "[警告] 解压临时目录清理失败: $prepared" >&2
    fi
  done
}
trap cleanup_prepared EXIT

prepare_zip() {
  local archive="$1" label="$2" output_var="$3"
  local prepared resolved
  if ! prepared=$(mktemp -d "$UPGRADE_DIR/.prepared_${label}.XXXXXX"); then
    log "[错误] $label 创建解压临时目录失败"
    return 1
  fi
  PREPARED_DIRS+=("$prepared")
  if ! resolved=$(python3 - "$archive" "$prepared" <<'ZIP_PY'
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

archive, destination = sys.argv[1], Path(sys.argv[2])
try:
    with zipfile.ZipFile(archive) as package:
        members = package.infolist()
        if not any(not member.is_dir() for member in members):
            raise ValueError("ZIP为空或只包含空目录")
        for member in members:
            path = PurePosixPath(member.filename)
            if path.is_absolute() or '..' in path.parts or not path.parts:
                raise ValueError("ZIP包含非法路径: %s" % member.filename)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("ZIP包含符号链接: %s" % member.filename)
        # extractall会校验解压内容的CRC；失败只影响临时目录。
        package.extractall(destination)
    children = list(destination.iterdir())
    selected = children[0] if len(children) == 1 and children[0].is_dir() else destination
    if not any(item.is_file() for item in selected.rglob('*')):
        raise ValueError("ZIP没有可安装的文件")
    print(selected)
except Exception as exc:
    print("ZIP校验/解压失败 %s: %s" % (archive, exc), file=sys.stderr)
    sys.exit(1)
ZIP_PY
  ); then
    log "[错误] $label ZIP校验或解压失败，未替换任何程序"
    return 1
  fi
  printf -v "$output_var" '%s' "$resolved"
  log "[预检] $label 已校验并解压到: $resolved"
}

# 先完整复制到与目标同级的临时目录；复制/备份失败时保留原目录。
replace_directory() {
  local source="$1" live="$2" backup="$3"
  local staged="${live}.new_${BACKUP_TS}" previous="${live}.previous_${BACKUP_TS}"
  if [ -e "$staged" ] || [ -e "$previous" ]; then
    log "[错误] 替换临时目录已存在: $staged / $previous"
    return 1
  fi
  if ! "$CP" -a -- "$source" "$staged"; then
    log "[错误] 新目录复制失败，保留原程序: $live"
    "$RM" -rf -- "$staged"
    return 1
  fi
  if [ -e "$live" ]; then
    if ! mkdir -p "$(dirname "$backup")" || ! "$CP" -a -- "$live" "$backup"; then
      log "[错误] 备份失败，保留原程序: $live"
      "$RM" -rf -- "$staged"
      return 1
    fi
    if ! "$MV" -T -- "$live" "$previous"; then
      log "[错误] 原目录切换失败: $live"
      "$RM" -rf -- "$staged"
      return 1
    fi
  fi
  if ! "$MV" -T -- "$staged" "$live"; then
    log "[错误] 新目录切换失败: $live"
    if [ -e "$previous" ]; then
      if ! "$MV" -T -- "$previous" "$live"; then
        log "[严重] 原目录恢复失败，原文件保留在: $previous"
      fi
    fi
    "$RM" -rf -- "$staged"
    return 1
  fi
  "$RM" -rf -- "$previous"
  log "[完成] 已替换 $live；备份在: $backup"
}

# ========= 动态计算 total（仅统计实际存在的升级项） =========
declare -a FILENAMES=("tems" "lc_data")
declare -A SERVICES=(
  ["tems"]="tems.service"
  ["lc_data"]="lc_data.service"
  ["app"]="python_app.service"
)
LC_INI_NAME="lc_data_set.ini"
LC_INI_OLD="$BASE_DIR/$LC_INI_NAME"
LC_INI_NEW="$UPGRADE_DIR/$LC_INI_NAME"
LC_INI_BACKUP="$BACKUP_DIR/$LC_INI_NAME"
LC_INI_STAGED="${LC_INI_OLD}.new_${BACKUP_TS}"
DIST_ZIP="$UPGRADE_DIR/dist.zip"
DIST_OLD="$BASE_DIR/dist"
DIST_BACKUP="$BACKUP_DIR/dist"
APP_ZIP="$UPGRADE_DIR/app.zip"
APP_OLD="$BASE_DIR/app"
APP_BACKUP="$BACKUP_DIR/app"

# 动态统计实际存在的升级项，避免进度偏移
total=0
for _name in "${FILENAMES[@]}"; do
  [ -e "$UPGRADE_DIR/$_name" ] && total=$((total+1))
done
[ -f "$LC_INI_NEW" ] && total=$((total+1))
[ -f "$APP_ZIP"    ] && total=$((total+1))
[ -f "$DIST_ZIP"   ] && total=$((total+1))

log "[进度] 本次实际升级项数: $total"

# 已完成的升级项计数（用于计算进度百分比）
done_count=0

# ========= 开始升级 =========
send_status 1 0 "start"

# 先准备所有ZIP。失败时保留升级内容、原程序及既有备份，便于排查/重试。
_resolved_app_new=""
_resolved_dist_new=""
for _component in app dist; do
  _archive="$UPGRADE_DIR/${_component}.zip"
  if [ -f "$_archive" ]; then
    if ! prepare_zip "$_archive" "$_component" "_resolved_${_component}_new"; then
      record_result "$_component" "fail" "ZIP预检失败，未执行程序替换"
      FINALIZED=true
      send_status 2 0 "${_component}_zip_validation_failed"
      exit 1
    fi
  fi
done

# -------- 逐项升级后端二进制 --------
for name in "${FILENAMES[@]}"; do
  service="${SERVICES[$name]}"
  OLD_PATH="$BASE_DIR/$name"
  NEW_PATH="$UPGRADE_DIR/$name"
  BACKUP_PATH="$BACKUP_DIR/$name"
  STAGED_PATH="${OLD_PATH}.new_${BACKUP_TS}"

  if [ ! -e "$NEW_PATH" ]; then
    echo "--------------------"
    log "[跳过] 未找到新版本: $NEW_PATH"
    record_result "$name ($service)" "skip" "升级包不存在，已跳过"
    continue
  fi

  echo "--------------------"
  log "[处理] 程序: $name (服务: $service)"

  log "[步骤1] 准备新版本到临时路径: $STAGED_PATH"
  $RM -rf "$STAGED_PATH" 2>/dev/null || true
  if [ -d "$NEW_PATH" ]; then
    $CP -a "$NEW_PATH" "$STAGED_PATH"
  else
    $CP -f "$NEW_PATH" "$STAGED_PATH"
  fi
  $CHMOD +x "$STAGED_PATH" 2>/dev/null || true

  log "[步骤2] 备份旧版本: $OLD_PATH -> $BACKUP_PATH"
  if [ -e "$OLD_PATH" ]; then
    mkdir -p "$(dirname "$BACKUP_PATH")"
    $MV -f "$OLD_PATH" "$BACKUP_PATH"
    log "[备份] 已备份到: $BACKUP_PATH"
  else
    log "[注意] 旧版本不存在（可能首次部署）: $OLD_PATH"
  fi

  log "[步骤3] 原子替换: $STAGED_PATH -> $OLD_PATH"
  $MV -f -T "$STAGED_PATH" "$OLD_PATH"

  log "[步骤4] 重启服务加载新版本: $service"
  if svc_restart "$service"; then
    done_count=$((done_count+1))
    progress=$(( done_count * 100 / total ))
    send_status 1 "$progress" "完成第${done_count}个程序升级:$name"
    record_result "$name ($service)" "ok" "升级并健康检查通过"
  else
    log "[回滚] $name 升级失败，开始回滚"
    if do_rollback "$service" "$OLD_PATH" "$BACKUP_PATH"; then
      record_result "$name ($service)" "rollback" "升级失败，已回滚至旧版本"
    else
      record_result "$name ($service)" "fail" "升级失败且回滚异常，需人工处理"
    fi
  fi
done

# -------- lc_data_set.ini 配置替换 --------
if [ -f "$LC_INI_NEW" ]; then
  echo "--------------------"
  log "[处理] 配置文件: $LC_INI_NAME"

  log "[步骤1] 准备新版本到临时路径: $LC_INI_STAGED"
  $RM -f "$LC_INI_STAGED" 2>/dev/null || true
  $CP -f "$LC_INI_NEW" "$LC_INI_STAGED"

  log "[步骤2] 备份旧版本: $LC_INI_OLD -> $LC_INI_BACKUP"
  if [ -f "$LC_INI_OLD" ]; then
    mkdir -p "$(dirname "$LC_INI_BACKUP")"
    $MV -f "$LC_INI_OLD" "$LC_INI_BACKUP"
    log "[备份] 已备份到: $LC_INI_BACKUP"
  else
    log "[注意] 旧版本不存在（可能首次下发）: $LC_INI_OLD"
  fi

  log "[步骤3] 原子替换: $LC_INI_STAGED -> $LC_INI_OLD"
  $MV -f -T "$LC_INI_STAGED" "$LC_INI_OLD"
  if svc_restart "${SERVICES[app]}" && svc_restart "${SERVICES[tems]}"; then
    log "[成功] ${SERVICES[app]} ${SERVICES[tems]}重启成功"
    done_count=$((done_count+1))
    progress=$(( done_count * 100 / total ))
    send_status 1 "$progress" "lc_data_set.ini_updated"
    record_result "$LC_INI_NAME" "ok" "配置文件已原子替换"
  else
    record_result "$LC_INI_NAME" "fail" "配置文件存在冲突"
    log "[回滚] ini 文件升级失败，开始回滚"
    $MV -f "$LC_INI_BACKUP" "$LC_INI_OLD"
    log "[回滚] 文件已还原: $LC_INI_OLD"
  fi
else
  record_result "$LC_INI_NAME" "skip" "无新配置，已跳过"
fi

# -------- 后端 app.zip 升级 --------
if [ -f "$APP_ZIP" ]; then
  echo "--------------------"
  log "[处理] 后端压缩包 app.zip"

  # 使用全局预检已校验并解压的目录。
  log "[解压] APP_NEW 解析结果: $_resolved_app_new"

  if [ -z "$_resolved_app_new" ] || [ ! -d "$_resolved_app_new" ]; then
    log "[错误] 无法识别 app.zip 的内容结构，请检查压缩包"
    send_status -1 0 "app_zip_structure_error"
    FAILED_SVCS+=("${SERVICES[app]}")
    record_result "app (${SERVICES[app]})" "fail" "zip 结构无法识别，需人工处理"
  else
    if ! replace_directory "$_resolved_app_new" "$APP_OLD" "$APP_BACKUP"; then
      record_result "app (${SERVICES[app]})" "fail" "目录复制、备份或切换失败"
    elif svc_restart "${SERVICES[app]}"; then
      log "[成功] ${SERVICES[app]} 重启成功"
      done_count=$((done_count+1))
      progress=$(( done_count * 100 / total ))
      send_status 1 "$progress" "app_done"
      record_result "app (${SERVICES[app]})" "ok" "升级并健康检查通过"
    else
      log "[回滚] app 升级失败，开始回滚"
      if do_rollback "${SERVICES[app]}" "$APP_OLD" "$APP_BACKUP"; then
        record_result "app (${SERVICES[app]})" "rollback" "升级失败，已回滚至旧版本"
      else
        record_result "app (${SERVICES[app]})" "fail" "升级失败且回滚异常，需人工处理"
      fi
    fi
  fi
else
  record_result "app (${SERVICES[app]})" "skip" "无 app.zip，已跳过"
fi

# -------- 前端 dist.zip 升级 --------
if [ -f "$DIST_ZIP" ]; then
  echo "--------------------"
  log "[处理] 前端压缩包 dist.zip"

  # 使用全局预检已校验并解压的目录。
  log "[解压] DIST_NEW 解析结果: $_resolved_dist_new"

  if [ -z "$_resolved_dist_new" ] || [ ! -d "$_resolved_dist_new" ]; then
    log "[错误] 无法识别 dist.zip 的内容结构，请检查压缩包"
    send_status -1 0 "dist_zip_structure_error"
    record_result "dist" "fail" "zip 结构无法识别，需人工处理"
  else
    if replace_directory "$_resolved_dist_new" "$DIST_OLD" "$DIST_BACKUP"; then
      done_count=$((done_count+1))
      progress=$(( done_count * 100 / total ))
      send_status 1 "$progress" "dist_done"
      record_result "dist" "ok" "前端文件替换完成"
    else
      record_result "dist" "fail" "目录复制、备份或切换失败"
    fi
  fi
else
  record_result "dist" "skip" "无 dist.zip，已跳过"
fi

# ========= 清理升级目录（保留 backups/ 与 PCS_*.zip） =========
echo "--------------------"
$RM $JOB_ID_FILE || true
$RM $REL_VERSION_FILE || true
if [ -d "$UPGRADE_DIR" ] && [ -n "$($LS -A "$UPGRADE_DIR" 2>/dev/null)" ]; then
  if [ "$UPGRADE_DIR" = "/home/zlg/upgrade" ]; then
    log "[清理] 清空升级目录（保留 backups/ PCS_*.zip status LC）: $UPGRADE_DIR/*"
    $FIND "$UPGRADE_DIR" -mindepth 1 -maxdepth 1 \
      ! -name 'backups' \
      ! -name 'PCS_*.zip' \
      ! -name 'status' \
      ! -name 'LC' \
      ! -name 'packages' \
      ! -name 'rollback' \
      -exec rm -rf {} +
  else
    log "[清理] 清空升级目录内容: $UPGRADE_DIR/*"
    $RM -rf "$UPGRADE_DIR"/* || true
  fi
else
  log "[清理] 升级目录不存在或为空：$UPGRADE_DIR"
fi

# ========= 备份保留策略（仅保留最近 N 份） =========
echo "--------------------"
if [ -d "$BACKUP_ROOT" ]; then
  log "[保留策略] 仅保留最近 $BACKUP_KEEP 份备份于: $BACKUP_ROOT"
  mapfile -t SNAP_DIRS < <(ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null || true)
  _snap_count=${#SNAP_DIRS[@]}
  if [ "$_snap_count" -gt "$BACKUP_KEEP" ]; then
    for (( _j=BACKUP_KEEP; _j<_snap_count; _j++ )); do
      _old="${SNAP_DIRS[$_j]%/}"
      log "[清理备份] 删除过期备份: $_old"
      $RM -rf "$_old"
    done
  else
    log "[保留策略] 当前备份数 $_snap_count，无需清理"
  fi
fi

# ========= 升级结果汇总 =========
_end_time="$(date '+%F %T')"
_col_w=32
_sep=$(printf '%*s' 64 '' | tr ' ' '=')
_div=$(printf '%*s' 60 '' | tr ' ' '-')

_print_row() {
  local _name="$1" _st="$2" _note="$3"
  local _tag
  case "$_st" in
    ok)       _tag="[成功 ✓]" ;;
    fail)     _tag="[失败 ✗]" ;;
    skip)     _tag="[跳过 -]" ;;
    rollback) _tag="[回滚 ↩]" ;;
    *)        _tag="[未知 ?]" ;;
  esac
  printf "  %-${_col_w}s %-12s %s\n" "$_name" "$_tag" "$_note"
}

echo ""
echo "$_sep"
printf "  %-24s %s\n" "升级结果汇总" "$_end_time"
echo "$_sep"
printf "  %-${_col_w}s %-12s %s\n" "升级项" "结果" "备注"
echo "  $_div"

# 按执行顺序逐项输出——结果全部来自升级过程中实时写入的 ITEM_RESULTS
for _key in "${ITEM_ORDER[@]}"; do
  _val="${ITEM_RESULTS[$_key]}"
  _st="${_val%%|*}"
  _note="${_val#*|}"
  _print_row "$_key" "$_st" "$_note"
done

# 每个程序的真实回退结果已在对应处理分支记录；不能仅重启就宣称全部回退。
if [ "$UPGRADE_HAD_ERROR" -ne 0 ]; then
  log "[结果] 本次升级存在失败，请核对各项目结果；已成功的项目可能已生效"
fi

echo "  $_div"
printf "  %-24s %d / %d 项\n" "完成 / 总计" "$done_count" "$total"
printf "  %-24s %s\n" "日志文件" "$LOG_FILE"
printf "  %-24s %s\n" "备份目录" "$BACKUP_DIR"
echo "$_sep"
echo ""

echo "===================== 升级结束 $_end_time ====================="

# 只在所有项目及回退处理结束后更新当前包并发布终态。
FINALIZED=true
if [ "$UPGRADE_HAD_ERROR" -eq 0 ] && [ "${#FAILED_SVCS[@]}" -eq 0 ] && [ "$total" -gt 0 ]; then
  if [ -n "$PACKAGE_SHA256" ]; then
    if [ -z "$PACKAGE_DB_TOOL" ] || ! python3 -c "$PACKAGE_DB_TOOL" --set-current "$PACKAGE_SHA256"; then
      log "[错误] 升级完成，但当前包标记更新失败，请重试 --set-current $PACKAGE_SHA256"
    fi
  else
    # 旧 file 入口没有可信包摘要，清除旧标记。
    if [ -z "$PACKAGE_DB_TOOL" ] || ! python3 -c "$PACKAGE_DB_TOOL" --clear-current; then
      log "[错误] 当前包标记清除失败，请重试 --clear-current"
    fi
  fi
  send_status 3 100 "all_done"
else
  send_status 2 100 "upgrade_failed_or_rolled_back"
fi
# 终态先落盘，再重启9000查询服务。
if ! svc_restart "$STATUS_SVC"; then
  log "[严重] $STATUS_SVC 重启失败，请恢复查询服务"
fi
