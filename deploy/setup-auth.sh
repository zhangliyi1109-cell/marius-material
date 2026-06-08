#!/bin/bash
# 在阿里云服务器项目目录内执行：bash deploy/setup-auth.sh
set -e
cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"

if [ -f .env ] && grep -q '^MATERIAL_AUTH_PASSWORD=.\+' .env 2>/dev/null; then
  echo "已有 .env 且已设置 MATERIAL_AUTH_PASSWORD"
else
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
fi

chmod 600 .env
chown www-data:www-data .env 2>/dev/null || chown www:www .env 2>/dev/null || true

if [ -f deploy/material-inventory.service ]; then
  cp deploy/material-inventory.service /etc/systemd/system/material-inventory.service
  systemctl daemon-reload
fi

systemctl restart material-inventory
sleep 1
echo "--- 健康检查 ---"
curl -s http://127.0.0.1:8080/health || true
echo
echo "完成。浏览器访问 http://$(hostname -I | awk '{print $1}')/ 应跳转到 /login"
