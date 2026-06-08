#!/bin/bash
# 在阿里云服务器项目目录内执行：bash deploy/setup-auth.sh [--force]
set -e
cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

write_env() {
  read -r -p "登录用户名 [admin]: " AUTH_USER
  AUTH_USER="${AUTH_USER:-admin}"
  read -r -s -p "登录密码: " AUTH_PASS
  echo
  if [ -z "$AUTH_PASS" ]; then
    echo "密码不能为空"
    exit 1
  fi
  SECRET="$(openssl rand -hex 32)"
  cat > .env <<EOF
PORT=8080
SECRET_KEY=${SECRET}
MATERIAL_AUTH_USER=${AUTH_USER}
MATERIAL_AUTH_PASSWORD=${AUTH_PASS}
XIAOMI_API_KEY=
EOF
  echo "已写入 $APP_DIR/.env"
}

if [ "$FORCE" = 1 ] || [ ! -f .env ] || ! grep -q '^MATERIAL_AUTH_PASSWORD=.\+' .env 2>/dev/null; then
  if [ "$FORCE" = 0 ] && [ -f .env ] && grep -q '^MATERIAL_AUTH_PASSWORD=.\+' .env 2>/dev/null; then
    echo "已有 .env 且已设置 MATERIAL_AUTH_PASSWORD"
  else
    write_env
  fi
else
  echo "已有 .env 且已设置 MATERIAL_AUTH_PASSWORD（用 --force 可重新设置）"
fi

chmod 600 .env

if [ ! -x venv/bin/gunicorn ]; then
  echo "==> 安装 Python 依赖"
  python3 -m venv venv
  ./venv/bin/pip install -U pip
  ./venv/bin/pip install -r requirements.txt
fi

echo "==> 停止占用 8080 的旧进程"
systemctl stop material-inventory 2>/dev/null || true
fuser -k 8080/tcp 2>/dev/null || true
sleep 1

cp deploy/material-inventory.service /etc/systemd/system/material-inventory.service
systemctl daemon-reload
systemctl enable material-inventory
systemctl restart material-inventory
sleep 2

echo "==> systemd 状态"
systemctl --no-pager status material-inventory || true

echo "==> 8080 监听进程"
ss -tlnp | grep 8080 || true

HEALTH="$(curl -s http://127.0.0.1:8080/health || true)"
echo "==> 健康检查: $HEALTH"

if echo "$HEALTH" | grep -q '"auth"'; then
  if echo "$HEALTH" | grep -q '"auth":true'; then
    echo "登录已启用。访问 http://$(hostname -I | awk '{print $1}')/login"
  else
    echo "服务已更新，但 auth=false：请检查 .env 中 MATERIAL_AUTH_PASSWORD 是否非空"
  fi
else
  echo "ERROR: 仍在跑旧代码。请执行:"
  echo "  journalctl -u material-inventory -n 40 --no-pager"
  exit 1
fi
