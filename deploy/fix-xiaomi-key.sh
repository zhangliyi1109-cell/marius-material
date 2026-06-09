#!/bin/bash
# 修正 .env 里被重复粘贴的 XIAOMI_API_KEY
set -e
cd "$(dirname "$0")/.."
./venv/bin/python3 <<'PY'
from pathlib import Path
import re
import sys
sys.path.insert(0, "shared")
from vision_tagger import _sanitize_api_key

p = Path(".env")
if not p.exists():
    raise SystemExit("无 .env 文件")

lines = []
changed = False
for line in p.read_text(encoding="utf-8").splitlines():
    if line.startswith("XIAOMI_API_KEY="):
        raw = line.split("=", 1)[1]
        clean = _sanitize_api_key(raw)
        lines.append(f"XIAOMI_API_KEY={clean}")
        print(f"XIAOMI_API_KEY: {len(raw)} -> {len(clean)} 字符")
        changed = raw != clean
    else:
        lines.append(line)
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
if not changed:
    print("已是正确长度")
PY
chmod 600 .env
systemctl restart material-inventory
sleep 2
bash deploy/check-tagging.sh
