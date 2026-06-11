#!/usr/bin/env python3
"""
tag_semantic_rules.py — 标签语义校验规则

预设词库只能约束"可选值范围"，不能约束"值的语义正确性"。
本模块定义**互斥规则**和**物性反推规则**，打标后自动校验。

设计原则：
- 互斥：基于常识（"运动休闲"和"保暖"语义矛盾）
- 物性：基于 BI D1 的物理指标（厚重绒类不适合"运动休闲"）
- 必选：基于场景联动（打"运动休闲"→场景必含"运动"）

修复策略：**违规标签直接移除**（不强行替换为别的）。
"""
from __future__ import annotations

from typing import Iterable

# ============================================================
# 1. 互斥规则
# ============================================================
# 格式：m["风格"] / m["适用场景"] / m["厚薄感"] / m["织法组织"] / m["表面质感"]
# 值列表 A → 不能与 B 同存
MUTEX_RULES: list[tuple[str, list[str], str, list[str]]] = [
    # ("维度", [值A...], "维度", [值B...])

    # 风格 ↔ 厚薄感
    ("风格", ["运动休闲"], "厚薄感", ["厚重", "加厚"]),
    ("风格", ["运动休闲"], "厚薄感", ["轻薄"]),  # 薄透料也不是运动

    # 风格 ↔ 风格
    ("风格", ["运动休闲"], "风格", ["保暖"]),
    ("风格", ["运动休闲"], "风格", ["复古"]),
    ("风格", ["运动休闲"], "风格", ["优雅"]),
    ("风格", ["运动休闲"], "风格", ["小香风"]),
    ("风格", ["运动休闲"], "风格", ["垂坠"]),

    # 风格 ↔ 织法
    ("风格", ["运动休闲"], "织法组织", ["绒类"]),

    # 风格 ↔ 表面
    ("风格", ["运动休闲"], "表面质感", ["绒感"]),

    # 风格 ↔ 厚薄感（其他）
    ("风格", ["保暖"], "厚薄感", ["轻薄"]),
    ("风格", ["夏日"], "厚薄感", ["厚重", "加厚"]),

    # 风格 ↔ 花纹（商务不应有花型）
    ("风格", ["商务"], "花纹图案", ["花型"]),
]


# ============================================================
# 2. 必选规则
# ============================================================
# 面料已无“适用场景”维度，不再需必选规则
REQUIRED_RULES: list[tuple[str, list[str], str, list[str]]] = []


# ============================================================
# 3. 物性反推规则（基于 BI D1 指标）
# ============================================================
# 当 BI D1 给了克重/成分/织法时，强制清除与物性矛盾的标签
# 触发条件：tags 中含触发词 + 物性指标满足条件 → 清除触发词
def check_weight_conflicts(tags: dict, weight_g: float | None) -> list[str]:
    """克重物性反推，返回应移除的风格列表"""
    if weight_g is None or weight_g <= 0:
        return []
    to_remove: list[str] = []
    styles = tags.get("风格", [])
    if not styles:
        return []

    # 重量料（>500g）不适合运动休闲/夏日
    if weight_g > 500:
        for s in ("运动休闲", "夏日"):
            if s in styles:
                to_remove.append(s)
    # 超轻（<100g）不适合保暖/商务
    if weight_g < 100:
        for s in ("保暖", "商务", "厚重"):
            if s in styles:
                to_remove.append(s)

    return to_remove


def check_composition_conflicts(tags: dict, composition: str) -> list[str]:
    """成分反推（如纯羊毛不适合"夏日"）"""
    if not composition:
        return []
    styles = tags.get("风格", [])
    if not styles:
        return []

    to_remove: list[str] = []
    # 100% 羊毛/羊绒 → 厚重保暖 → 删"夏日"
    if "羊毛" in composition and "夏日" in styles and "100%" in composition:
        to_remove.append("夏日")
    return to_remove


# ============================================================
# 4. 主校验函数
# ============================================================
def validate_tags(tags: dict, weight_g: float | None = None, composition: str = "") -> tuple[dict, list[str]]:
    """
    校验并修复 tags。返回 (cleaned_tags, violations)。

    修复策略：违规字段**直接移除**（不强行替换）。
    返回的 violations 列表会进"候选新增"队列，供人工审核。
    """
    cleaned = dict(tags)
    violations: list[str] = []

    # 4.1 互斥规则
    for dim_a, vals_a, dim_b, vals_b in MUTEX_RULES:
        # 检查 dim_a 中是否有 vals_a 的值
        if dim_a == "风格" or dim_a == "适用场景":
            a_present = [v for v in cleaned.get(dim_a, []) if v in vals_a]
        else:
            a_present = [v for v in [cleaned.get(dim_a, "")] if v in vals_a]

        if dim_b == "风格" or dim_b == "适用场景":
            b_present = [v for v in cleaned.get(dim_b, []) if v in vals_b]
        else:
            b_present = [v for v in [cleaned.get(dim_b, "")] if v in vals_b]

        if a_present and b_present:
            # 冲突：移除 dim_a 中的违规值（保留 dim_b，因为 dim_b 通常是更基础的物性）
            if dim_a in ("风格", "适用场景"):
                cleaned[dim_a] = [v for v in cleaned.get(dim_a, []) if v not in a_present]
                for v in a_present:
                    violations.append(f"MUTEX: {dim_a}={v} ↔ {dim_b}={b_present[0]}, 已移除 {v}")
            else:
                # 单值字段：清空
                if cleaned.get(dim_a) in a_present:
                    cleaned[dim_a] = ""
                    violations.append(f"MUTEX: {dim_a}={a_present[0]} ↔ {dim_b}={b_present[0]}, 已清空 {dim_a}")

    # 4.2 必选规则
    for dim_a, vals_a, dim_b, required in REQUIRED_RULES:
        if dim_a == "风格" or dim_a == "适用场景":
            a_present = [v for v in cleaned.get(dim_a, []) if v in vals_a]
        else:
            continue  # 必选规则只针对 风格/适用场景
        if a_present:
            b_present = cleaned.get(dim_b, [])
            if not isinstance(b_present, list):
                b_present = [b_present]
            if not any(req in b_present for req in required):
                # 必含项缺失：移除 dim_a
                cleaned[dim_a] = [v for v in cleaned.get(dim_a, []) if v not in a_present]
                for v in a_present:
                    violations.append(f"REQUIRED: {dim_a}={v} 但 {dim_b} 不含 {required}, 已移除 {v}")

    # 4.3 物性反推
    w_removes = check_weight_conflicts(cleaned, weight_g)
    if w_removes:
        cleaned["风格"] = [v for v in cleaned.get("风格", []) if v not in w_removes]
        for v in w_removes:
            violations.append(f"WEIGHT: 克重{weight_g}g 与 风格={v} 矛盾, 已移除")

    c_removes = check_composition_conflicts(cleaned, composition)
    if c_removes:
        cleaned["风格"] = [v for v in cleaned.get("风格", []) if v not in c_removes]
        for v in c_removes:
            violations.append(f"COMPOSITION: 成分{composition} 与 风格={v} 矛盾, 已移除")

    return cleaned, violations


# ============================================================
# 5. 测试入口
# ============================================================
if __name__ == "__main__":
    # 测试用例
    test_cases = [
        {
            "name": "顺毛呢 175 号（厚重保暖被打成运动休闲）",
            "tags": {
                "织法组织": "绒类", "表面质感": "绒感", "厚薄感": "厚重",
                "花纹图案": "纯色",
                "风格": ["经典", "商务", "保暖", "休闲", "复古", "运动休闲"],
                "适用场景": ["大衣", "外套", "西装"]
            },
            "weight": 680.0,
            "composition": "100% 羊毛"
        },
        {
            "name": "透气运动夹克",
            "tags": {
                "织法组织": "针织", "表面质感": "哑光", "厚薄感": "中等",
                "风格": ["运动休闲", "功能性"],
                "适用场景": ["运动", "外套", "夹克"]
            },
            "weight": 220.0,
            "composition": "100% 涤纶"
        },
    ]
    for tc in test_cases:
        cleaned, violations = validate_tags(tc["tags"], tc["weight"], tc["composition"])
        print(f"\n=== {tc['name']} ===")
        print(f"  原:  风格={tc['tags'].get('风格', [])}")
        print(f"  清后: 风格={cleaned.get('风格', [])}")
        for v in violations:
            print(f"  ⚠️  {v}")
