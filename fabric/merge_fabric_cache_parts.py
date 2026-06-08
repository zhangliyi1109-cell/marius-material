#!/usr/bin/env python3
"""合并 part 缓存到 .fabric_visual_cache.json"""

import json
from pathlib import Path

ROOT = Path(__file__).parent
MAIN = ROOT / ".fabric_visual_cache.json"
PARTS = [ROOT / f".fabric_visual_cache_part{i}.json" for i in range(1, 5)]

cache: dict = {}
if MAIN.exists():
    cache.update(json.loads(MAIN.read_text(encoding="utf-8")))
for p in PARTS:
    if p.exists():
        cache.update(json.loads(p.read_text(encoding="utf-8")))
MAIN.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"merged {len(cache)} urls")
