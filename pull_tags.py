#!/usr/bin/env python3
"""
pull_tags.py — 拉服务器最新 tags/*.json 并导入本地 sqlite

与 export_tags.py 配对使用：
- 服务器 export_tags.py → tags/fabric_YYYY-MM-DD.json
- 本地 pull_tags.py → 读 tags/*.json → 写回本地 fabric_tags.db / button_tags.db

约定（与 Iris 1a+2a+3a 一致）：
- 服务器实时 push（打完标立刻 git push）
- 本地每小时拉一次（cron 配合）
- 取每种类型**最新**的 JSON 导入
"""
from __future__ import annotations

import glob
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TAGS_DIR = ROOT / "tags"


def import_one(db_path: Path, kind: str) -> int:
    """导入最新 tags/{kind}_*.json → db_path

    冲突解决：UPSERT (INSERT OR REPLACE) by detail_code
    - 服务器标签覆盖本地（服务器是权威）
    - 本地独有的（非服务器来源）保留：先备份再 import
    """
    files = sorted(glob.glob(str(TAGS_DIR / f"{kind}_*.json")))
    if not files:
        print(f"  ⏭️  {kind}: 无 JSON 文件可导入（服务器还没导出过）")
        return 0

    latest = Path(files[-1])
    print(f"  📄 {kind}: 读 {latest.name}")

    data = json.loads(latest.read_text(encoding="utf-8"))
    items = data.get("items", [])
    meta = data.get("_meta", {})
    print(f"     服务器导出于: {meta.get('export_time', '?')}  数量: {len(items)}")

    if not db_path.exists():
        print(f"  ⚠️  本地 db 不存在: {db_path}")
        return 0

    # 备份原 db
    backup = db_path.with_suffix(f".db.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    import shutil
    shutil.copy2(db_path, backup)
    print(f"     备份: {backup.name}")

    conn = sqlite3.connect(str(db_path))
    before_count = conn.execute("SELECT COUNT(*) FROM sku_tags").fetchone()[0]

    upserted = 0
    inserted = 0
    updated = 0
    for r in items:
        try:
            tags_json = json.dumps(r["tags"], ensure_ascii=False)
        except (TypeError, ValueError):
            tags_json = json.dumps({"_raw": str(r["tags"])}, ensure_ascii=False)

        # 检查是否已存在
        cur = conn.execute(
            "SELECT 1 FROM sku_tags WHERE detail_code = ?", (r["detail_code"],)
        )
        exists = cur.fetchone() is not None

        conn.execute(
            """
            INSERT OR REPLACE INTO sku_tags
              (detail_code, image_url, tags_json, status, has_vision, error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["detail_code"],
                r.get("image_url", ""),
                tags_json,
                r.get("status", "done"),
                1 if r.get("has_vision") else 0,
                r.get("error", ""),
                r.get("updated_at", datetime.now().timestamp()),
            ),
        )
        upserted += 1
        if exists:
            updated += 1
        else:
            inserted += 1

    conn.commit()
    after_count = conn.execute("SELECT COUNT(*) FROM sku_tags").fetchone()[0]
    conn.close()

    print(f"     导入: {upserted} 款 (新增 {inserted} / 更新 {updated})")
    print(f"     库变化: {before_count} → {after_count}")
    return upserted


def main():
    print("=" * 50)
    print("MARIUS 视觉标签拉取（本地）")
    print("=" * 50)
    print(f"⏱️  {datetime.now().isoformat()}\n")

    if not TAGS_DIR.exists():
        print(f"❌ tags 目录不存在: {TAGS_DIR}")
        print("   请先 git pull 拉取服务器最新代码")
        return 1

    n1 = import_one(ROOT / "fabric" / "fabric_tags.db", "fabric")
    n2 = import_one(ROOT / "shared" / "button_tags.db", "button")

    if n1 == 0 and n2 == 0:
        print("\n⚠️  没有任何导入。可能服务器还没打过标。")
        return 0

    print(f"\n✅ 完成 (fabric={n1} 款, button={n2} 款)")
    print(f"\n📋 下一步:")
    print(f"   python3 /Users/zhangzhang/.openclaw/workspace/1_MARIUS/AI项目/知识库/原始数据/库存快照/vision_sync_local.py")
    print(f"   # vision_sync_local.py 会从本地 material 服务 (127.0.0.1:8080) 拉面料+纽扣+视觉标签，写入知识库 MD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
