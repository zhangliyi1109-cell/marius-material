#!/bin/bash
# 仅更新小米 API Key：bash deploy/set-xiaomi-key.sh
set -e
cd "$(dirname "$0")/.."

read -r -s -p "XIAOMI_API_KEY（粘贴一次即可）: " KEY
echo
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
if [ -z "$KEY" ]; then echo "不能为空"; exit 1; fi
if [ "${#KEY}" -gt 80 ]; then
  echo "WARN: Key 长度 ${#KEY} 异常，将只保留开头 tp- 段"
  KEY="$(printf '%s' "$KEY" | sed -E 's/^(tp-[a-zA-Z0-9]{20,60}).*/\1/')"
fi
if ! printf '%s' "$KEY" | grep -qE '^tp-[a-zA-Z0-9]{20,60}$'; then
  echo "ERROR: Key 格式不对，应为 tp- 开头、约 50 字符"
  exit 1
fi

export NEW_XIAOMI_KEY="$KEY"
./venv/bin/python3 <<'PY'
from pathlib import Path
import os
import re

key = os.environ["NEW_XIAOMI_KEY"]
path = Path(".env")
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
out, found = [], False
for line in lines:
    if re.match(r"^XIAOMI_API_KEY=", line):
        out.append(f"XIAOMI_API_KEY={key}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"XIAOMI_API_KEY={key}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"已写入 XIAOMI_API_KEY（{len(key)} 字符）")
PY

chmod 600 .env
systemctl restart material-inventory
sleep 2
curl -s http://127.0.0.1:8080/health
echo
echo "运行: bash deploy/check-tagging.sh"
