#!/usr/bin/env bash
# 议程 · 一键部署（在服务器上跑，不要在 Windows 上跑）
#
#   sudo bash deploy.sh agenda.example.com
#
# 做四件事：装 python3 → 放文件到 /opt/agenda → 装 systemd 服务 → 配 Caddy 自动 HTTPS
# 可重复执行：不会覆盖 agenda.db 和 token.txt
set -euo pipefail

DOMAIN="${1:-}"
APP_DIR=/opt/agenda
PORT=8080
SRC="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "$DOMAIN" ]]; then
  echo "用法: sudo bash deploy.sh 你的域名（不带 https://）"
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo "请用 sudo 运行"
  exit 1
fi

RUN_USER="${SUDO_USER:-root}"

say(){ printf "\n\033[1;32m== %s\033[0m\n" "$*"; }

say "1/5 检查 python3"
if ! command -v python3 >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y python3
fi
python3 -V | sed 's/^/   /'

say "2/5 放文件到 $APP_DIR"
mkdir -p "$APP_DIR"
install -m 644 "$SRC/server.py" "$APP_DIR/server.py"
rm -rf "$APP_DIR/web"
cp -r "$SRC/web" "$APP_DIR/web"
chmod -R a+rX "$APP_DIR/web"
[[ -f "$APP_DIR/token.txt" ]] || echo "  （首次部署，token.txt 会在启动时生成）"
chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR"
ls -1 "$APP_DIR" | sed 's/^/   /'

say "3/5 装 systemd 服务"
cat >/etc/systemd/system/agenda.service <<UNIT
[Unit]
Description=Agenda sync server
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/server.py --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now agenda >/dev/null 2>&1
sleep 1
systemctl is-active agenda | sed 's/^/   状态: /'

say "4/5 本机自检"
if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null; then
  echo "   后端在 127.0.0.1:$PORT 正常响应"
else
  echo "   ✗ 后端没起来，看日志: journalctl -u agenda -n 50 --no-pager"
  exit 1
fi

say "5/5 配 HTTPS（Caddy）"
if ! command -v caddy >/dev/null 2>&1; then
  echo "   安装 caddy..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y caddy || {
    echo "   ✗ 源里没有 caddy，请手动装：https://caddyserver.com/docs/install"
    echo "   临时可用 nginx 反代到 127.0.0.1:$PORT，或直接 http://IP:$PORT 先试"
    exit 1
  }
fi
if ss -ltnp 2>/dev/null | grep -qE ':(80|443)\s' && ! systemctl is-active --quiet caddy; then
  echo "   ⚠ 80/443 已被别的程序占用（nginx/apache？）。先停掉它，或手动把 Caddyfile 里的站点换成别的做法。"
fi
mkdir -p /etc/caddy
cat >/etc/caddy/Caddyfile <<CADDY
$DOMAIN {
	encode gzip
	reverse_proxy 127.0.0.1:$PORT
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer"
	}
}
CADDY
systemctl reload caddy 2>/dev/null || systemctl restart caddy
sleep 1
systemctl is-active caddy | sed 's/^/   caddy: /'

TOKEN="$(head -1 "$APP_DIR/token.txt" 2>/dev/null || true)"
say "完成"
echo "   域名      : https://$DOMAIN"
echo "   令牌      : ${TOKEN:-（还没生成，看 /opt/agenda/token.txt）}"
echo "   配对地址  : https://$DOMAIN/?token=$TOKEN"
echo
echo "   第一次访问如果证书还没签好，等 10~30 秒再刷新。"
echo "   查日志: journalctl -u agenda -f     重启: systemctl restart agenda"
echo "   加设备: echo \$(python3 -c \"import secrets;print(secrets.token_urlsafe(24))\") >> $APP_DIR/token.txt && systemctl restart agenda"
