#!/bin/bash
# 在服务器项目目录执行：bash deploy/check-tagging.sh
set -e
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; source .env; set +a; fi

echo "==> 环境"
if [ -n "$XIAOMI_API_KEY" ]; then
  LEN=${#XIAOMI_API_KEY}
  echo "XIAOMI_API_KEY: 已设置 (${LEN} 字符)"
  if [ "$LEN" -gt 80 ]; then
    echo "WARN: Key 过长，可能误粘贴多次。请运行: bash deploy/set-xiaomi-key.sh"
  fi
else
  echo "XIAOMI_API_KEY: 未设置"
fi

echo "==> 打标队列（本地 DB，无需登录）"
./venv/bin/python3 <<'PY'
import json
import sqlite3
from pathlib import Path
import sys
sys.path.insert(0, "shared")
from vision_tagger import resolve_api_key

for name, db_path in [("纽扣", "button/button_tags.db"), ("面料", "fabric/fabric_tags.db")]:
    p = Path(db_path)
    if not p.exists():
        print(f"  {name}: 无 {db_path}")
        continue
    conn = sqlite3.connect(p)
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM sku_tags GROUP BY status").fetchall())
    print(f"  {name}: {json.dumps(counts, ensure_ascii=False)}")
    failed = conn.execute(
        "SELECT detail_code, substr(error,1,120) FROM sku_tags WHERE status='failed' LIMIT 3"
    ).fetchall()
    for code, err in failed:
        print(f"    failed {code}: {err}")

print("  api_key:", "OK" if resolve_api_key() else "MISSING")
PY
echo

echo "==> 测试主图下载 + 小米 API"
./venv/bin/python3 <<'PY'
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "shared")
from vision_tagger import resolve_api_key, analyze_image
from image_fetch import download_image

key = resolve_api_key()
print("resolve_api_key:", f"OK ({len(key)} chars)" if key else "MISSING")
if not key:
    raise SystemExit("请运行: bash deploy/set-xiaomi-key.sh")

url = "https://oss.scm321.com/BizFile/5125/Material/230615172114297-30.jpg"
p = Path(tempfile.gettempdir()) / "tag_test.jpg"
download_image(url, p)
print("download:", p.stat().st_size, "bytes")
v = analyze_image(p)
print("vision OK:", v.get("孔型"), v.get("视觉描述", "")[:50])
PY

echo "全部通过。看板点「补打标」或失败卡片「重新打标」"
