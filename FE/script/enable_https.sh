#!/bin/bash
# =============================================================================
# enable_https.sh — 设备端一键启用 HTTPS（自签名证书 + nginx 反向代理 + 自动续期）
#
# 设计原则：
#   1. 项目代码零改动：后端继续监听 0.0.0.0:8000，nginx 做 TLS 终结后
#      明文转发到 127.0.0.1:8000；前端（同源 axios）与 upgrade/rollback 脚本
#      （打 127.0.0.1:8000）全部无感
#   2. 自签名证书：398 天有效期，SAN 含设备 IP，满足 Chrome 主机名校验
#   3. 到期前 30 天由 systemd timer 自动重签并 reload nginx，无需重启后端
#   4. 幂等可重跑：重跑前自动备份旧证书与旧 nginx 配置
#   5. 全程自检：证书/私钥配对校验、nginx -t 校验、curl 回环自检
#
# 用法：
#   ./enable_https.sh                          # 交互式输入设备访问 IP
#   ./enable_https.sh 192.168.1.100            # 命令行参数指定 IP
#   DEVICE_IP=192.168.1.100 ./enable_https.sh  # 环境变量指定 IP
#   ./enable_https.sh --check                  # 只检查已部署状态
#
# 注意：
#   - 在设备（工控机）上以 root 执行，不是开发机
#   - 前置条件：设备上已安装 nginx（本脚本不负责安装）
#   - 浏览器首次访问 https://<IP>/ 会告警，点"高级 -> 继续前往"；
#     外部调用方需改走 https 并信任证书。后续如升级为内部 CA，
#     只需替换证书与 ssl_certificate 配置，其余不变
# =============================================================================

set -u
set -o pipefail
set -E

export PATH="/home/zlg/myenv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ================== 常量 ==================
CERT_DIR="/etc/ssl/g3"
CERT_FILE="$CERT_DIR/g3.crt"
KEY_FILE="$CERT_DIR/g3.key"
BACKUP_DIR="$CERT_DIR/backup"
NGINX_CONF_NAME="g3_https.conf"
RENEW_SCRIPT="/usr/local/sbin/g3-cert-renew.sh"
RENEW_SERVICE="g3-cert-renew.service"
RENEW_TIMER="g3-cert-renew.timer"
CERT_DAYS=398
RENEW_WINDOW_DAYS=30

log(){ echo "[$(date '+%F %T')] $*"; }
die(){ log "[ERROR] $*"; exit 1; }

# ================== 帮助 ==================
usage() {
    sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

# ================== 状态检查 ==================
do_check() {
    log "===== HTTPS 部署状态检查 ====="
    # 证书
    if [ -f "$CERT_FILE" ]; then
        log "[OK] 证书存在: $CERT_FILE"
        openssl x509 -in "$CERT_FILE" -noout -subject -enddate 2>/dev/null
        if openssl x509 -in "$CERT_FILE" -noout -checkend $((RENEW_WINDOW_DAYS*86400)) 2>/dev/null; then
            log "[OK] 证书剩余有效期 > ${RENEW_WINDOW_DAYS} 天"
        else
            log "[WARN] 证书已过期或 ${RENEW_WINDOW_DAYS} 天内到期，等待 timer 自动续期（或重跑本脚本）"
        fi
    else
        log "[WARN] 证书不存在: $CERT_FILE（尚未部署）"
    fi
    # nginx 配置
    NGINX_CONF_DIR=""
    [ -d /etc/nginx/conf.d ] && NGINX_CONF_DIR=/etc/nginx/conf.d
    [ -z "$NGINX_CONF_DIR" ] && [ -d /etc/nginx/sites-enabled ] && NGINX_CONF_DIR=/etc/nginx/sites-enabled
    if [ -n "$NGINX_CONF_DIR" ] && [ -f "$NGINX_CONF_DIR/$NGINX_CONF_NAME" ]; then
        log "[OK] nginx 配置存在: $NGINX_CONF_DIR/$NGINX_CONF_NAME"
    else
        log "[WARN] nginx 配置不存在: $NGINX_CONF_DIR/$NGINX_CONF_NAME"
    fi
    # 服务与 timer
    systemctl is-active nginx >/dev/null 2>&1 && log "[OK] nginx 运行中" || log "[WARN] nginx 未运行"
    systemctl is-enabled "$RENEW_TIMER" >/dev/null 2>&1 && log "[OK] 续期 timer 已启用" || log "[WARN] 续期 timer 未启用"
    # 回环自检
    if command -v curl >/dev/null; then
        code=$(curl -sk -o /dev/null -w "%{http_code}" https://127.0.0.1/ 2>/dev/null)
        log "[${code}] https://127.0.0.1/ 回环自检（200 为正常，000 表示 443 不通）"
    fi
    exit 0
}

# ================== 主流程 ==================
case "${1:-}" in
    -h|--help) usage ;;
    --check)   do_check ;;
esac

# 1. 解析设备 IP
DEVICE_IP="${DEVICE_IP:-${1:-}}"
if [ -z "$DEVICE_IP" ]; then
    default_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    if [ -t 0 ]; then
        read -r -p "请输入设备访问 IP${default_ip:+（回车用 $default_ip）}: " DEVICE_IP
        DEVICE_IP="${DEVICE_IP:-$default_ip}"
    else
        [ -n "$default_ip" ] && DEVICE_IP="$default_ip" || die "未指定设备 IP，请用 DEVICE_IP=<ip> 或命令行参数指定"
    fi
fi
echo "$DEVICE_IP" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || die "IP 格式非法: $DEVICE_IP"

# 2. 前置检查
[ "$(id -u)" -eq 0 ] || die "需要 root 权限（sudo ./enable_https.sh）"
command -v nginx >/dev/null || die "未找到 nginx，请先在设备上安装 nginx 再运行本脚本"
openssl version | grep -qE 'OpenSSL (1\.1\.1|3\.)' || die "OpenSSL 版本过低（需 >=1.1.1 以支持 -addext）: $(openssl version)"
command -v curl >/dev/null || die "未找到 curl"

# 3. 设备识别（防误在开发机执行）
if [ ! -f /home/zlg/app/main.py ]; then
    log "[WARN] 未检测到 /home/zlg/app/main.py，当前机器可能不是目标设备"
    if [ -t 0 ]; then
        read -r -p "确认要在当前机器执行? [y/N] " ans
        [ "$ans" = "y" ] || die "已取消"
    else
        die "当前机器非目标设备，已中止（如需强制执行请注释本检查）"
    fi
fi

# 4. nginx 配置目录探测
NGINX_CONF_DIR=""
[ -d /etc/nginx/conf.d ] && NGINX_CONF_DIR=/etc/nginx/conf.d
[ -z "$NGINX_CONF_DIR" ] && [ -d /etc/nginx/sites-enabled ] && NGINX_CONF_DIR=/etc/nginx/sites-enabled
[ -n "$NGINX_CONF_DIR" ] || die "未找到 /etc/nginx/conf.d 或 /etc/nginx/sites-enabled，nginx 目录结构未知"

log "=================================================="
log "目标 IP  : $DEVICE_IP"
log "nginx    : $(command -v nginx)"
log "配置目录 : $NGINX_CONF_DIR"
log "=================================================="

# 5. 生成自签名证书
log "[1/5] 生成自签名证书 (${CERT_DAYS} 天, SAN=$DEVICE_IP) ..."
mkdir -p "$CERT_DIR" "$BACKUP_DIR"
umask 077
if [ -f "$CERT_FILE" ] || [ -f "$KEY_FILE" ]; then
    ts="$(date +%Y%m%d%H%M%S)"
    [ -f "$CERT_FILE" ] && cp -f "$CERT_FILE" "$BACKUP_DIR/g3.crt.$ts"
    [ -f "$KEY_FILE" ] && cp -f "$KEY_FILE" "$BACKUP_DIR/g3.key.$ts"
    log "旧证书已备份到 $BACKUP_DIR（时间戳 $ts）"
fi
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY_FILE" -out "$CERT_FILE" -days "$CERT_DAYS" \
    -subj "/CN=$DEVICE_IP" -addext "subjectAltName=IP:$DEVICE_IP" \
    || die "证书生成失败"
chmod 600 "$KEY_FILE"
umask 022

# 证书/私钥配对校验
c_md5="$(openssl x509 -noout -modulus -in "$CERT_FILE" | openssl md5 | awk '{print $2}')"
k_md5="$(openssl rsa  -noout -modulus -in "$KEY_FILE" | openssl md5 | awk '{print $2}')"
[ "$c_md5" = "$k_md5" ] || die "证书与私钥不匹配，已中止（可重跑本脚本恢复）"
log "[OK] 证书生成完毕且与私钥匹配"
openssl x509 -in "$CERT_FILE" -noout -subject -enddate

# 6. 写 nginx 配置
log "[2/5] 写入 nginx 配置: $NGINX_CONF_DIR/$NGINX_CONF_NAME ..."
[ -f "$NGINX_CONF_DIR/$NGINX_CONF_NAME" ] && cp -f "$NGINX_CONF_DIR/$NGINX_CONF_NAME" "$NGINX_CONF_DIR/$NGINX_CONF_NAME.bak.$(date +%Y%m%d%H%M%S)"
cat > "$NGINX_CONF_DIR/$NGINX_CONF_NAME" <<'NGINX_EOF'
# G3 EMS HTTPS 反向代理（由 enable_https.sh 生成，勿手改；重跑脚本会覆盖）
server {
    listen 443 ssl;
    server_name __DEVICE_IP__;

    ssl_certificate     /etc/ssl/g3/g3.crt;
    ssl_certificate_key /etc/ssl/g3/g3.key;
    ssl_protocols TLSv1.2 TLSv1.3;

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
sed -i "s|__DEVICE_IP__|${DEVICE_IP}|g" "$NGINX_CONF_DIR/$NGINX_CONF_NAME"

# 80 -> 443 跳转（仅当 80 端口未被其他进程占用时写入）
PORT80_OTHER=0
if command -v ss >/dev/null && ss -ltnp 2>/dev/null | grep -E ':80\s' | grep -qv 'nginx'; then
    PORT80_OTHER=1
fi
if [ "$PORT80_OTHER" = "0" ]; then
    cat >> "$NGINX_CONF_DIR/$NGINX_CONF_NAME" <<'NGINX80_EOF'

# 明文 80 端口统一 301 跳转到 HTTPS
server {
    listen 80;
    server_name __DEVICE_IP__;
    return 301 https://$host$request_uri;
}
NGINX80_EOF
    sed -i "s|__DEVICE_IP__|${DEVICE_IP}|g" "$NGINX_CONF_DIR/$NGINX_CONF_NAME"
else
    log "[WARN] 80 端口被其他进程占用，跳过 80->443 跳转配置"
fi

nginx -t || die "nginx 配置校验失败，请检查 $NGINX_CONF_DIR/$NGINX_CONF_NAME"

# 7. 系统服务：nginx（缺失时补齐）
log "[3/5] 配置 systemd 服务 ..."
if ! systemctl cat nginx.service >/dev/null 2>&1; then
    NGINX_BIN="$(command -v nginx)"
    cat > /etc/systemd/system/nginx.service <<'NGINX_UNIT'
[Unit]
Description=Nginx TLS 反向代理
After=network.target

[Service]
Type=forking
ExecStart=__NGINX_BIN__
ExecReload=__NGINX_BIN__ -s reload
ExecStop=__NGINX_BIN__ -s quit
Restart=always
RestartSec=5
KillMode=mixed

[Install]
WantedBy=multi-user.target
NGINX_UNIT
    sed -i "s|__NGINX_BIN__|${NGINX_BIN}|g" /etc/systemd/system/nginx.service
    log "已补齐 nginx.service（$NGINX_BIN）"
fi

# 证书续期脚本 + service + timer
cat > "$RENEW_SCRIPT" <<'RENEW_EOF'
#!/bin/bash
# 由 g3-cert-renew.timer 触发：证书剩余不足30天时自动重签并 reload nginx（自签名模式）
set -u
CERT=/etc/ssl/g3/g3.crt
KEY=/etc/ssl/g3/g3.key
BACKUP=/etc/ssl/g3/backup
CN=__DEVICE_IP__
CERT_DAYS=398

log(){ echo "[$(date '+%F %T')] $*"; }

# 剩余有效期 >= 30 天则跳过（checkend 返回 0 表示仍然有效）
if openssl x509 -in "$CERT" -noout -checkend $((30*86400)) 2>/dev/null; then
    log "证书剩余有效期 > 30 天，无需续期"
    exit 0
fi

log "证书即将到期，开始续期 ..."
mkdir -p "$BACKUP"
cp -f "$CERT" "$BACKUP/g3.crt.$(date +%Y%m%d%H%M%S)" 2>/dev/null
cp -f "$KEY"  "$BACKUP/g3.key.$(date +%Y%m%d%H%M%S)" 2>/dev/null

openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY.tmp" -out "$CERT.tmp" -days "$CERT_DAYS" \
    -subj "/CN=$CN" -addext "subjectAltName=IP:$CN" || exit 1
mv -f "$KEY.tmp" "$KEY"
mv -f "$CERT.tmp" "$CERT"
chmod 600 "$KEY"

systemctl reload nginx 2>/dev/null || nginx -s reload || exit 1
log "证书续期完成并已重载 nginx"
RENEW_EOF
sed -i "s|__DEVICE_IP__|${DEVICE_IP}|g" "$RENEW_SCRIPT"
chmod +x "$RENEW_SCRIPT"

cat > "/etc/systemd/system/$RENEW_SERVICE" <<'SVC_EOF'
[Unit]
Description=续期 G3 自签名证书（由 timer 触发）

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/g3-cert-renew.sh
SVC_EOF

cat > "/etc/systemd/system/$RENEW_TIMER" <<'TMR_EOF'
[Unit]
Description=每日检查证书有效期，剩余不足30天时自动续期

[Timer]
OnCalendar=*-*-* 03:00:00
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
TMR_EOF

systemctl daemon-reload
systemctl enable --now nginx          || die "nginx 服务启动失败"
systemctl enable --now "$RENEW_TIMER" || die "续期 timer 启用失败"

# 8. 自检
log "[4/5] 自检 ..."
sleep 1
systemctl is-active nginx >/dev/null || die "nginx 未运行"
code=$(curl -sk -o /dev/null -w "%{http_code}" https://127.0.0.1/)
[ "$code" = "200" ] || die "回环自检失败: https://127.0.0.1/ 返回 $code"
log "[OK] https://127.0.0.1/ -> $code"

# 9. 汇总
log "[5/5] 部署完成"
echo "===================== HTTPS 部署完成 ====================="
echo "[证书]  $CERT_FILE（自签名 ${CERT_DAYS} 天，SAN=$DEVICE_IP）"
echo "[配置]  $NGINX_CONF_DIR/$NGINX_CONF_NAME"
echo "[服务]  nginx + $RENEW_TIMER（每日检查，剩 ${RENEW_WINDOW_DAYS} 天内自动重签并 reload）"
echo "[访问]  https://$DEVICE_IP/"
echo "[提醒]  浏览器首次访问点"高级 -> 继续前往"；"
echo "       上位机等外部调用方需改走 https://$DEVICE_IP/ 并信任证书；"
echo "       后端 8000 保持不变，过渡期后建议将后端绑回 127.0.0.1 加固"
