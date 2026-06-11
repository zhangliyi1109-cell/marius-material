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
    if not CACHE_PATH.exists():
        print(f"❌ 文件不存在: {CACHE_PATH}")
        return 1

    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    print(f"原条目: {len(cache)}")

    # 1. 统计原值
    pre_stats: dict[str, Counter] = {k: Counter() for k in SINGLE_KEYS + LIST_KEYS}
    for v in cache.values():
        for k in SINGLE_KEYS:
            if v.get(k):
                pre_stats[k][v[k]] += 1
        for k in LIST_KEYS:
            for x in v.get(k, []):
                pre_stats[k][x] += 1

    # 2. 归一化
    cleaned_cache = {}
    unknown_total = 0
    removed_count = 0  # 被过滤掉的总标签数
    per_item_removed = []  # 记录被移除的标签（用于报告）

    for url, raw in cache.items():
        cleaned = normalize_tags(VOCAB, raw, SINGLE_KEYS, LIST_KEYS)
        # 统计被移除的
        for k in LIST_KEYS:
            orig_set = set(raw.get(k, []))
            new_set = set(cleaned.get(k, []))
            removed = orig_set - new_set
            for r in removed:
                removed_count += 1
                per_item_removed.append((url[:50], k, r))
        # 单值字段
        for k in SINGLE_KEYS:
            if raw.get(k) and raw.get(k) != cleaned.get(k):
                removed_count += 1
                per_item_removed.append((url[:50], k, f"{raw.get(k)} → 删"))
        # 找未知的
        unknown = get_unknown_tags(VOCAB, raw, SINGLE_KEYS + LIST_KEYS)
        for k, vals in unknown.items():
            unknown_total += len(vals)
        cleaned_cache[url] = cleaned

    # 3. 写回
    CACHE_PATH.write_text(
        json.dumps(cleaned_cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 4. 报告
    print()
    print("=" * 50)
    print("修复完成报告")
    print("=" * 50)
    print(f"被过滤的标签: {removed_count} 条")
    print()
    print("=== 主要被移除（按值统计）===")
    removed_counter = Counter()
    for _, k, r in per_item_removed:
        # 提取主词
        main = r.split(" → ")[0] if " → " in r else r
        removed_counter[(k, main)] += 1
    for (k, v), n in removed_counter.most_common(15):
        print(f"  {n:3d}  {k}={v}")

    # 5. 修复后统计
    print()
    print("=== 修复后字段值统计 ===")
    post_stats: dict[str, Counter] = {k: Counter() for k in SINGLE_KEYS + LIST_KEYS}
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


if __name__ == "__main__":
    main()
