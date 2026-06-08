#!/usr/bin/env python3
"""合并视觉缓存并写回 seed_inventory.json。"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parent
JSON_PATH = ROOT / "seed_inventory.json"
CACHE_PATH = ROOT / "visual_cache.json"

spec = importlib.util.spec_from_file_location(
    "extract", ROOT / "extract_button_visual_tags.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main() -> None:
    items = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    enriched = mod.apply_tags(items, cache)
    JSON_PATH.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"items={len(enriched)} cache_urls={len(cache)}")


if __name__ == "__main__":
    main()
