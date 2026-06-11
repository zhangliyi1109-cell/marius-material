#!/usr/bin/env python3
"""批量为纽扣库存清单提取视觉标签。"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

_MODULE_DIR = Path(__file__).resolve().parent
ROOT = _MODULE_DIR
JSON_PATH = ROOT / "纽扣库存清单.json"
IMG_DIR = ROOT / ".button_images"
CACHE_PATH = ROOT / ".button_visual_cache.json"

COLOR_MAP = {
    "100": "白色/米白",
    "101": "黑色",
    "102": "灰色",
    "103": "米色/绿色",
    "124": "藏青",
    "132": "金色",
    "134": "蓝色",
    "149": "黑色",
    "153": "黑色",
    "176": "驼色",
    "179": "深咖",
    "208": "卡其",
    "330": "银色",
    "337": "透明",
    "340": "浅金",
    "342": "亮银",
    "344": "枪色",
    "349": "深咖",
    "351": "古金",
    "358": "亮枪色",
    "365": "哑金",
    "389": "哑银",
    "399": "亮银",
    "511": "哑白",
    "704": "浅金",
    "326": "黄牛角",
    "原色": "原白/贝壳原色",
    "A03": "米白",
}


def url_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def parse_text_tags(item: dict) -> dict:
    name = " ".join(
        str(item.get(k, "") or "")
        for k in ("物料名称", "物料编码", "物料明细编码", "颜色规格", "纽扣类型")
    )
    color_spec = item.get("颜色规格", "") or ""
    color_code = str(item.get("颜色", "") or "")

    tags: dict = {
        "主色描述": "",
        "孔型": "",
        "造型": "",
        "光泽": "",
        "边缘": "",
        "装饰元素": [],
        "风格": [],
        "适用场景": [],
        "关键词": [],
    }

    m = re.search(r"\[([^\]]+)\]([^;]*)", color_spec)
    if m:
        tags["主色描述"] = m.group(2).strip() or COLOR_MAP.get(color_code, color_code)
    elif color_code:
        tags["主色描述"] = COLOR_MAP.get(color_code, color_code)

    if re.search(r"手缝", name) and not tags.get("孔型"):
        tags["孔型"] = "手缝扣"
    if re.search(r"四眼|4眼", name):
        tags["孔型"] = "四眼"
    elif re.search(r"二眼|2眼|两眼", name):
        tags["孔型"] = "二眼"
    elif re.search(r"工字", name):
        tags["孔型"] = "工字"
    elif re.search(r"四合|暗扣|按扣", name):
        tags["孔型"] = "四合/暗扣"
    elif re.search(r"撞钉|铆钉", name):
        tags["孔型"] = "撞钉"
    elif re.search(r"猪鼻|对钩|吊钟|绳扣|胸针|装饰链", name):
        tags["孔型"] = "辅件/非传统扣"
    elif item.get("纽扣类型") in ("工字扣", "四合扣", "撞钉", "暗扣/按扣"):
        tags["孔型"] = item["纽扣类型"]

    if re.search(r"球形|圆球|球扣", name):
        tags["造型"] = "球形/拱形"
    elif re.search(r"平面|扁", name):
        tags["造型"] = "扁平面片"
    elif re.search(r"垫扣", name):
        tags["造型"] = "垫扣/副扣"
    elif re.search(r"猪鼻|D字|对钩|吊钟", name):
        tags["造型"] = "功能辅件"

    if re.search(r"哑光|哑银|哑金|哑白|哑漆|做旧", name):
        tags["光泽"] = "哑光"
    elif re.search(r"亮光|亮银|亮枪|亮面|喷亮|电镀|古金|古银|24K", name):
        tags["光泽"] = "亮光/金属感"
    elif re.search(r"喷漆|渐变", name):
        tags["光泽"] = "喷漆/特殊表面"
    elif item.get("材质") in ("树脂", "塑料", "果实", "牛角", "贝壳"):
        tags["光泽"] = tags["光泽"] or "自然质感"

    if re.search(r"有边|凸边|圈边", name):
        tags["边缘"] = "有边/凸边"
    elif re.search(r"无边|平边", name):
        tags["边缘"] = "平边/无边"

    deco = []
    for kw, label in [
        (r"LOGO|刻字|MARIUS|MS", "品牌刻字"),
        (r"花纹|图案|纹理|塔罗", "花纹/图案"),
        (r"珍珠|锆石", "珍珠/宝石"),
        (r"镂空", "镂空"),
        (r"烧边", "烧边"),
    ]:
        if re.search(kw, name, re.I):
            deco.append(label)
    tags["装饰元素"] = deco

    styles = []
    scenes = []
    btn_type = item.get("纽扣类型", "")
    material = item.get("材质", "")

    if "LOGO" in name or "刻字" in name or "MARIUS" in name.upper():
        styles.append("品牌识别")
    if btn_type in ("牛角扣", "果实扣") or material in ("牛角", "果实"):
        styles.extend(["经典", "自然风"])
        scenes.extend(["外套", "大衣", "针织"])
    if btn_type == "贝壳扣" or material == "贝壳":
        styles.extend(["优雅", "商务"])
        scenes.extend(["衬衫", "西装", "开衫"])
    if "珍珠" in name or material == "珍珠":
        styles.extend(["装饰", "小香风", "复古"])
        scenes.extend(["外套", "小香风套装"])
    if btn_type in ("工字扣", "四合扣", "撞钉"):
        styles.append("功能五金")
        scenes.extend(["牛仔", "工装", "裤装"])
    if re.search(r"胸针|装饰链|对钩|吊钟|绳扣", name):
        styles.append("装饰辅件")
    if not scenes:
        scenes = ["通用"]

    tags["风格"] = list(dict.fromkeys(styles))
    tags["适用场景"] = list(dict.fromkeys(scenes))

    keywords = [
        item.get("纽扣类型", ""),
        item.get("材质", ""),
        tags["主色描述"],
        tags["孔型"],
        tags["造型"],
        tags["光泽"],
        tags["边缘"],
        *tags["装饰元素"],
        *tags["风格"],
        *tags["适用场景"],
    ]
    tags["关键词"] = [k for k in keywords if k and k not in ("", "通用")]
    return tags


def merge_tags(text_tags: dict, vision_tags: dict | None) -> dict:
    if not vision_tags:
        return _normalize_button_tags(text_tags)
    out = dict(text_tags)
    for key in ("主色描述", "孔型", "造型", "光泽", "边缘"):
        if vision_tags.get(key):
            out[key] = vision_tags[key]
    for key in ("装饰元素", "风格", "适用场景", "关键词"):
        merged = list(dict.fromkeys((out.get(key) or []) + (vision_tags.get(key) or [])))
        out[key] = merged
    if vision_tags.get("视觉描述"):
        out["视觉描述"] = vision_tags["视觉描述"]
    return _normalize_button_tags(out)


def _normalize_button_tags(tags: dict) -> dict:
    """将标签标准化到预设词库。"""
    import sys
    from pathlib import Path
    _shared = Path(__file__).resolve().parent.parent / "shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    try:
        from tag_normalizer import load_vocabulary, normalize_tags
        vocab = load_vocabulary("button")
        return normalize_tags(
            vocab, tags,
            single_keys=("孔型", "造型", "光泽", "边缘"),
            list_keys=("装饰元素", "风格", "适用场景"),
        )
    except Exception:
        return tags


def download_images(items: list[dict]) -> dict[str, str]:
    IMG_DIR.mkdir(exist_ok=True)
    mapping: dict[str, str] = {}
    for item in items:
        url = (item.get("主图") or "").strip()
        if not url:
            continue
        key = url_key(url)
        ext = Path(urlparse(url).path).suffix or ".jpg"
        path = IMG_DIR / f"{key}{ext}"
        if not path.exists():
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                path.write_bytes(r.content)
            except Exception as exc:
                print(f"download fail {url}: {exc}", file=sys.stderr)
                continue
        mapping[url] = str(path)
    return mapping


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_tags(items: list[dict], cache: dict) -> list[dict]:
    out = []
    for item in items:
        row = dict(item)
        text_tags = parse_text_tags(item)
        url = (item.get("主图") or "").strip()
        vision = cache.get(url) if url else None
        merged = merge_tags(text_tags, vision)
        if not url and re.search(r"图案", item.get("物料名称", "")):
            merged.setdefault("装饰元素", [])
            if "图案" not in merged["装饰元素"]:
                merged["装饰元素"].append("图案")
            merged.setdefault("风格", []).extend(["装饰", "经典"])
            merged.setdefault("适用场景", []).extend(["外套", "衬衫"])
            merged["视觉描述"] = merged.get("视觉描述") or "合金图案手缝扣（缺主图），金色金属装饰扣。"
            merged["关键词"] = list(
                dict.fromkeys(merged.get("关键词", []) + ["图案", "手缝", "装饰", "经典"])
            )
        row["视觉标签"] = merged
        out.append(row)
    return out


def main() -> None:
    items = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    cache = load_cache()
    download_images(items)
    enriched = apply_tags(items, cache)
    JSON_PATH.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated {JSON_PATH} ({len(enriched)} items, cache {len(cache)} images)")


if __name__ == "__main__":
    main()
