#!/bin/bash
# 将运行时 .db 导出为可提交 Git 的 JSON（在 Mac 或服务器项目根目录执行）
set -e
cd "$(dirname "$0")/.."

PYTHON="./venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="python3"

"$PYTHON" <<'PY'
import json
import sqlite3
from pathlib import Path

ROOT = Path(".")


def export_cache(db: Path, out: Path) -> int:
    if not db.exists():
        print(f"skip {db} (not found)")
        return 0
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT image_url, vision_json FROM image_vision WHERE status='done'"
    ).fetchall()
    cache = {}
    for url, vision_json in rows:
        if not url:
            continue
        try:
            cache[url.strip()] = json.loads(vision_json)
        except json.JSONDecodeError:
            pass
    out.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"exported {len(cache)} images -> {out}")
    return len(cache)


def export_seed_from_db(db: Path, seed_path: Path) -> int:
    if not db.exists() or not seed_path.exists():
        print(f"skip seed export ({db.name} or {seed_path.name} missing)")
        return 0
    conn = sqlite3.connect(db)
    rows = conn.execute(
        """
        SELECT detail_code, tags_json FROM sku_tags
        WHERE status IN ('done', 'text_only')
        """
    ).fetchall()
    by_code = {}
    for code, tags_json in rows:
        if not code:
            continue
        try:
            tags = json.loads(tags_json)
        except json.JSONDecodeError:
            continue
        if tags.get("视觉描述") or tags.get("关键词"):
            by_code[code.strip()] = tags

    items = json.loads(seed_path.read_text(encoding="utf-8"))
    updated = 0
    for item in items:
        code = (item.get("物料明细编码") or "").strip()
        if code in by_code:
            item["视觉标签"] = by_code[code]
            updated += 1
    seed_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"merged {updated} sku tags into {seed_path} (db had {len(by_code)} done)")
    return updated


export_cache(ROOT / "button/button_tags.db", ROOT / "button/visual_cache.json")
export_cache(ROOT / "fabric/fabric_tags.db", ROOT / "fabric/visual_cache.json")
export_seed_from_db(ROOT / "button/button_tags.db", ROOT / "button/seed_inventory.json")
PY

if [ -f button/seed_inventory.json ]; then
  "$PYTHON" button/merge_visual_tags.py
fi

echo
echo "下一步（提交到 GitHub）："
echo "  git add button/visual_cache.json button/seed_inventory.json fabric/visual_cache.json"
echo "  git commit -m \"Sync vision tags from runtime database\""
echo "  git push origin main"
echo
echo "目标服务器："
echo "  cd /root/marius-material && git pull"
echo "  rm -f button/button_tags.db fabric/fabric_tags.db"
echo "  systemctl restart material-inventory"
