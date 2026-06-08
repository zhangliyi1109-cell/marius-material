#!/usr/bin/env python3
"""将 Agent/手工维护的 .fabric_visual_cache.json 合并进 fabric_tags.db。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
CACHE_PATH = ROOT / ".fabric_visual_cache.json"
CACHE_PARTS = [ROOT / f".fabric_visual_cache_part{i}.json" for i in range(1, 5)]
CONFIG_PATH = ROOT / "fabric_inventory_config.json"


def load_full_cache() -> dict:
    cache: dict = {}
    if CACHE_PATH.exists():
        cache.update(json.loads(CACHE_PATH.read_text(encoding="utf-8")))
    for p in CACHE_PARTS:
        if p.exists():
            cache.update(json.loads(p.read_text(encoding="utf-8")))
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cache


def load_extract():
    spec = importlib.util.spec_from_file_location(
        "fabric_extract", ROOT / "extract_fabric_visual_tags.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_bi_fabric_rows() -> list[dict]:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    proc = subprocess.run(
        [
            "guancli",
            "ds",
            "preview",
            cfg["dataset_id"],
            "--limit",
            "500",
            "--filter",
            f"可配库存 GT {cfg['min_stock_default']}",
            "--filter",
            f"物料大类名称 EQ {cfg['material_category']}",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
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
    from fabric_tag_pipeline import apply_agent_cache, get_store

    if not CACHE_PATH.exists():
        print("no cache file:", CACHE_PATH)
        return
    cache = load_full_cache()
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    store = get_store(cfg)
    rows = load_bi_fabric_rows()
    # normalize rows for apply_agent_cache
    norm = []
    for r in rows:
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
    print(f"cache_urls={len(cache)} sku_synced={updated}")
    print("db_counts", store.count_by_status())


if __name__ == "__main__":
    main()
