#!/bin/bash
# 在服务器项目目录执行：bash deploy/check-tagging.sh
set -e
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; source .env; set +a; fi

echo "==> 环境"
for VAR in XIAOMI_API_KEY KIMI_API_KEY MOONSHOT_API_KEY; do
  eval "VAL=\${$VAR:-}"
  if [ -n "$VAL" ]; then
    LEN=${#VAL}
    echo "$VAR: 已设置 (${LEN} 字符)"
    if [ "$VAR" = "XIAOMI_API_KEY" ] && [ "$LEN" -gt 80 ]; then
      echo "WARN: Key 过长，可能误粘贴多次。请运行: bash deploy/set-xiaomi-key.sh"
    fi
  fi
done

echo "==> 打标队列（本地 DB，无需登录）"
./venv/bin/python3 <<'PY'
import json
import sqlite3
from pathlib import Path
import sys
sys.path.insert(0, "shared")
from vision_tagger import api_key_env_name, resolve_api_key, uses_vision_api, vision_settings

for name, cfg_path, db_path in [
    ("纽扣", "button/inventory_config.json", "button/button_tags.db"),
    ("面料", "fabric/inventory_config.json", "fabric/fabric_tags.db"),
]:
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    vp = (cfg.get("vision") or {}).get("provider", "xiaomi" if name == "纽扣" else "agent")
    if uses_vision_api(vp):
        vs = vision_settings(cfg.get("vision"))
        key_ok = bool(resolve_api_key(vs["provider"]))
        print(f"  {name} provider={vs['provider']} model={vs['model']} key={'OK' if key_ok else 'MISSING'}")
    else:
        print(f"  {name} provider={vp} (agent 缓存，无需 API Key)")
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

PY
echo

echo "==> 测试主图下载 + 视觉 API（按纽扣 inventory_config.json 的 provider）"
./venv/bin/python3 <<'PY'
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "shared")
from vision_tagger import analyze_image, api_key_env_name, resolve_api_key, uses_vision_api, vision_settings
from image_fetch import download_image

cfg = json.loads(Path("button/inventory_config.json").read_text(encoding="utf-8"))
vision_cfg = cfg.get("vision") or {}
provider = (vision_cfg.get("provider") or "xiaomi").strip().lower()
if not uses_vision_api(provider):
    raise SystemExit(f"纽扣 provider={provider}，无需 API 测试")
vs = vision_settings(vision_cfg)
provider = vs["provider"]
key = resolve_api_key(provider)
print(f"provider={provider} model={vs['model']}")
print("api_key:", f"OK ({len(key)} chars)" if key else "MISSING")
if not key:
    raise SystemExit(f"请在 .env 设置 {api_key_env_name(provider)}")

url = "https://oss.scm321.com/BizFile/5125/Material/230615172114297-30.jpg"
p = Path(tempfile.gettempdir()) / "tag_test.jpg"
download_image(url, p)
print("download:", p.stat().st_size, "bytes")
v = analyze_image(p, provider=provider, base_url=vs["base_url"], model=vs["model"])
print("vision OK:", v.get("孔型"), v.get("视觉描述", "")[:50])
PY

echo "全部通过。看板点「补打标」或失败卡片「重新打标」"
