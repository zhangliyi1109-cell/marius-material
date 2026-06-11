#!/usr/bin/env python3
"""标签标准化：将原始标签映射到预设词库，确保所有标签出自统一池子。

用法:
    from tag_normalizer import load_vocabulary, normalize_tags

    vocab = load_vocabulary("button")
    tags = normalize_tags(vocab, raw_tags)
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
VOCAB_PATH = ROOT / "tag_vocabulary.json"


def load_vocabulary(category: str) -> dict:
    """加载指定品类（button/fabric）的预设标签词库。"""
    data = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    return data.get(category, {})


def _try_parse_python_list(value: str) -> str:
    """如果值是 Python 列表字符串如 \"['针织', '提花']\"，提取首元素。"""
    if not isinstance(value, str):
        return value
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        try:
            parsed = ast.literal_eval(v)
            if isinstance(parsed, list) and parsed:
                return str(parsed[0]).strip()
        except (ValueError, SyntaxError):
            pass
    return value


def _normalize_single(value: str, dim_vocab: dict) -> str:
    """标准化单个标签值。

    原则：
    - 空值 → 保留空
    - 在 synonyms 里 → 映射到预设值
    - 在 preset 里 → 保留
    - **不在 preset 也不在 synonyms → 返回空字符串**（被制除的标签丢失，不进预设池）
    """
    if not value:
        return value
    value = str(value).strip()
    # 处理 Python 列表字符串的 bug 数据
    value = _try_parse_python_list(value)
    synonyms = dim_vocab.get("synonyms", {})
    # 先查同义词映射
    if value in synonyms:
        mapped = synonyms[value]
        # mapped 也必须在 preset 里
        if mapped in set(dim_vocab.get("values", [])):
            return mapped
    # 如果已在预设值中，直接返回
    preset = set(dim_vocab.get("values", []))
    if value in preset:
        return value
    # 不在预设中 → 清空（被 Iris 拿掉的标签彻底丢失，不进“候选新增”）
    return ""


def _normalize_list(values: list, dim_vocab: dict) -> list:
    """标准化标签列表（去重+同义词映射+过滤无效）。"""
    if not values:
        return []
    synonyms = dim_vocab.get("synonyms", {})
    preset = set(dim_vocab.get("values", []))
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        if not v:
            continue
        v = str(v).strip()
        # 同义词映射
        mapped = synonyms.get(v, v)
        # 过滤：只在预设中的保留
        if mapped in preset and mapped not in seen:
            seen.add(mapped)
            result.append(mapped)
    return result


def normalize_tags(vocab: dict, tags: dict, single_keys: tuple[str, ...], list_keys: tuple[str, ...]) -> dict:
    """标准化一个标签字典，返回新的标准化字典。

    Args:
        vocab: load_vocabulary() 返回的词库
        tags: 原始标签字典
        single_keys: 单值字段名列表
        list_keys: 多值字段名列表
    """
    out = dict(tags)
    for key in single_keys:
        if key in tags and key in vocab:
            out[key] = _normalize_single(tags[key], vocab[key])
    for key in list_keys:
        if key in tags and key in vocab:
            out[key] = _normalize_list(tags.get(key) or [], vocab[key])
    return out


def get_unknown_tags(vocab: dict, tags: dict, all_keys: tuple[str, ...]) -> dict[str, list[str]]:
    """获取不在预设词库中的标签，用于人工审核后加入词库。"""
    unknowns: dict[str, list[str]] = {}
    for key in all_keys:
        if key not in vocab or key not in tags:
            continue
        dim = vocab[key]
        preset = set(dim.get("values", []))
        synonyms = set(dim.get("synonyms", {}).keys())
        blacklist = preset | synonyms
        value = tags[key]
        if isinstance(value, list):
            missing = [v for v in value if v and v.strip() not in blacklist]
        elif value and str(value).strip() not in blacklist:
            missing = [str(value).strip()]
        else:
            missing = []
        if missing:
            unknowns[key] = missing
    return unknowns


# ──────────────────────────────
# 强制入库标准化（Iris 2026-06-11 要求）
# ──────────────────────────────

_BUTTON_SINGLE = ("孔型", "造型", "光泽", "边缘")
_BUTTON_LIST = ("装饰元素", "风格", "适用场景")

_FABRIC_SINGLE = ("织法组织", "表面质感", "花纹图案", "厚薄感", "色系", "克重档位")
_FABRIC_LIST = ("风格", "适用场景")


def normalize_tags_for_category(category: str, tags: dict) -> dict:
    """按品类强制标准化标签字典，返回新字典。写入 DB 前必须调用。

    若 tag_normalizer 不可用（导入失败）或标签不在词库，
    按降级策略返回原始标签（不打断入库流程）。
    """
    if not tags or not isinstance(tags, dict):
        return tags
    try:
        vocab = load_vocabulary(category)
    except Exception:
        return tags
    if not vocab:
        return tags
    if category == "button":
        return normalize_tags(vocab, tags, single_keys=_BUTTON_SINGLE, list_keys=_BUTTON_LIST)
    elif category == "fabric":
        return normalize_tags(vocab, tags, single_keys=_FABRIC_SINGLE, list_keys=_FABRIC_LIST)
    return tags


def normalize_tags_and_report(category: str, tags: dict) -> tuple[dict, dict[str, list[str]]]:
    """标准化并返回“被丢弃/被替换”的原始标签，用于审计。"""
    normalized = normalize_tags_for_category(category, tags)
    if category == "button":
        dropped = get_unknown_tags(
            load_vocabulary(category), tags,
            all_keys=_BUTTON_SINGLE + _BUTTON_LIST + ("主色描述", "颜色")
        )
    elif category == "fabric":
        dropped = get_unknown_tags(
            load_vocabulary(category), tags,
            all_keys=_FABRIC_SINGLE + _FABRIC_LIST + ("主色描述", "颜色")
        )
    else:
        dropped = {}
    return normalized, dropped
