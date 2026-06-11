#!/usr/bin/env python3
"""
export_tags.py — 把 fabric_tags.db / button_tags.db 导出为 JSON 到 tags/

约定（与 Iris 1a+2a+3a 一致）：
- 目录：tags/  (与本脚本同级)
- 文件命名：tags/fabric_YYYY-MM-DD.json / tags/button_YYYY-MM-DD.json
- 字段：detail_code, image_url, tags_json (对象), status, has_vision, error, updated_at
- 配套脚本：export_tags.sh  (git add + commit + push)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TAGS_DIR = ROOT / "tags"


def export_one(db_path: Path, kind: str, date_str: str) -> Path:
    """导出单个 db 到 tags/{kind}_{date_str}.json"""
    if not db_path.exists():
        print(f"  ⚠️  跳过（不存在）: {db_path}")
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT detail_code, image_url, tags_json, status, has_vision, error, updated_at "
        "FROM sku_tags"
    ).fetchall()
    conn.close()

    out = []
    for r in rows:
        try:
            tags = json.loads(r["tags_json"])
        except (json.JSONDecodeError, TypeError):
            tags = {"_raw": r["tags_json"]}
        out.append({
            "detail_code": r["detail_code"],
            "image_url": r["image_url"],
            "tags": tags,
            "status": r["status"],
            "has_vision": bool(r["has_vision"]),
            "error": r["error"],
            "updated_at": r["updated_at"],
        })

    TAGS_DIR.mkdir(exist_ok=True)
    out_path = TAGS_DIR / f"{kind}_{date_str}.json"
    out_path.write_text(
        json.dumps({
            "_meta": {
                "kind": kind,
                "export_time": datetime.now().isoformat(),
                "db_path": str(db_path.relative_to(ROOT)),
                "count": len(out),
                "schema_version": 1,
            },
            "items": out,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  ✅ {kind}: {len(out)} 款 → {out_path.relative_to(ROOT)}")
    return out_path


def main():
    print("=" * 50)
    print("MARIUS 视觉标签导出")
    print("=" * 50)

    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"📅 日期: {date_str}\n")

    fabric_path = export_one(ROOT / "fabric" / "fabric_tags.db", "fabric", date_str)
    button_path = export_one(ROOT / "shared" / "button_tags.db", "button", date_str)

    if not fabric_path and not button_path:
        print("❌ 没有任何 db 可导出")
        return 1

    print(f"\n💾 已写入: {TAGS_DIR.relative_to(ROOT)}/")
    print(f"   下一步: bash export_tags.sh  (git add + commit + push)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
