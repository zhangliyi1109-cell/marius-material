#!/usr/bin/env python3
"""合并视觉缓存并写回纽扣库存清单。"""

import json
from pathlib import Path

ROOT = Path(__file__).parent
JSON_PATH = ROOT / "纽扣库存清单.json"
CACHE_FILES = [
    ROOT / f".button_visual_cache_part{i}.json"
    for i in range(1, 5)
]
CACHE_PATH = ROOT / ".button_visual_cache.json"

# import tag helpers from main script
import importlib.util

spec = importlib.util.spec_from_file_location(
    "extract", ROOT / "extract_button_visual_tags.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def load_vision_cache() -> dict:
    cache: dict = {}
    if CACHE_PATH.exists():
        cache.update(json.loads(CACHE_PATH.read_text(encoding="utf-8")))
    for path in CACHE_FILES:
        if path.exists():
            cache.update(json.loads(path.read_text(encoding="utf-8")))
    return cache


def main() -> None:
    items = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    cache = load_vision_cache()
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    enriched = mod.apply_tags(items, cache)
    JSON_PATH.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with_img = sum(1 for d in enriched if (d.get("主图") or "").strip())
    with_vision = sum(
        1
        for d in enriched
        if (d.get("主图") or "").strip() and cache.get((d.get("主图") or "").strip())
    )
    print(f"items={len(enriched)} cache_urls={len(cache)} vision_matched={with_vision}/{with_img}")


if __name__ == "__main__":
    main()
