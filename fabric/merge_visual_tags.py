#!/usr/bin/env python3
"""将 visual_cache.json 合并进 fabric_tags.db。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CACHE_PATH = ROOT / "visual_cache.json"
CONFIG_PATH = ROOT / "inventory_config.json"

sys.path.insert(0, str(ROOT.parent / "shared"))
sys.path.insert(0, str(ROOT))


def load_bi_fabric_rows() -> list[dict]:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    proc = subprocess.run(
        [
            "guancli", "ds", "preview", cfg["dataset_id"],
            "--limit", "500",
            "--filter", f"可配库存 GT {cfg['min_stock_default']}",
            "--filter", f"物料大类名称 EQ {cfg['material_category']}",
            "--format", "json",
        ],
        capture_output=True, text=True, timeout=120,
    )
    rows = json.loads(proc.stdout)
    return [r for r in rows if (r.get("物料大类名称") or "") == cfg["material_category"]]


def parse_color_spec(spec: str) -> dict:
    import re
    m = re.search(r"\[([^\]]+)\]([^;]*)", spec or "")
    return {
        "颜色": m.group(1).strip() if m else "",
        "颜色描述": m.group(2).strip() if m else "",
        "颜色规格": spec or "",
    }


def main() -> None:
    from tag_pipeline import apply_agent_cache, get_store

    if not CACHE_PATH.exists():
        print("no cache:", CACHE_PATH)
        return
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    store = get_store(cfg)
    for url, vision in json.loads(CACHE_PATH.read_text(encoding="utf-8")).items():
        if url and isinstance(vision, dict):
            store.save_vision(url.strip(), vision, status="done")
    norm = []
    for r in load_bi_fabric_rows():
        spec = parse_color_spec(r.get("物料颜色规格名称") or "")
        norm.append({
            "物料明细编码": (r.get("物料明细编码") or "").strip(),
            "物料名称": r.get("物料名称", ""),
            "物料编码": r.get("物料编码", ""),
            "颜色规格": spec["颜色规格"],
            "颜色": spec["颜色"],
            "物料种类": r.get("物料种类", ""),
            "主图": (r.get("主图") or "").strip(),
        })
    updated = apply_agent_cache(store, norm)
    print(f"cache_urls={len(json.loads(CACHE_PATH.read_text()))} sku_synced={updated}")
    print("db_counts", store.count_by_status())


if __name__ == "__main__":
    main()
