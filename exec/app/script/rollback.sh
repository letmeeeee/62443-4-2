#!/bin/bash
# =============================================================================
# rollback.sh — 版本回退脚本
#
# 设计原则：
#   1. 自动扫描 BACKUP_ROOT 下的快照目录，默认取最近一份
#   2. 逐项检测该快照中实际存在哪些备份，只回退存在的项
#   3. 每项回退前将当前版本暂存（形成新快照），保证可以再次前滚
#   4. 回退后做与升级脚本相同的三层健康检查
#   5. 某项回退失败时恢复到回退前的版本，不影响其他项继续执行
#   6. 最终打印与升级脚本风格一致的汇总表
#
# 用法：
#   ./rollback.sh                          # 自动选最新一份备份
#   ./rollback.sh 20250115143001           # 指定快照时间戳
#   ROLLBACK_JOB_ID=job-42 ./rollback.sh  # 带任务 ID 上报状态
# =============================================================================
set -u
set -o pipefail
set -E

# ========= 环境与路径（与 upgrade.sh 保持一致） =========
export PATH="/home/zlg/myenv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
JOB_ID_FILE="/home/zlg/upgrade/rollback/job_id"
REL_VERSION_FILE="/home/zlg/upgrade/rollback/spcVersion"
BASE_DIR="/home/zlg"
BACKUP_ROOT="/home/zlg/upgrade/backups"
BACKUP_ROLL_FAIL="/home/zlg/upgrade/rollback/backups"
if [ -f "$JOB_ID_FILE" ]; then
  JOB_ID="$(cat "$JOB_ID_FILE")"
else
  JOB_ID="${UPGRADE_JOB_ID:-unknown}"
fi
mkdir -p "$BACKUP_ROOT"
mkdir -p "$BACKUP_ROLL_FAIL"
ROLL_STATUS_DIR="/home/zlg/upgrade/status/"
mkdir -p "$ROLL_STATUS_DIR"
# ========= 日志 =========
LOG_DIR="/var/log/ems/rollback"
mkdir -p "$LOG_DIR"
LOG_KEEP_DAYS=31
LOG_MIN_FREE_KB=10240
mkdir -p "$ROLL_STATUS_DIR"
JSON_OUTPUT_FILE="${ROLL_STATUS_DIR%/}/${JOB_ID}.json"
oldest_log_file() {
  ls -1tr "$LOG_DIR"/*.log 2>/dev/null | head -n 1 || true
}

log_dir_free_kb() {
  df -Pk "$LOG_DIR" 2>/dev/null | awk 'NR==2 {print $4}'
}

should_reuse_oldest_log() {
  local oldest="$1"
  local free_kb
  [ -n "$oldest" ] || return 1

  free_kb="$(log_dir_free_kb)"
  if [ -n "$free_kb" ] && [ "$free_kb" -lt "$LOG_MIN_FREE_KB" ]; then
    return 0
  fi

  if find "$oldest" -mtime +"$LOG_KEEP_DAYS" -print -quit 2>/dev/null | grep -q .; then
    return 0
  fi

  return 1
}

prepare_log_file() {
  local new_log="$LOG_DIR/rollback_$(date +%F_%H-%M-%S).log"
  local oldest
  oldest="$(oldest_log_file)"

  if should_reuse_oldest_log "$oldest"; then
    : > "$oldest"
    echo "$oldest"
    return
  fi

  echo "$new_log"
}

LOG_FILE="$(prepare_log_file)"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { echo "[$(date '+%F %T')] $*"; }

# ========= 确定回退快照 =========
# 优先取命令行参数指定的时间戳，否则自动选最新一份
if [ -f "$REL_VERSION_FILE" ]; then
    REL_VERSION="$(tr -d '\r\n' < "$REL_VERSION_FILE")"
else
    REL_VERSION="${REL_VERSION:-$(date +%Y%m%d%H%M%S)}"
fi
echo "Rollback version: ${REL_VERSION}"
TARGET_TS=$REL_VERSION
if [ $# -ge 1 ]; then
    # 如果启动脚本传入路径，则使用传入路径
    SNAP_DIR="$1"
else
    # 未传参，按版本号拼接备份目录
    SNAP_DIR="$BACKUP_ROOT/$TARGET_TS"
fi
if [ ! -d "$SNAP_DIR" ]; then
  echo "[错误] 指定的快照目录不存在: $SNAP_DIR"
  echo "[提示] 可用快照列表："
  ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | sed 's|.*/||;s|/$||' || echo "  （无可用快照）"
  exit 1
fi

# ========= 为本次回退创建新快照（保留当前版本，支持再次前滚） =========
ROLLBACK_TS="$(date +%Y%m%d%H%M%S)"
SAVE_DIR="$BACKUP_ROLL_FAIL/pre_rollback_${ROLLBACK_TS}"
mkdir -p "$SAVE_DIR"

# ========= 状态上报 =========
STATUS_HOST="${UP_STATUS_HOST:-${APP_HOST:-127.0.0.1}}"
STATUS_PORT="${UP_STATUS_PORT:-5050}"
API_URL="${UP_STATUS_URL:-http://${STATUS_HOST}:${STATUS_PORT}/status/update}"
ROLLBACK_JOB_ID="${JOB_ID:-unknown}"

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

# send_status() {
#   local st="$1"; shift
#   local progress="$1"; shift
#   local msg="${*:-}"
#   local payload
#   payload=$(printf '{"job":"%s","state":%d,"progress":%d,"msg":"%s"}' \
#             "$ROLLBACK_JOB_ID" "$st" "$progress" "$(echo "$msg" | sed 's/"/\\"/g')")
#   _post_json "$payload" || true
#   log "[status] job=$ROLLBACK_JOB_ID state=$st progress=$progress msg=$msg"
# }

_post_json() {
  local payload="$1"
  local write_status=0
  local err_msg=""

  mkdir -p "$ROLL_STATUS_DIR" 2>/dev/null || true

  # 直接将payload写入本地JSON文件，覆盖原有内容
  if ! printf '%s\n' "$payload" > "$JSON_OUTPUT_FILE" 2>"$LOG_DIR/status_write_err.log"; then
    write_status=1
    err_msg="$(cat "$LOG_DIR/status_write_err.log" 2>/dev/null || echo 'unknown write error')"
    log "[status-write] 写入失败: $JSON_OUTPUT_FILE, reason=$err_msg"
    rm -f "$LOG_DIR/status_write_err.log" 2>/dev/null || true
    return 1
  fi

  rm -f "$LOG_DIR/status_write_err.log" 2>/dev/null || true
  return 0
}


send_status() {
  # 用法：send_status <state-int> <progress> [msg...]
  local st="$1"; shift
  local progress="$1"; shift
  local msg="${*:-}"
  local payload
  payload=$(printf '{"job":"%s","state":%d,"progress":%d,"msg":"%s"}' \
            "$ROLLBACK_JOB_ID" "$st" "$progress" "$(echo "$msg" | sed 's/"/\\"/g')")
  if ! _post_json "$payload"; then
    log "[status] job=$ROLLBACK_JOB_ID state=$st progress=$progress msg=$msg (write failed)"
  else
    log "[status] job=$ROLLBACK_JOB_ID state=$st progress=$progress msg=$msg"
  fi
}

# ========= 绝对路径命令 =========
SYSTEMCTL="$(command -v systemctl || echo /usr/bin/systemctl)"
CP="$(command -v cp    || echo /bin/cp)"
MV="$(command -v mv    || echo /bin/mv)"
CHMOD="$(command -v chmod || echo /bin/chmod)"
RM="$(command -v rm    || echo /bin/rm)"

# ========= 服务与路径定义（与 upgrade.sh 保持一致） =========
declare -a FILENAMES=("tems" "lc_data")
declare -A SERVICES=(
  ["tems"]="tems.service"
  ["lc_data"]="lc_data.service"
  ["dist"]=""
  ["app"]="python_app.service"
)
LC_INI_NAME="lc_data_set.ini"

# 升级状态查询服务（9000 端口）。回退期间必须保持存活，
# 只在最终状态上报完成之后重启一次，让它加载回退后的代码。
STATUS_SVC="upgrade_status.service"

# ========= 结果跟踪 =========
declare -A ITEM_RESULTS=()
declare -a ITEM_ORDER=()
declare -a FAILED_ITEMS=()

record_result() {
  local _key="$1" _st="$2" _note="$3"
  ITEM_RESULTS["$_key"]="${_st}|${_note}"
  ITEM_ORDER+=("$_key")
}

# 未捕获错误只记录，不中断流程
trap 'log "[ERR trap] 第 $LINENO 行发生未捕获错误"' ERR

# ========= 工具函数 =========

SVC_INIT_WAIT=5
SVC_RESTART_TIMEOUT=30

svc_health_check() {
  local svc="$1"
  local wait="${2:-0}"
  [ "$wait" -gt 0 ] && sleep "$wait"

  if ! "$SYSTEMCTL" is-active --quiet "$svc"; then
    log "[健康检查] $svc: is-active=failed"
    return 1
  fi

  local pid
  pid=$("$SYSTEMCTL" show -p MainPID --value "$svc" 2>/dev/null || echo 0)
  if [ "${pid:-0}" -le 0 ] || ! kill -0 "$pid" 2>/dev/null; then
    log "[健康检查] $svc: MainPID=$pid 进程不存在"
    return 1
  fi

  if journalctl -u "$svc" -n 20 --no-pager 2>/dev/null \
       | grep -qiE '(traceback|panic|fatal|segfault|killed|oom)'; then
    log "[健康检查] $svc: 日志中检测到致命关键字"
    return 1
  fi

  log "[健康检查] $svc: 通过 (pid=$pid)"
  return 0
}

svc_restart() {
  local svc="$1"
  log "[重启] 正在重启 $svc ..."
  timeout "$SVC_RESTART_TIMEOUT" "$SYSTEMCTL" restart "$svc" >/dev/null 2>&1
  local ret=$?
  if [ "$ret" -ne 0 ]; then
    [ "$ret" -eq 124 ] \
      && log "[失败] $svc 重启超时 ${SVC_RESTART_TIMEOUT}s" \
      || log "[失败] $svc 重启异常，返回码: $ret"
    return 1
  fi
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

# rollback_item: 回退单个文件/目录
# 参数: <显示名> <服务名> <生产路径> <快照中的备份路径> [is_dir: 0|1]
rollback_item() {
  local label="$1"
  local svc="$2"
  local live_path="$3"
  local snap_path="$4"
  local is_dir="${5:-0}"

  echo "--------------------"
  log "[回退] $label"
  log "       快照来源: $snap_path"
  log "       生产路径: $live_path"

  # ── 步骤1: 将当前版本暂存到 SAVE_DIR（形成新快照，支持再次前滚）
  local save_path="$SAVE_DIR/$(basename "$live_path")"
  if [ -e "$live_path" ]; then
    log "[保存] 暂存当前版本: $live_path -> $save_path"
    if [ "$is_dir" -eq 1 ]; then
      $CP -a "$live_path" "$save_path"
    else
      $CP -f "$live_path" "$save_path"
    fi
  else
    log "[注意] 当前版本不存在，跳过暂存: $live_path"
  fi

  # ── 步骤2: 将快照内容复制到临时路径，再原子替换（避免直接覆盖生产路径）
  local staged="${live_path}.rb_${ROLLBACK_TS}"
  $RM -rf "$staged" 2>/dev/null || true
  if [ "$is_dir" -eq 1 ]; then
    $CP -a "$snap_path" "$staged"
  else
    $CP -f "$snap_path" "$staged"
    $CHMOD +x "$staged" 2>/dev/null || true
  fi

  # ── 步骤3: 原子替换
  $RM -rf "$live_path"
  $MV -f -T "$staged" "$live_path"
  log "[替换] 完成: $live_path"

  # ── 步骤4: 重启服务并健康检查
  if [ -z "$svc" ] || svc_restart "$svc"; then
      if [ -n "$svc" ]; then
          record_result "$label" "ok" "回退成功，服务运行正常"
      else
          record_result "$label" "ok" "回退成功（无需重启服务）"
      fi
      return 0
  fi
  # ── 步骤5: 服务启动失败 → 恢复暂存版本（即回退前的当前版本）
  log "[恢复] 回退后服务异常，尝试恢复到回退前版本"
  if [ -e "$save_path" ]; then
    $RM -rf "$live_path"
    if [ "$is_dir" -eq 1 ]; then
      $CP -a "$save_path" "$live_path"
    else
      $CP -f "$save_path" "$live_path"
      $CHMOD +x "$live_path" 2>/dev/null || true
    fi
    if svc_restart "$svc"; then
      log "[恢复成功] $svc 已恢复到回退前版本"
      record_result "$label" "fail" "回退失败（服务异常），已恢复到回退前版本"
    else
      log "[严重] $svc 恢复后仍无法启动，需人工介入"
      record_result "$label" "critical" "回退与恢复均失败，需人工介入"
      FAILED_ITEMS+=("$label")
    fi
  else
    log "[严重] 无暂存版本可恢复，需人工介入: $svc"
    record_result "$label" "critical" "回退失败且无暂存可恢复，需人工介入"
    FAILED_ITEMS+=("$label")
  fi
  return 1
}

# rollback_file_only: 仅替换文件，不涉及服务重启（用于配置文件）
rollback_file_only() {
  local label="$1"
  local live_path="$2"
  local snap_path="$3"

  echo "--------------------"
  log "[回退] $label (仅文件替换，无服务重启)"

  local save_path="$SAVE_DIR/$(basename "$live_path")"
  if [ -f "$live_path" ]; then
    $CP -f "$live_path" "$save_path"
    log "[保存] 暂存当前版本: $save_path"
  fi

  local staged="${live_path}.rb_${ROLLBACK_TS}"
  $RM -f "$staged" 2>/dev/null || true
  $CP -f "$snap_path" "$staged"
  $MV -f -T "$staged" "$live_path"
  log "[替换] 完成: $live_path"
  record_result "$label" "ok" "配置文件已回退"
}

# ========= 扫描快照，统计本次实际回退项数 =========
echo "===================== 回退开始 $(date '+%F %T') ====================="
log "[日志] 本次日志：$LOG_FILE"
log "[回退] 使用快照: $SNAP_DIR (时间戳: $TARGET_TS)"
log "[保存] 当前版本暂存至: $SAVE_DIR"
echo ""

# 列出快照中实际存在的条目，让用户了解本次将回退哪些项
log "[扫描] 快照内容："
ls -1 "$SNAP_DIR" 2>/dev/null | while read -r f; do
  echo "         - $f"
done

# 动态统计实际存在的回退项数
total=0
for _n in "${FILENAMES[@]}"; do
  [ -e "$SNAP_DIR/$_n" ] && total=$((total+1))
done
[ -f "$SNAP_DIR/$LC_INI_NAME" ] && total=$((total+1))
[ -d "$SNAP_DIR/app" ]          && total=$((total+1))
[ -d "$SNAP_DIR/dist" ]         && total=$((total+1))

if [ "$total" -eq 0 ]; then
  log "[错误] 快照目录为空或不包含任何已知备份项: $SNAP_DIR"
  send_status 2 0 "snapshot_empty"
  exit 1
fi

log "[进度] 本次实际回退项数: $total"
done_count=0
send_status 1 0 "rollback_start:$TARGET_TS"

# ========= 逐项回退 =========

# ── 后端二进制（tems / lc_data）
for name in "${FILENAMES[@]}"; do
  svc="${SERVICES[$name]}"
  snap_path="$SNAP_DIR/$name"
  live_path="$BASE_DIR/$name"

  if [ ! -e "$snap_path" ]; then
    log "[跳过] 快照中不含 $name，跳过"
    record_result "$name ($svc)" "skip" "快照中无此备份，已跳过"
    continue
  fi

  is_dir=0
  [ -d "$snap_path" ] && is_dir=1

  if rollback_item "$name ($svc)" "$svc" "$live_path" "$snap_path" "$is_dir"; then
    done_count=$((done_count+1))
    progress=$(( done_count * 100 / total ))
    send_status 1 "$progress" "rollback_done:$name"
  fi
done

# ── 配置文件 lc_data_set.ini
snap_ini="$SNAP_DIR/$LC_INI_NAME"
live_ini="$BASE_DIR/$LC_INI_NAME"
if [ -f "$snap_ini" ]; then
  rollback_file_only "$LC_INI_NAME" "$live_ini" "$snap_ini"
  done_count=$((done_count+1))
  progress=$(( done_count * 100 / total ))
  send_status 1 "$progress" "rollback_done:$LC_INI_NAME"
else
  log "[跳过] 快照中不含 $LC_INI_NAME，跳过"
  record_result "$LC_INI_NAME" "skip" "快照中无此备份，已跳过"
fi

# ── 后端 app 目录
snap_app="$SNAP_DIR/app"
live_app="$BASE_DIR/app"
if [ -d "$snap_app" ]; then
  if rollback_item "app (${SERVICES[app]})" "${SERVICES[app]}" "$live_app" "$snap_app" 1; then
    done_count=$((done_count+1))
    progress=$(( done_count * 100 / total ))
    send_status 1 "$progress" "rollback_done:app"
  fi
else
  log "[跳过] 快照中不含 app/，跳过"
  record_result "app (${SERVICES[app]})" "skip" "快照中无此备份，已跳过"
fi

# ── 前端 dist 目录
snap_dist="$SNAP_DIR/dist"
live_dist="$BASE_DIR/dist"
if [ -d "$snap_dist" ]; then
  if rollback_item "dist (${SERVICES[dist]})" "${SERVICES[dist]}" "$live_dist" "$snap_dist" 1; then
    done_count=$((done_count+1))
    progress=$(( done_count * 100 / total ))
    send_status 1 "$progress" "rollback_done:dist"
  fi
else
  log "[跳过] 快照中不含 dist/，跳过"
  record_result "dist" "skip" "快照中无此备份，已跳过"
fi

# ========= 最终状态上报 =========
echo "--------------------"
if [ "${#FAILED_ITEMS[@]}" -eq 0 ]; then
  log "[结果] 所有回退项执行成功"
  send_status 3 100 "rollback_all_done"
else
  _failed_list=$(IFS=','; echo "${FAILED_ITEMS[*]}")
  log "[结果] 以下项回退失败，请人工介入: $_failed_list"
  send_status 2 100 "rollback_failed:$_failed_list"
fi

# ========= 切换升级状态查询服务到回退后的代码 =========
# 必须放在终态上报之后，理由同 upgrade.sh
if svc_restart "$STATUS_SVC"; then
  log "[成功] $STATUS_SVC 已重启并加载回退后的版本"
else
  log "[严重] $STATUS_SVC 重启失败，升级状态查询接口不可用，请人工介入"
  # 汇总区在下方，这里追加只是为了语义完整，不会再被打印出来
  FAILED_ITEMS+=("$STATUS_SVC")
fi

# ========= 回退结果汇总 =========
_end_time="$(date '+%F %T')"
_col_w=32
_sep=$(printf '%*s' 64 '' | tr ' ' '=')
_div=$(printf '%*s' 60 '' | tr ' ' '-')

_print_row() {
  local _name="$1" _st="$2" _note="$3"
  local _tag
  case "$_st" in
    ok)       _tag="[成功 ✓]"  ;;
    fail)     _tag="[失败 ✗]"  ;;
    skip)     _tag="[跳过 -]"  ;;
    critical) _tag="[严重 !!]" ;;
    *)        _tag="[未知 ?]"  ;;
  esac
  printf "  %-${_col_w}s %-13s %s\n" "$_name" "$_tag" "$_note"
}

echo ""
echo "$_sep"
printf "  %-24s %s\n" "回退结果汇总" "$_end_time"
echo "$_sep"
printf "  %-24s %s\n" "回退快照" "$TARGET_TS"
printf "  %-24s %s\n" "当前版本已暂存至" "${SAVE_DIR##*/}"
echo "$_sep"
printf "  %-${_col_w}s %-13s %s\n" "回退项" "结果" "备注"
echo "  $_div"

for _key in "${ITEM_ORDER[@]}"; do
  _val="${ITEM_RESULTS[$_key]}"
  _st="${_val%%|*}"
  _note="${_val#*|}"
  _print_row "$_key" "$_st" "$_note"
done

echo "  $_div"
printf "  %-24s %d / %d 项\n" "成功 / 总计"    "$done_count" "$total"
printf "  %-24s %s\n"         "日志文件"        "$LOG_FILE"
printf "  %-24s %s\n"         "快照目录"        "$SNAP_DIR"
printf "  %-24s %s\n"         "本次暂存目录"    "$SAVE_DIR"
echo "$_sep"
echo ""
echo "===================== 回退结束 $_end_time ====================="
echo "[提示] 若需再次前滚，可将 $SAVE_DIR 作为快照来源执行本脚本"
