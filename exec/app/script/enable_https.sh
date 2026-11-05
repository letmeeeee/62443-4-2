#!/bin/bash
# 从设备 INI 校验 CA 签发的 HTTPS 身份及代理配置；设备只生成 CSR。
# 支持逗号或空白分隔的多个设备 IPv4 地址；仍监听所有 IPv4 网口。
# sudo ./enable_https.sh --install-service  安装开机初始化服务和每日续期 timer
# sudo ./enable_https.sh                    读取 INI、按需更新并启动/reload nginx
# sudo ./enable_https.sh --prepare          仅准备配置（供 nginx 启动前调用）
# sudo ./enable_https.sh --check            检查证书、nginx 配置与服务状态
# 修改 INI 后：sudo systemctl start g3-cert-renew.service
set -Eeuo pipefail
export PATH="/home/zlg/myenv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${LC_INI_PATH:-/home/zlg/lc_data_set.ini}"
CERT_DIR="${HTTPS_CERT_DIR:-/etc/ssl/g3}"
[[ "$CERT_DIR" =~ ^/[[:alnum:]_./-]+$ ]] || { echo "Invalid HTTPS certificate directory" >&2; exit 1; }
CERT_FILE="$CERT_DIR/g3.crt"
KEY_FILE="$CERT_DIR/g3.key"
RENEW_WINDOW_DAYS=30
MODE="${1:---apply}"
log(){ echo "[$(date '+%F %T')] $*"; }
die(){ log "[ERROR] $*" >&2; exit 1; }
case "$MODE" in
    --help|-h) sed -n '2,8p' "$0"; exit 0 ;;
    --apply|--prepare|--install-service|--check) ;;
    *) die "用法: $0 [--install-service|--apply|--prepare|--check]；IP 改由 $CONFIG_FILE 配置" ;;
esac
[ "$(id -u)" -eq 0 ] || die "请以 root 执行"
# 同时保留终端/journal 输出和每日文件日志，覆盖后续命令的标准输出及错误。
LOG_DIR=/var/log/ems/https
LOG_FILE="$LOG_DIR/https-$(date '+%F').log"
command -v tee >/dev/null || die "缺少依赖: tee"
mkdir -p "$LOG_DIR"
chmod 750 "$LOG_DIR"
(umask 027; touch "$LOG_FILE")
chmod 640 "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1
log_exit(){ log "HTTPS 脚本结束：mode=$MODE pid=$$ exit_code=$1"; }
trap 'log_exit "$?"' EXIT
log "HTTPS 脚本开始：mode=$MODE pid=$$ config=$CONFIG_FILE log=$LOG_FILE"
for tool in python3 openssl nginx flock systemctl; do
    command -v "$tool" >/dev/null || die "缺少依赖: $tool"
done
[ -f /home/zlg/app/main.py ] || die "未检测到目标设备 /home/zlg/app/main.py"
# 校验配置先于文件修改；配置缺失不猜测 IP、不覆盖原 INI。
DEVICE_IPS="$(python3 "$SCRIPT_DIR/https_config.py" "$CONFIG_FILE")" || exit 1
CERTIFICATE_MODE="$(python3 "$SCRIPT_DIR/https_config.py" --certificate-mode "$CONFIG_FILE")" || exit 1
read -r -a IP_ARRAY <<< "$DEVICE_IPS"
SAN="$(printf 'IP:%s\n' "${IP_ARRAY[@]}" | paste -sd, -)"
if [ -d /etc/nginx/conf.d ]; then
    NGINX_CONF_DIR=/etc/nginx/conf.d
elif [ -d /etc/nginx/sites-enabled ]; then
    NGINX_CONF_DIR=/etc/nginx/sites-enabled
else
    die "找不到 nginx 配置目录"
fi
NGINX_CONF="$NGINX_CONF_DIR/g3_https.conf"
if [ "$MODE" = --check ]; then
    log "INI 设备 IP: $DEVICE_IPS；证书模式: $CERTIFICATE_MODE"
    python3 "$SCRIPT_DIR/https_certificates.py" --config "$CONFIG_FILE" --dir "$CERT_DIR" check
    openssl x509 -in "$CERT_FILE" -noout -subject -enddate -ext subjectAltName
    nginx -t
    systemctl status --no-pager nginx g3-https.service g3-cert-renew.timer
    exit 0
fi
mkdir -p "$CERT_DIR/backup"
chmod 700 "$CERT_DIR" "$CERT_DIR/backup"
exec 9>"$CERT_DIR/.configure.lock"
flock -x 9
STAGING="$(mktemp -d "$CERT_DIR/.configure.XXXXXX")"
chmod 700 "$STAGING"
PUBLISHED=0
COMMITTED=0
restore_files() {
    if [ -f "$STAGING/old.nginx" ]; then
        cp -p "$STAGING/old.nginx" "$NGINX_CONF"
    else
        rm -f -- "$NGINX_CONF"
    fi
}
cleanup() {
    local status=$?
    trap - EXIT
    if [ "$PUBLISHED" = 1 ] && [ "$COMMITTED" = 0 ]; then
        log "更新失败，恢复原证书和 nginx 配置"
        restore_files
    fi
    rm -rf -- "$STAGING"
    log_exit "$status"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Only CA-issued identities may be deployed. Renewal never creates a local leaf certificate.
python3 "$SCRIPT_DIR/https_certificates.py" --config "$CONFIG_FILE" --dir "$CERT_DIR" reconcile \
    --renew-window-days "$RENEW_WINDOW_DAYS" || die "CA 证书尚未就绪；请签发并导入 CSR 对应的身份证书"
CURRENT_CERT_HASH="$(openssl dgst -sha256 -r "$CERT_FILE")"
CURRENT_CERT_HASH="${CURRENT_CERT_HASH%% *}"
APPLIED_CERT_HASH="$(cat "$CERT_DIR/.applied-cert.sha256" 2>/dev/null || true)"
cat > "$STAGING/nginx.conf" <<'NGINX_EOF'
# G3 EMS HTTPS 反向代理（由 enable_https.sh 生成，勿手改；重跑脚本会覆盖）
server {
    listen 443 ssl;
    server_name __DEVICE_IP__;

    ssl_certificate     __HTTPS_CERTIFICATE__;
    ssl_certificate_key __HTTPS_KEY__;
    ssl_protocols TLSv1.2 TLSv1.3;

    # 独立升级状态服务：主应用升级停机期间仍可查询，共享登录 Cookie
    location = /api/upgrade/process {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 后端 Flask 不动，TLS 终结后明文转发本机 8000
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SocketIO 路径：必须带 WebSocket 升级头（普通请求 $http_upgrade 为空，不影响）
    location /socket.io/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }
}
NGINX_EOF
sed -i "s|__DEVICE_IP__|${DEVICE_IPS}|g; s|__HTTPS_CERTIFICATE__|${CERT_FILE}|g; s|__HTTPS_KEY__|${KEY_FILE}|g" "$STAGING/nginx.conf"

# 保留已有行为：80 被其他服务占用时不添加 HTTP 跳转。
if ! command -v ss >/dev/null || ! ss -ltnp | grep -E ':80\s' | grep -qv nginx; then
    cat >> "$STAGING/nginx.conf" <<'HTTP_EOF'
server {
    listen 80;
    server_name __DEVICE_IP__;
    return 301 https://$host$request_uri;
}
HTTP_EOF
    sed -i "s|__DEVICE_IP__|${DEVICE_IPS}|g; s|__HTTPS_CERTIFICATE__|${CERT_FILE}|g; s|__HTTPS_KEY__|${KEY_FILE}|g" "$STAGING/nginx.conf"
fi
changed=0
if [ "$CURRENT_CERT_HASH" != "$APPLIED_CERT_HASH" ] || [ -f "$CERT_DIR/.reload-required" ] || ! cmp -s "$STAGING/nginx.conf" "$NGINX_CONF"; then
    [ ! -f "$NGINX_CONF" ] || cp -p "$NGINX_CONF" "$STAGING/old.nginx"
    backup="$CERT_DIR/backup/$(date '+%Y%m%d%H%M%S')-$$"
    mkdir -m 700 "$backup"
    for old in "$STAGING"/old.*; do
        [ ! -f "$old" ] || cp -p "$old" "$backup/"
    done
    PUBLISHED=1
    install -m 644 "$STAGING/nginx.conf" "$NGINX_CONF"
    changed=1
fi
nginx -t || die "nginx 配置校验失败"

if [ "$MODE" = --install-service ]; then
    # 固定安装路径，应用代码目录被升级替换时初始化脚本仍可运行。
    install -d -m 755 /usr/local/lib/g3-https
    if [ "$SCRIPT_DIR" != /usr/local/lib/g3-https ]; then
        install -m 755 "$SCRIPT_DIR/enable_https.sh" /usr/local/lib/g3-https/enable_https.sh
        install -m 644 "$SCRIPT_DIR/https_config.py" /usr/local/lib/g3-https/https_config.py
        install -m 644 "$SCRIPT_DIR/https_certificates.py" /usr/local/lib/g3-https/https_certificates.py
        install -m 644 "$SCRIPT_DIR/pki_common.py" /usr/local/lib/g3-https/pki_common.py
    fi
    if ! systemctl cat nginx.service >/dev/null 2>&1; then
        NGINX_BIN="$(command -v nginx)"
        cat > /etc/systemd/system/nginx.service <<UNIT
[Unit]
Description=Nginx TLS reverse proxy
After=network.target
[Service]
Type=forking
ExecStart=$NGINX_BIN
ExecReload=$NGINX_BIN -s reload
ExecStop=$NGINX_BIN -s quit
[Install]
WantedBy=multi-user.target
UNIT
    fi
    cat > /etc/systemd/system/g3-https.service <<'UNIT'
[Unit]
Description=Prepare G3 HTTPS certificates and proxy from INI
Wants=network-online.target
After=network-online.target
Before=nginx.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/lib/g3-https/enable_https.sh --prepare
TimeoutStartSec=120
[Install]
WantedBy=multi-user.target
UNIT
    install -d -m 755 /etc/systemd/system/nginx.service.d
    cat > /etc/systemd/system/nginx.service.d/g3-https.conf <<'UNIT'
[Unit]
Requires=g3-https.service
After=g3-https.service
UNIT
    cat > /etc/systemd/system/g3-cert-renew.service <<'UNIT'
[Unit]
Description=Check G3 CA identity and prepare external renewal CSR
Wants=network-online.target
After=network-online.target nginx.service
[Service]
Type=oneshot
ExecStart=/usr/local/lib/g3-https/enable_https.sh --apply
TimeoutStartSec=120
UNIT
    cat > /etc/systemd/system/g3-cert-renew.timer <<'UNIT'
[Unit]
Description=Daily G3 HTTPS configuration and certificate check
[Timer]
OnCalendar=*-*-* 03:00:00
RandomizedDelaySec=300
Persistent=true
[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable g3-https.service nginx.service g3-cert-renew.timer
fi
# prepare 不能启动 nginx：nginx 正在等待本服务完成，否则会产生依赖死锁。
# 在等待 systemd 前释放文件锁，避免它启动的 prepare 进程等待本进程。
COMMITTED=1
flock -u 9
if [ "$MODE" != --prepare ]; then
    if systemctl is-active --quiet nginx; then
        if [ "$changed" = 1 ]; then
            systemctl reload nginx || die "nginx reload 失败，文件已更新，请查看 nginx 日志"
        fi
    else
        systemctl start nginx
    fi
    if [ "$MODE" = --install-service ]; then
        systemctl start g3-cert-renew.timer
    fi
fi
APPLIED_HASH_STAGING="$(mktemp "$CERT_DIR/.applied.XXXXXX")"
chmod 600 "$APPLIED_HASH_STAGING"
printf '%s' "$CURRENT_CERT_HASH" > "$APPLIED_HASH_STAGING"
mv -f -- "$APPLIED_HASH_STAGING" "$CERT_DIR/.applied-cert.sha256"
rm -f -- "$CERT_DIR/.reload-required"
log "HTTPS 配置完成：IP=$DEVICE_IPS；9000 查询接口与 8000 共用 443"
