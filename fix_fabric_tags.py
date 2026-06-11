#!/usr/bin/env python3
"""
fix_fabric_tags.py — 修复面料标签库的三大问题：
1. 标签归一化（走预设词库 + 同义词映射）
2. 克重从 BI D1 自动拉取（用 fabric_weight_fetcher）
3. 写回 SQLite DB

用法：
    python3 fix_fabric_tags.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT))

from tag_normalizer import load_vocabulary, normalize_tags
from fabric_weight_fetcher import classify_weight
from tag_semantic_rules import validate_tags

DB_PATH = ROOT / "fabric" / "fabric_tags.db"
JSON_PATH = ROOT / "tags" / "fabric_2026-06-11.json"
VOCAB = load_vocabulary("fabric")

# BI D1 缓存
BI_CACHE = Path("/tmp/bi_d1_codes.json")
if not BI_CACHE.exists():
    print(f"❌ BI D1 缓存不存在: {BI_CACHE}")
    print("   请先运行: python3 -c 'fetch BI D1 all codes'")
    sys.exit(1)

bi = json.loads(BI_CACHE.read_text())
BI_CODES = set(bi["all_codes"])
BI_WEIGHTS = bi["weights"]


def find_bi_code(detail_code: str) -> str | None:
    """detail_code 是明细编码（含颜色后缀），BI 物料编码是主编码（前缀）。"""
    for length in range(len(detail_code), 2, -1):
        prefix = detail_code[:length]
        if prefix in BI_CODES:
            return prefix
    return None


def main():
    # 1. 读 DB
    if not DB_PATH.exists():
        print(f"❌ DB 不存在: {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 2. 加载 JSON 备份（用于持久化）—— 但优先以 DB 为准
    rows = list(conn.execute(
        "SELECT detail_code, image_url, tags_json, status, has_vision, error, updated_at "
        "FROM sku_tags"
    ))
    print(f"DB 总行数: {len(rows)}")

    # 3. 逐条修复
    single_keys = ("织法组织", "表面质感", "花纹图案", "厚薄感", "色系", "克重档位")
    list_keys = ("风格",)

    stats = {
        "total": len(rows),
        "tag_normalized": 0,
        "bi_matched": 0,
        "weight_filled": 0,
        "weight_dist": {},
        "semantic_violations": 0,
        "violations_by_rule": {},
    }

    for row in rows:
        code = row["detail_code"]
        try:
            tags = json.loads(row["tags_json"])
        except (json.JSONDecodeError, TypeError):
            continue

        orig = dict(tags)
        # 3.1 标签归一化
        normed = normalize_tags(VOCAB, tags, single_keys, list_keys)
        if any(orig.get(k) != normed.get(k) for k in single_keys):
            stats["tag_normalized"] += 1
        if set(orig.get("风格", [])) != set(normed.get("风格", [])):
            stats["tag_normalized"] += 1

        # 3.2 BI D1 匹配 + 克重
        bi_code = find_bi_code(code)
        if bi_code:
            stats["bi_matched"] += 1
            weight = BI_WEIGHTS.get(bi_code)
            if weight:
                weight_class = classify_weight(weight)
                normed["克重档位"] = weight_class
                normed["克重数值"] = weight
                normed["BI物料编码"] = bi_code
                stats["weight_filled"] += 1
                stats["weight_dist"][weight_class] = stats["weight_dist"].get(weight_class, 0) + 1

        # 3.3 语义校验（互斥/必选/物性反推）
        weight_g = normed.get("克重数值")
        comp = normed.get("成分", "")
        cleaned, violations = validate_tags(normed, weight_g, comp)
        if violations:
            stats["semantic_violations"] += len(violations)
            for v in violations:
                rule = v.split(":")[0]
                stats["violations_by_rule"][rule] = stats["violations_by_rule"].get(rule, 0) + 1
        normed = cleaned

        # 3.4 写回 DB
        conn.execute(
            "UPDATE sku_tags SET tags_json = ? WHERE detail_code = ?",
            (json.dumps(normed, ensure_ascii=False), code),
        )

    conn.commit()
    conn.close()

    # 4. 报告
    print()
    print("=" * 50)
    print("修复完成报告")
    print("=" * 50)
    print(f"总条数: {stats['total']}")
    print(f"标签归一化修正: {stats['tag_normalized']}")
    print(f"BI D1 主编码匹配: {stats['bi_matched']} ({stats['bi_matched']/stats['total']*100:.1f}%)")
    print(f"克重填充: {stats['weight_filled']} ({stats['weight_filled']/stats['total']*100:.1f}%)")
    print(f"语义违规修复: {stats['semantic_violations']} 条")
    if stats["violations_by_rule"]:
        print("  按规则分布:")
        for k, n in sorted(stats["violations_by_rule"].items(), key=lambda x: -x[1]):
            print(f"    {n:3d}  {k}")
    print()
    print("克重档位分布:")
    for k, n in sorted(stats["weight_dist"].items(), key=lambda x: -x[1]):
        print(f"  {n:3d}  {k}")
    print()
    print(f"✅ DB 已更新: {DB_PATH}")


if __name__ == "__main__":
    main()
