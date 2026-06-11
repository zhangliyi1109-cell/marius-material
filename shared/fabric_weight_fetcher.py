#!/usr/bin/env python3
"""从 BI D1 数据集批量获取面料克重/成分/门幅，供库存看板使用。"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any


# bi_fabric_info.py 位置
_KNOWLEDGE_DIR = Path.home() / ".openclaw/workspace/1_MARIUS/AI项目/知识库/原始数据"


def _ensure_path():
    if str(_KNOWLEDGE_DIR) not in sys.path:
        sys.path.insert(0, str(_KNOWLEDGE_DIR))


def classify_weight(weight_g: float | None) -> str:
    """将克重数值映射到档位标签。"""
    if weight_g is None:
        return ""
    try:
        w = float(weight_g)
    except (TypeError, ValueError):
        return ""
    if w <= 0:
        return ""
    if w < 150:
        return "超轻(<150g)"
    if w < 250:
        return "轻量(150-250g)"
    if w < 400:
        return "中量(250-400g)"
    if w < 600:
        return "重量(400-600g)"
    return "超重(>600g)"


def fetch_weight_batch(codes: list[str]) -> dict[str, dict[str, Any]]:
    """批量查询面料克重/成分/门幅。

    Args:
        codes: 物料编码列表（去重后的）

    Returns:
        {物料编码: {"weight": float, "width": float, "composition": str, "composition_parsed": list}}
    """
    if not codes:
        return {}

    _ensure_path()
    try:
        from bi_fabric_info import query  # type: ignore
    except ImportError:
        print("[fabric_weight] bi_fabric_info 导入失败，克重数据不可用", file=sys.stderr)
        return {}

    result: dict[str, dict[str, Any]] = {}
    for i, code in enumerate(codes):
        if not code:
            continue
        try:
            items = query(str(code).strip())
        except Exception as exc:
            print(f"[fabric_weight] 查询 {code} 失败: {exc}", file=sys.stderr)
            continue

        if not items:
            continue

        # 取第一条（同一编码可能有多色，克重基本一致）
        it = items[0]
        weight = it.get("weight")
        try:
            weight = float(weight) if weight else None
        except (TypeError, ValueError):
            weight = None

        width = it.get("width")
        try:
            width = float(width) if width else None
        except (TypeError, ValueError):
            width = None

        result[str(code)] = {
            "weight": weight,
            "width": width,
            "composition": it.get("composition", ""),
            "composition_parsed": it.get("composition_parsed", []),
        }

        # 限速：每个请求间隔 1 秒，避免 BI 压力
        if i < len(codes) - 1:
            time.sleep(1)

    return result
