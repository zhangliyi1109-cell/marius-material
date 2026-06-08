#!/bin/bash
# 在阿里云 ECS 上首次部署后执行（需 root 或 sudo）
set -e

APP_DIR=/opt/material-inventory
REPO=${REPO:-git@github.com:zhangliyi1109-cell/marius-material.git}

echo "==> 安装系统依赖"
if command -v apt-get >/dev/null; then
  apt-get update
  apt-get install -y git python3 python3-venv python3-pip nginx
elif command -v yum >/dev/null; then
  yum install -y git python3 python3-pip nginx
  python3 -m pip install virtualenv 2>/dev/null || true
else
  echo "请手动安装 git python3 nginx"
  exit 1
fi

echo "==> 克隆/更新代码"
mkdir -p "$(dirname "$APP_DIR")"
if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR" && git pull
else
  git clone "$REPO" "$APP_DIR"
  cd "$APP_DIR"
fi

echo "==> Python 虚拟环境"
python3 -m venv venv
./venv/bin/pip install -U pip
./venv/bin/pip install -r requirements.txt

echo "==> 环境变量"
if [ ! -f .env ]; then
  cp deploy/env.example .env
  echo "请编辑 $APP_DIR/.env 填入 SECRET_KEY、MATERIAL_AUTH_PASSWORD、XIAOMI_API_KEY 等"
fi

echo "==> guancli（BI 拉数必需）"
if ! command -v guancli >/dev/null; then
  echo "请在本机安装 guancli 并复制配置到服务器，例如："
  echo "  scp -r ~/.config/guancli root@101.133.149.106:/root/.config/"
  echo "  或按 guancli 文档在服务器登录一次"
fi

echo "==> systemd 服务"
id www-data >/dev/null 2>&1 || useradd -r -s /bin/false www 2>/dev/null || true
chown -R www-data:www-data "$APP_DIR" 2>/dev/null || chown -R www:www "$APP_DIR" 2>/dev/null || true
cp deploy/material-inventory.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable material-inventory
systemctl restart material-inventory

echo "==> Nginx"
cp deploy/nginx-material.conf /etc/nginx/conf.d/material.conf
nginx -t && systemctl enable nginx && systemctl restart nginx

echo "完成。请确认阿里云安全组已放行 TCP 80"
echo "访问 http://101.133.149.106/"
