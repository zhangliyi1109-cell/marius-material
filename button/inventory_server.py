#!/usr/bin/env python3
"""纽扣实时库存 API：从观远 BI 拉取 + 合并本地视觉标签。"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request, send_from_directory

from tag_pipeline import get_pipeline, get_store

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "inventory_config.json"

bp = Blueprint("button", __name__)

_cache: dict[str, Any] = {"rows": [], "fetched_at": 0, "error": None}
_tag_bootstrapped = False

BUTTON_KINDS = frozenset({"钮扣", "工字扣", "四合扣"})
# 名称命中则视为非纽扣（垫肩、气眼、吊钟等辅料）
_NON_BUTTON_NAME = re.compile(
    r"吊钟|气眼|裤钩|对勾|暗钩|垫肩|马尾衬|衬\+|花边|猪鼻|日字扣|调节扣|弹弓|"
    r"睫毛|米珠|主唛|皮标|金属牌|装饰金属|杠铃|拉链|绳扣|胸针|装饰链|绳|吊牌|"
    r"蕾丝|气眼|介子|B件|羽绒服",
    re.I,
)
_BUTTON_NAME = re.compile(
    r"扣|钮|撞钉|铆钉|按扣|暗扣|四合|工字|牛角|贝壳|果实|树脂",
    re.I,
)


def is_button_row(row: dict) -> bool:
    """仅保留纽扣类：排除辅料_其他及误归类的金属辅件。"""
    kind = (row.get("物料种类") or "").strip()
    if kind == "辅料_其他":
        return False
    name = " ".join(
        str(row.get(k, "") or "")
        for k in ("物料名称", "物料编码", "物料颜色规格名称")
    )
    if kind in BUTTON_KINDS:
        return not _NON_BUTTON_NAME.search(name)
    if kind == "金属部件":
        return bool(_BUTTON_NAME.search(name)) and not _NON_BUTTON_NAME.search(name)
    return False


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_visual_index(cfg: dict) -> dict[str, dict]:
    """SKU 明细编码 → 视觉标签；优先 SQLite，JSON 兜底。"""
    store = get_store(cfg)
    index = store.build_visual_index()
    path = ROOT / cfg.get("visual_tags_json", "seed_inventory.json")
    if path.exists():
        items = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            key = (item.get("物料明细编码") or "").strip()
            if key and key not in index:
                tags = item.get("视觉标签") or {}
                if tags:
                    index[key] = tags
    return index


def bootstrap_tagging(cfg: dict) -> None:
    global _tag_bootstrapped
    if _tag_bootstrapped:
        return
    get_pipeline(cfg)
    _tag_bootstrapped = True


def tag_status_for_row(cfg: dict, detail: str) -> str:
    if not detail:
        return "pending"
    meta = get_store(cfg).get_tag_meta(detail)
    return meta.get("status") or "pending"


def infer_button_type(row: dict) -> str:
    kind = row.get("物料种类") or ""
    name = " ".join(
        str(row.get(k, "") or "")
        for k in ("物料名称", "物料编码", "物料颜色规格名称")
    )
    if kind and kind != "钮扣":
        return kind
    for kw, label in [
        (r"牛角", "牛角扣"),
        (r"贝壳", "贝壳扣"),
        (r"果实|Corozo|corozo", "果实扣"),
        (r"树脂", "树脂扣"),
        (r"工字", "工字扣"),
        (r"四合|急钮|按扣|暗扣", "四合扣"),
        (r"撞钉|铆钉", "撞钉"),
        (r"暗扣", "暗扣/按扣"),
        (r"猪鼻|对钩|吊钟|绳扣|胸针|装饰链", "辅件"),
    ]:
        if re.search(kw, name, re.I):
            return label
    return kind or "钮扣"


def parse_color_spec(spec: str) -> dict[str, str]:
    spec = spec or ""
    m = re.search(r"\[([^\]]+)\]([^;]*)", spec)
    color_code = m.group(1).strip() if m else ""
    color_desc = m.group(2).strip() if m else ""
    size = ""
    if ";" in spec:
        parts = spec.split(";", 1)
        if len(parts) > 1:
            size = parts[1].strip()
    elif re.search(r"\d+L|\d+mm|\d+CM", spec, re.I):
        size = spec
    return {
        "颜色规格": spec,
        "颜色": color_code,
        "颜色描述": color_desc,
        "尺寸": size,
    }


def fetch_bi_rows(cfg: dict) -> list[dict]:
    kinds = ",".join(cfg["material_kinds"])
    cmd = [
        "guancli",
        "ds",
        "preview",
        cfg["dataset_id"],
        "--limit",
        "500",
        "--filter",
        f"可配库存 GT {cfg['min_stock_default']}",
        "--filter",
        f"物料种类 IN {kinds}",
        "--format",
        "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "guancli failed")
    rows = json.loads(proc.stdout)
    if not isinstance(rows, list):
        raise RuntimeError("unexpected guancli response")
    return rows


def normalize_row(row: dict, visual_index: dict[str, dict], cfg: dict) -> dict:
    detail = (row.get("物料明细编码") or "").strip()
    spec = parse_color_spec(row.get("物料颜色规格名称") or "")
    stock = float(row.get("可配库存") or 0)
    visual = visual_index.get(detail, {})
    return {
        "物料种类": row.get("物料种类", ""),
        "纽扣类型": infer_button_type(row),
        "物料名称": row.get("物料名称", ""),
        "物料编码": row.get("物料编码", ""),
        "物料明细编码": detail,
        "颜色规格": spec["颜色规格"],
        "主图": (row.get("主图") or "").strip(),
        "可配库存": stock,
        "实际库存": float(row.get("实际库存") or 0),
        "材质": "",  # BI 无此列，由视觉标签/名称补充
        "颜色": spec["颜色"],
        "颜色描述": spec["颜色描述"],
        "尺寸": spec["尺寸"],
        "仓库名称": row.get("仓库名称", ""),
        "供应商简称": row.get("供应商简称", ""),
        "物料类型": row.get("物料类型", ""),
        "last_update_time": row.get("last_update_time", ""),
        "视觉标签": visual,
        "tag_status": tag_status_for_row(cfg, detail),
    }


def get_merged_rows(force: bool = False) -> tuple[list[dict], dict]:
    cfg = load_config()
    bootstrap_tagging(cfg)
    ttl = cfg.get("cache_seconds", 120)
    now = time.time()
    if not force and _cache["rows"] and now - _cache["fetched_at"] < ttl:
        return _cache["rows"], {"cached": True, "fetched_at": _cache["fetched_at"]}

    visual_path = ROOT / cfg.get("visual_tags_json", "seed_inventory.json")
    visual_index = load_visual_index(cfg)
    try:
        raw = fetch_bi_rows(cfg)
        raw = [r for r in raw if is_button_row(r)]
        rows = [normalize_row(r, visual_index, cfg) for r in raw]
        rows.sort(key=lambda x: x["可配库存"], reverse=True)
        _cache["rows"] = rows
        _cache["fetched_at"] = now
        _cache["error"] = None
        meta = {"cached": False, "fetched_at": now, "source": "bi"}
        if cfg.get("auto_tag_on_fetch", True):
            n = get_pipeline(cfg).enqueue_rows(rows)
            meta["tag_enqueued"] = n
    except Exception as exc:
        if _cache["rows"]:
            meta = {
                "cached": True,
                "fetched_at": _cache["fetched_at"],
                "source": "stale_cache",
                "warning": str(exc),
            }
            return _cache["rows"], meta
        # fallback static json
        items = json.loads(visual_path.read_text(encoding="utf-8"))
        items = [r for r in items if is_button_row(r)]
        rows = sorted(items, key=lambda x: x.get("可配库存", 0), reverse=True)
        _cache["rows"] = rows
        _cache["fetched_at"] = now
        meta = {"cached": False, "fetched_at": now, "source": "static_fallback", "error": str(exc)}
    return _cache["rows"], meta


def group_by_product(rows: list[dict]) -> list[dict]:
    """按物料编码合并同款多尺码 SKU，减少页面视觉重复。"""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = (row.get("物料编码") or row.get("物料名称") or "").strip()
        if not key:
            key = row.get("物料明细编码") or str(id(row))
        groups.setdefault(key, []).append(row)

    merged: list[dict] = []
    for _key, items in groups.items():
        items.sort(key=lambda x: x["可配库存"], reverse=True)
        total_stock = sum(x["可配库存"] for x in items)
        rep = dict(items[0])
        rep["可配库存合计"] = total_stock
        rep["可配库存"] = total_stock
        rep["sku_count"] = len(items)
        rep["variants"] = [
            {
                "物料明细编码": x["物料明细编码"],
                "颜色规格": x["颜色规格"],
                "尺寸": x["尺寸"],
                "可配库存": x["可配库存"],
                "tag_status": x.get("tag_status"),
            }
            for x in items
        ]
        rep["tag_status"] = _aggregate_tag_status(items)
        merged.append(rep)
    merged.sort(key=lambda x: x["可配库存合计"], reverse=True)
    return merged


def _aggregate_tag_status(items: list[dict]) -> str:
    order = {"failed": 0, "pending": 1, "running": 2, "text_only": 3, "done": 4}
    statuses = [i.get("tag_status") or "pending" for i in items]
    if not statuses:
        return "pending"
    return min(statuses, key=lambda s: order.get(s, 1))


def filter_rows(rows: list[dict]) -> list[dict]:
    q = (request.args.get("q") or "").strip().lower()
    min_stock = float(request.args.get("min_stock") or 0)
    btn_type = (request.args.get("type") or "").strip()
    hole = (request.args.get("hole") or "").strip()
    style = (request.args.get("style") or "").strip()

    out = []
    for row in rows:
        if row.get("可配库存", 0) < min_stock:
            continue
        if btn_type and row.get("纽扣类型") != btn_type:
            continue
        tags = row.get("视觉标签") or {}
        if hole and tags.get("孔型") != hole:
            continue
        if style and style not in (tags.get("风格") or []):
            continue
        if q:
            blob = json.dumps(row, ensure_ascii=False).lower()
            if q not in blob:
                continue
        out.append(row)
    return out


@bp.get("/")
def index():
    return send_from_directory(ROOT, "inventory.html")


@bp.get("/api/buttons")
def api_buttons():
    force = request.args.get("refresh") == "1"
    view = (request.args.get("view") or "product").strip()
    rows, meta = get_merged_rows(force=force)
    filtered = filter_rows(rows)
    sku_total = len(filtered)
    if view == "product":
        display = group_by_product(filtered)
    else:
        display = filtered
    return jsonify(
        {
            "items": display,
            "total": len(display),
            "sku_total": sku_total,
            "total_all": len(rows),
            "view": view,
            **meta,
        }
    )


@bp.get("/api/tag-jobs")
def api_tag_jobs():
    cfg = load_config()
    bootstrap_tagging(cfg)
    return jsonify(get_pipeline(cfg).status())


@bp.post("/api/tag-jobs/run")
def api_tag_jobs_run():
    cfg = load_config()
    bootstrap_tagging(cfg)
    rows, _meta = get_merged_rows(force=True)
    n = get_pipeline(cfg).enqueue_all_pending(rows)
    return jsonify({"enqueued": n, **get_pipeline(cfg).status()})


@bp.get("/api/meta")
def api_meta():
    cfg = load_config()
    bootstrap_tagging(cfg)
    rows, meta = get_merged_rows()
    types = sorted({r.get("纽扣类型", "") for r in rows if r.get("纽扣类型")})
    holes = sorted(
        {
            (r.get("视觉标签") or {}).get("孔型", "")
            for r in rows
            if (r.get("视觉标签") or {}).get("孔型")
        }
    )
    styles: set[str] = set()
    for r in rows:
        for s in (r.get("视觉标签") or {}).get("风格") or []:
            styles.add(s)
    tag_status = get_pipeline(cfg).status()
    return jsonify(
        {
            "config": cfg,
            "types": types,
            "holes": holes,
            "styles": sorted(styles),
            "tag_jobs": tag_status,
            **meta,
        }
    )


if __name__ == "__main__":
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix="/button")
    app.run(host="127.0.0.1", port=8765, debug=False)
