#!/usr/bin/env python3
"""
fix_button_tags.py — 修复纽扣标签库的污染问题

输入：button/visual_cache.json
输出：覆盖更新（保留原结构）+ 报告

修复内容：
1. 标签归一化（走预设词库 + 同义词映射）
2. 不在词库的标签直接移除（"自然" 等 Iris 删掉的）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "shared"))

from tag_normalizer import load_vocabulary, normalize_tags, get_unknown_tags

VOCAB = load_vocabulary("button")
CACHE_PATH = ROOT / "button" / "visual_cache.json"

# 字段定义（button 的字段）
SINGLE_KEYS = ("孔型", "造型", "光泽", "边缘")
LIST_KEYS = ("装饰元素", "风格", "适用场景")


def main():
    # 两个数据文件都处理（服务器读 seed_inventory.json，本地缓存 visual_cache.json）
    targets = [
        (ROOT / "button" / "seed_inventory.json", "seed_inventory.json"),
        (CACHE_PATH, "visual_cache.json"),
    ]

    for path, label in targets:
        if not path.exists():
            print(f"⚠️  跳过（不存在）: {path}")
            continue

        print()
        print("=" * 60)
        print(f"处理 {label}")
        print("=" * 60)

        if label == "seed_inventory.json":
            # seed 是 list[dict]，每个 item 都有"视觉标签"子字段
            seed = json.loads(path.read_text(encoding="utf-8"))
            print(f"原条目: {len(seed)}")

            pre_stats, post_stats = _count_seed(seed)
            print_pre_summary(pre_stats)

            cleaned = _clean_seed(seed)

            print_post_summary(post_stats_for_cleaned(cleaned))

            # 写回
            path.write_text(
                json.dumps(cleaned, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"✅ {label} 已更新")
        else:
            # visual_cache.json 是 dict[url, tags]
            cache = json.loads(path.read_text(encoding="utf-8"))
            print(f"原条目: {len(cache)}")

            pre_stats = {k: Counter() for k in SINGLE_KEYS + LIST_KEYS}
            for v in cache.values():
                for k in SINGLE_KEYS:
                    if v.get(k):
                        pre_stats[k][v[k]] += 1
                for k in LIST_KEYS:
                    for x in v.get(k, []):
                        pre_stats[k][x] += 1

            cleaned_cache = {}
            unknown_total = 0
            removed_count = 0
            per_item_removed = []

            for url, raw in cache.items():
                cleaned = normalize_tags(VOCAB, raw, SINGLE_KEYS, LIST_KEYS)
                for k in LIST_KEYS:
                    orig_set = set(raw.get(k, []))
                    new_set = set(cleaned.get(k, []))
                    removed = orig_set - new_set
                    for r in removed:
                        removed_count += 1
                        per_item_removed.append((url[:50], k, r))
                for k in SINGLE_KEYS:
                    if raw.get(k) and raw.get(k) != cleaned.get(k):
                        removed_count += 1
                        per_item_removed.append((url[:50], k, f"{raw.get(k)} → 删"))
                unknown = get_unknown_tags(VOCAB, raw, SINGLE_KEYS + LIST_KEYS)
                for k, vals in unknown.items():
                    unknown_total += len(vals)
                cleaned_cache[url] = cleaned

            print(f"被过滤的标签: {removed_count} 条")
            print()
            print("=== 主要被移除（按值统计）===")
            removed_counter = Counter()
            for _, k, r in per_item_removed:
                main = r.split(" → ")[0] if " → " in r else r
                removed_counter[(k, main)] += 1
            for (k, v), n in removed_counter.most_common(15):
                print(f"  {n:3d}  {k}={v}")

            post_stats = {k: Counter() for k in SINGLE_KEYS + LIST_KEYS}
            for v in cleaned_cache.values():
                for k in SINGLE_KEYS:
                    if v.get(k):
                        post_stats[k][v[k]] += 1
                for k in LIST_KEYS:
                    for x in v.get(k, []):
                        post_stats[k][x] += 1

            for k in SINGLE_KEYS + LIST_KEYS:
                pre = pre_stats[k]
                post = post_stats[k]
                print(f"\n  {k}: {len(pre)} → {len(post)} 个值")
                for val, n in post.most_common():
                    print(f"    {n:3d}  {val}")

            path.write_text(
                json.dumps(cleaned_cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"✅ {label} 已更新")


def _count_seed(seed: list[dict]) -> tuple[dict[str, Counter], None]:
    """统计 seed 数据的字段分布。"""
    pre_stats = {k: Counter() for k in SINGLE_KEYS + LIST_KEYS}
    for item in seed:
        tags = item.get("视觉标签") or {}
        for k in SINGLE_KEYS:
            if tags.get(k):
                pre_stats[k][tags[k]] += 1
        for k in LIST_KEYS:
            for x in tags.get(k, []) or []:
                pre_stats[k][x] += 1
    return pre_stats, None


def print_pre_summary(pre_stats: dict[str, Counter]) -> None:
    print()
    print("=== 修复前字段值统计 ===")
    for k in SINGLE_KEYS + LIST_KEYS:
        pre = pre_stats[k]
        print(f"\n  {k}: {len(pre)} 个值")
        for val, n in pre.most_common(10):
            print(f"    {n:3d}  {val}")


def print_post_summary(post_stats: dict[str, Counter]) -> None:
    print()
    print("=== 修复后字段值统计 ===")
    for k in SINGLE_KEYS + LIST_KEYS:
        post = post_stats[k]
        print(f"\n  {k}: {len(post)} 个值")
        for val, n in post.most_common(10):
            print(f"    {n:3d}  {val}")


def post_stats_for_cleaned(cleaned: list[dict]) -> dict[str, Counter]:
    post_stats = {k: Counter() for k in SINGLE_KEYS + LIST_KEYS}
    for item in cleaned:
        tags = item.get("视觉标签") or {}
        for k in SINGLE_KEYS:
            if tags.get(k):
                post_stats[k][tags[k]] += 1
        for k in LIST_KEYS:
            for x in tags.get(k, []) or []:
                post_stats[k][x] += 1
    return post_stats


def _clean_seed(seed: list[dict]) -> list[dict]:
    """归一化 seed_inventory.json 中每个 item 的 视觉标签。"""
    removed_counter: Counter = Counter()
    cleaned: list[dict] = []
    for item in seed:
        tags = item.get("视觉标签") or {}
        new_tags = normalize_tags(VOCAB, tags, SINGLE_KEYS, LIST_KEYS)
        # 统计被移除
        for k in LIST_KEYS:
            orig_set = set(tags.get(k, []) or [])
            new_set = set(new_tags.get(k, []) or [])
            for r in orig_set - new_set:
                removed_counter[(k, r)] += 1
        for k in SINGLE_KEYS:
            if tags.get(k) and tags.get(k) != new_tags.get(k):
                removed_counter[(k, str(tags.get(k)))] += 1
        new_item = dict(item)
        new_item["视觉标签"] = new_tags
        cleaned.append(new_item)

    print(f"\n被过滤的标签: {sum(removed_counter.values())} 条")
    print("=== 主要被移除（按值统计）===")
    for (k, v), n in removed_counter.most_common(20):
        print(f"  {n:3d}  {k}={v}")

    return cleaned


if __name__ == "__main__":
    main()
