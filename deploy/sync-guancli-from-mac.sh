#!/bin/bash
# 在 Mac 上执行：把本机 guancli 配置复制到阿里云（需已能 ssh root@101.133.149.106）
set -e
SERVER=${1:-root@101.133.149.106}
CFG="$HOME/Library/Application Support/guancli/config.json"

if [ ! -f "$CFG" ]; then
  echo "未找到本机 guancli 配置: $CFG"
  echo "请先在 Mac 上执行: guancli auth login"
  exit 1
fi

echo "上传到 $SERVER ..."
ssh "$SERVER" 'mkdir -p /root/.config/guancli /var/www/.config/guancli'
scp "$CFG" "$SERVER:/root/.config/guancli/config.json"
ssh "$SERVER" 'cp /root/.config/guancli/config.json /var/www/.config/guancli/ && chown -R www-data:www-data /var/www 2>/dev/null || chown -R www:www /var/www 2>/dev/null || true'
echo "完成。在服务器上验证:"
echo "  ssh $SERVER 'guancli auth status && guancli ds preview r6d0ada08a78746bca88007e --limit 1 --format json'"
