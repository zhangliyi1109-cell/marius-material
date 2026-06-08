#!/bin/bash
# 在服务器项目目录执行：bash deploy/check-tagging.sh
set -e
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; source .env; set +a; fi

echo "==> 环境"
echo "XIAOMI_API_KEY: ${XIAOMI_API_KEY:+已设置 (${#XIAOMI_API_KEY} 字符)}${XIAOMI_API_KEY:-未设置}"

echo "==> 打标队列状态"
curl -s http://127.0.0.1:8080/button/api/tag-jobs | python3 -m json.tool 2>/dev/null || true
echo

echo "==> 失败样本（纽扣 DB）"
python3 <<'PY'
import sqlite3
from pathlib import Path
db = Path("button/button_tags.db")
if not db.exists():
    print("无 button_tags.db")
else:
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT detail_code, error FROM sku_tags WHERE status='failed' LIMIT 5"
    ).fetchall()
    if not rows:
        print("无 failed 记录")
    for code, err in rows:
        print(f"  {code}: {err}")
PY

echo "==> 测试主图下载 + 小米 API"
./venv/bin/python3 <<'PY'
import os, sys, tempfile
from pathlib import Path
import requests
sys.path.insert(0, "shared")
from vision_tagger import resolve_api_key, analyze_image
from image_fetch import download_image

key = resolve_api_key()
print("resolve_api_key:", "OK" if key else "MISSING")
if not key:
    raise SystemExit("请在 .env 设置 XIAOMI_API_KEY 后 systemctl restart material-inventory")

url = "https://oss.scm321.com/BizFile/5125/Material/230615172114297-30.jpg"
p = Path(tempfile.gettempdir()) / "tag_test.jpg"
download_image(url, p)
print("download:", p.stat().st_size, "bytes")
v = analyze_image(p)
print("vision OK:", v.get("孔型"), v.get("视觉描述", "")[:50])
PY

echo "全部通过。可在看板点「补打标」或对失败卡片点「重新打标」"
