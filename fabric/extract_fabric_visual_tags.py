#!/usr/bin/env python3
"""面料视觉标签：文本规则 + 与视觉结果合并。"""

from __future__ import annotations

import re

COLOR_MAP = {
    "100": "白色/米白",
    "101": "黑色",
    "102": "灰色",
    "103": "米色/绿色",
    "124": "藏青",
    "132": "金色",
    "134": "蓝色",
    "149": "黑色",
    "176": "驼色",
    "179": "深咖",
    "208": "卡其",
    "330": "银色",
    "337": "透明",
    "340": "浅金",
    "351": "古金",
    "365": "哑金",
    "389": "哑银",
    "511": "哑白",
}


def parse_text_tags(item: dict) -> dict:
    name = " ".join(
        str(item.get(k, "") or "")
        for k in ("物料名称", "物料编码", "物料明细编码", "颜色规格", "物料种类")
    )
    color_spec = item.get("颜色规格", "") or ""
    color_code = str(item.get("颜色", "") or "")
    kind = item.get("物料种类", "") or ""

    tags: dict = {
        "主色描述": "",
        "色系": "",
        "织法组织": "",
        "表面质感": "",
        "花纹图案": "",
        "厚薄感": "",
        "风格": [],
        "适用场景": [],
        "关键词": [],
    }

    m = re.search(r"\[([^\]]+)\]([^;]*)", color_spec)
    if m:
        tags["主色描述"] = m.group(2).strip() or COLOR_MAP.get(color_code, color_code)
    elif color_code:
        tags["主色描述"] = COLOR_MAP.get(color_code, color_code)

    if re.search(r"藏青|深蓝|宝蓝", name):
        tags["色系"] = "冷色"
    elif re.search(r"米|驼|杏|咖|棕|橙|红|粉", name):
        tags["色系"] = "暖色"
    elif re.search(r"黑|白|灰|银", name):
        tags["色系"] = "中性"

    if re.search(r"针织|汗布|罗纹|毛圈|双面", name):
        tags["织法组织"] = "针织"
    elif re.search(r"斜纹|哔叽|华达呢", name):
        tags["织法组织"] = "斜纹"
    elif re.search(r"平纹|府绸|帆布", name):
        tags["织法组织"] = "平纹"
    elif re.search(r"提花|大提花|小提花", name):
        tags["织法组织"] = "提花"
    elif re.search(r"绒|拉绒|摇粒|天鹅绒|法兰绒", name):
        tags["织法组织"] = "绒类"
    elif kind in ("羊毛", "羊绒"):
        tags["织法组织"] = tags["织法组织"] or "梭织/毛纺"

    if re.search(r"哑光|磨毛|拉绒|呢", name):
        tags["表面质感"] = "哑光/绒感"
    elif re.search(r"亮丝|丝光|缎|光", name):
        tags["表面质感"] = "亮面"
    elif re.search(r"麻|肌理|颗粒", name):
        tags["表面质感"] = "肌理感"
    elif kind in ("真丝", "醋酸"):
        tags["表面质感"] = tags["表面质感"] or "光滑/亮面"

    if re.search(r"格|千鸟|棋盘", name):
        tags["花纹图案"] = "格纹"
    elif re.search(r"条|条纹", name):
        tags["花纹图案"] = "条纹"
    elif re.search(r"人字|鱼骨", name):
        tags["花纹图案"] = "人字纹"
    elif re.search(r"花|印花", name):
        tags["花纹图案"] = "花型"
    elif re.search(r"纯色|素色", name) or tags["主色描述"]:
        tags["花纹图案"] = tags["花纹图案"] or "纯色"

    if re.search(r"薄|雪纺|丝", name):
        tags["厚薄感"] = "轻薄"
    elif re.search(r"厚|呢|大衣|双面呢|羊绒", name):
        tags["厚薄感"] = "厚重"
    else:
        tags["厚薄感"] = "中等"

    styles: list[str] = []
    scenes: list[str] = []
    if kind in ("羊毛", "羊绒"):
        styles.extend(["经典", "商务", "保暖"])
        scenes.extend(["大衣", "外套", "西装"])
    elif kind == "真丝":
        styles.extend(["优雅", "轻奢"])
        scenes.extend(["衬衫", "连衣裙", "礼服"])
    elif kind == "棉":
        styles.extend(["休闲", "日常"])
        scenes.extend(["衬衫", "裤装", "外套"])
    elif kind == "亚麻":
        styles.extend(["自然", "休闲", "夏日"])
        scenes.extend(["衬衫", "裤装"])
    elif kind == "醋酸":
        styles.extend(["垂坠", "优雅"])
        scenes.extend(["连衣裙", "衬衫"])
    elif kind == "涤纶":
        styles.extend(["功能性", "易打理"])
        scenes.extend(["外套", "裤装", "运动"])
    if re.search(r"小香|粗花呢|花呢", name):
        styles.append("小香风")
        scenes.append("外套")
    if not scenes:
        scenes = ["通用"]

    tags["风格"] = list(dict.fromkeys(styles))
    tags["适用场景"] = list(dict.fromkeys(scenes))
    tags["关键词"] = [
        k
        for k in [
            kind,
            tags["主色描述"],
            tags["色系"],
            tags["织法组织"],
            tags["表面质感"],
            tags["花纹图案"],
            tags["厚薄感"],
            *tags["风格"],
            *tags["适用场景"],
        ]
        if k
    ]
    return tags


def merge_tags(text_tags: dict, vision_tags: dict | None) -> dict:
    if not vision_tags:
        return _normalize_fabric_tags(text_tags)
    out = dict(text_tags)
    for key in (
        "主色描述",
        "色系",
        "织法组织",
        "表面质感",
        "花纹图案",
        "厚薄感",
    ):
        if vision_tags.get(key):
            out[key] = vision_tags[key]
    for key in ("风格", "适用场景", "关键词"):
        merged = list(dict.fromkeys((out.get(key) or []) + (vision_tags.get(key) or [])))
        out[key] = merged
    if vision_tags.get("视觉描述"):
        out["视觉描述"] = vision_tags["视觉描述"]
    return _normalize_fabric_tags(out)


def _normalize_fabric_tags(tags: dict) -> dict:
    """将标签标准化到预设词库。"""
    import sys
    from pathlib import Path
    _shared = Path(__file__).resolve().parent.parent / "shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    try:
        from tag_normalizer import load_vocabulary, normalize_tags
        vocab = load_vocabulary("fabric")
        return normalize_tags(
            vocab, tags,
            single_keys=("织法组织", "表面质感", "花纹图案", "厚薄感", "色系", "克重档位"),
            list_keys=("风格", "适用场景"),
        )
    except Exception:
        return tags
