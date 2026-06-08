#!/bin/bash
# 仅更新小米 API Key：bash deploy/set-xiaomi-key.sh
set -e
cd "$(dirname "$0")/.."
read -r -s -p "XIAOMI_API_KEY: " KEY
echo
if [ -z "$KEY" ]; then echo "不能为空"; exit 1; fi
if [ -f .env ]; then
  if grep -q '^XIAOMI_API_KEY=' .env; then
    sed -i.bak "s|^XIAOMI_API_KEY=.*|XIAOMI_API_KEY=${KEY}|" .env
  else
    echo "XIAOMI_API_KEY=${KEY}" >> .env
  fi
else
  echo "XIAOMI_API_KEY=${KEY}" > .env
fi
chmod 600 .env
systemctl restart material-inventory
sleep 1
curl -s http://127.0.0.1:8080/health
echo
echo "完成。运行 bash deploy/check-tagging.sh 做完整测试"
