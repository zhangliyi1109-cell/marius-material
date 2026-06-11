#!/usr/bin/env python3
"""面料实时库存 API：观远 BI 拉取 + 自动视觉打标。"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request, send_from_directory

from tag_pipeline import apply_agent_cache, get_pipeline, get_store

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "inventory_config.json"

bp = Blueprint("fabric", __name__)
_cache: dict[str, Any] = {"rows": [], "fetched_at": 0, "error": None}
_tag_bootstrapped = False


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def bootstrap_tagging(cfg: dict) -> None:
    global _tag_bootstrapped
    if _tag_bootstrapped:
        return
    get_pipeline(cfg)
    _tag_bootstrapped = True


def is_fabric_row(row: dict, category: str) -> bool:
    if (row.get("物料大类名称") or "").strip() != category:
        return False
    unit = (row.get("单位") or "").strip().lower()
    if unit and unit not in ("m", "米", "码"):
        return False
    return True


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
    return {
        "颜色规格": spec,
        "颜色": color_code,
        "颜色描述": color_desc,
        "门幅/规格": size,
    }


def load_visual_index(cfg: dict) -> dict[str, dict]:
    return get_store(cfg).build_visual_index()


def tag_status_for_row(cfg: dict, detail: str) -> str:
    if not detail:
        return "pending"
    return get_store(cfg).get_tag_meta(detail).get("status") or "pending"


def tag_fields_for_row(cfg: dict, detail: str) -> dict[str, str]:
    if not detail:
        return {"tag_status": "pending", "tag_error": ""}
    meta = get_store(cfg).get_tag_meta(detail)
    return {
        "tag_status": meta.get("status") or "pending",
        "tag_error": (meta.get("error") or "").strip(),
    }


def tag_fail_info(items: list[dict]) -> tuple[str, list[str]]:
    failed = [x for x in items if x.get("tag_status") == "failed"]
    if not failed:
        return "", []
    errors = [(x.get("tag_error") or "").strip() for x in failed if (x.get("tag_error") or "").strip()]
    err = errors[0] if errors else "打标失败，原因未知"
    codes = [(x.get("物料明细编码") or "").strip() for x in failed]
    return err, [c for c in codes if c]


def fetch_bi_rows(cfg: dict) -> list[dict]:
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
        f"物料大类名称 EQ {cfg['material_category']}",
        "--format",
        "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "guancli failed")
    rows = json.loads(proc.stdout)
    if not isinstance(rows, list):
        raise RuntimeError("unexpected guancli response")
    category = cfg.get("material_category", "面料")
    return [r for r in rows if is_fabric_row(r, category)]


def normalize_row(row: dict, visual_index: dict[str, dict], cfg: dict) -> dict:
    detail = (row.get("物料明细编码") or "").strip()
    spec = parse_color_spec(row.get("物料颜色规格名称") or "")
    stock = float(row.get("可配库存") or 0)
    unit = (row.get("单位") or "m").strip()
    return {
        "物料种类": row.get("物料种类", ""),
        "物料名称": row.get("物料名称", ""),
        "物料编码": row.get("物料编码", ""),
        "物料明细编码": detail,
        "颜色规格": spec["颜色规格"],
        "颜色": spec["颜色"],
        "颜色描述": spec["颜色描述"],
        "门幅/规格": spec["门幅/规格"],
        "主图": (row.get("主图") or "").strip(),
        "可配库存": stock,
        "实际库存": float(row.get("实际库存") or 0),
        "单位": unit,
        "仓库名称": row.get("仓库名称", ""),
        "供应商简称": row.get("供应商简称", ""),
        "物料类型": row.get("物料类型", ""),
        "物料大类名称": row.get("物料大类名称", ""),
        "年份名称": row.get("年份名称", ""),
        "last_update_time": row.get("last_update_time", ""),
        "视觉标签": visual_index.get(detail, {}),
        **tag_fields_for_row(cfg, detail),
    }


def _fabric_rows_for_cache(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        spec = parse_color_spec(r.get("物料颜色规格名称") or "")
        rows.append(
            {
                "物料明细编码": (r.get("物料明细编码") or "").strip(),
                "物料名称": r.get("物料名称", ""),
                "物料编码": r.get("物料编码", ""),
                "颜色规格": spec["颜色规格"],
                "颜色": spec["颜色"],
                "物料种类": r.get("物料种类", ""),
                "主图": (r.get("主图") or "").strip(),
            }
        )
    return rows


def get_rows(force: bool = False) -> tuple[list[dict], dict]:
    cfg = load_config()
    bootstrap_tagging(cfg)
    ttl = cfg.get("cache_seconds", 120)
    now = time.time()
    if not force and _cache["rows"] and now - _cache["fetched_at"] < ttl:
        return _cache["rows"], {"cached": True, "fetched_at": _cache["fetched_at"]}

    try:
        raw = fetch_bi_rows(cfg)
        apply_agent_cache(get_store(cfg), _fabric_rows_for_cache(raw))
        visual_index = load_visual_index(cfg)
        rows = [normalize_row(r, visual_index, cfg) for r in raw]
        rows.sort(key=lambda x: x["可配库存"], reverse=True)
        _cache["rows"] = rows
        _cache["fetched_at"] = now
        meta: dict[str, Any] = {"cached": False, "fetched_at": now, "source": "bi"}
        if cfg.get("auto_tag_on_fetch", True):
            per_fetch = int((cfg.get("vision") or {}).get("max_enqueue_per_fetch", 10))
            meta["tag_enqueued"] = get_pipeline(cfg).enqueue_rows(rows, limit=per_fetch)
        return _cache["rows"], meta
    except Exception as exc:
        if _cache["rows"]:
            return _cache["rows"], {
                "cached": True,
                "fetched_at": _cache["fetched_at"],
                "source": "stale_cache",
                "warning": str(exc),
            }
        raise


def apply_visual_tags(rows: list[dict], cfg: dict) -> None:
    visual_index = load_visual_index(cfg)
    for row in rows:
        detail = row.get("物料明细编码", "")
        row["视觉标签"] = visual_index.get(detail, {})
        row.update(tag_fields_for_row(cfg, detail))


def _aggregate_tag_status(items: list[dict]) -> str:
    order = {"failed": 0, "pending": 1, "running": 2, "text_only": 3, "done": 4}
    statuses = [i.get("tag_status") or "pending" for i in items]
    return min(statuses, key=lambda s: order.get(s, 1)) if statuses else "pending"


def group_by_product(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = (row.get("物料编码") or row.get("物料名称") or "").strip()
        if not key:
            key = row.get("物料明细编码") or str(id(row))
        groups.setdefault(key, []).append(row)

    merged: list[dict] = []
    for _key, items in groups.items():
        items.sort(key=lambda x: x["可配库存"], reverse=True)
        total = sum(x["可配库存"] for x in items)
        rep = dict(items[0])
        rep["可配库存合计"] = total
        rep["可配库存"] = total
        rep["sku_count"] = len(items)
        rep["tag_status"] = _aggregate_tag_status(items)
        rep["variants"] = [
            {
                "物料明细编码": x["物料明细编码"],
                "颜色规格": x["颜色规格"],
                "颜色描述": x["颜色描述"],
                "门幅/规格": x["门幅/规格"],
                "可配库存": x["可配库存"],
                "单位": x.get("单位", "m"),
                "tag_status": x.get("tag_status"),
                "tag_error": x.get("tag_error"),
            }
            for x in items
        ]
        err, codes = tag_fail_info(items)
        rep["tag_error"] = err
        rep["retry_detail_codes"] = codes
        merged.append(rep)
    merged.sort(key=lambda x: x["可配库存合计"], reverse=True)
    return merged


def filter_rows(rows: list[dict]) -> list[dict]:
    q = (request.args.get("q") or "").strip().lower()
    min_stock = float(request.args.get("min_stock") or 0)
    kind = (request.args.get("kind") or "").strip()
    warehouse = (request.args.get("warehouse") or "").strip()
    pattern = (request.args.get("pattern") or "").strip()
    weave = (request.args.get("weave") or "").strip()

    out = []
    for row in rows:
        if row.get("可配库存", 0) < min_stock:
            continue
        if kind and row.get("物料种类") != kind:
            continue
        if warehouse and warehouse not in (row.get("仓库名称") or ""):
            continue
        tags = row.get("视觉标签") or {}
        if pattern and tags.get("花纹图案") != pattern:
            continue
        if weave and tags.get("织法组织") != weave:
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


@bp.get("/api/fabrics")
def api_fabrics():
    force = request.args.get("refresh") == "1"
    view = (request.args.get("view") or "product").strip()
    cfg = load_config()
    rows, meta = get_rows(force=force)
    apply_visual_tags(rows, cfg)
    filtered = filter_rows(rows)
    sku_total = len(filtered)
    display = group_by_product(filtered) if view == "product" else filtered
    return jsonify(
        {
            "items": display,
            "total": len(display),
            "sku_total": sku_total,
            "total_all": len(rows),
            "view": view,
            "unit": load_config().get("stock_unit", "m"),
            "tag_jobs": get_pipeline(load_config()).status(),
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
    try:
        rows, _ = get_rows(force=True)
    except Exception as exc:
        return jsonify({"error": f"拉取 BI 失败: {exc}", "enqueued": 0}), 500
    pipe = get_pipeline(cfg)
    n = pipe.enqueue_all_pending(rows)
    status = pipe.status()
    return jsonify({
        "enqueued": n,
        "message": f"已入队 {n} 个 SKU" if n else "没有待打标 SKU（可能已全部完成）",
        **status,
    })


@bp.post("/api/tag-jobs/retry")
def api_tag_jobs_retry():
    cfg = load_config()
    bootstrap_tagging(cfg)
    body = request.get_json(silent=True) or {}
    codes = body.get("detail_codes") or []
    if body.get("detail_code"):
        codes = [body["detail_code"], *codes]
    codes = [str(c).strip() for c in codes if str(c).strip()]
    if not codes:
        return jsonify({"error": "缺少 detail_code 或 detail_codes"}), 400
    rows, _ = get_rows(force=True)
    n = get_pipeline(cfg).retry_details(rows, codes)
    return jsonify({"retried": n, **get_pipeline(cfg).status()})


@bp.get("/api/meta")
def api_meta():
    cfg = load_config()
    bootstrap_tagging(cfg)
    rows, meta = get_rows()
    kinds = sorted({r.get("物料种类", "") for r in rows if r.get("物料种类")})
    warehouses = sorted({r.get("仓库名称", "") for r in rows if r.get("仓库名称")})
    patterns: set[str] = set()
    weaves: set[str] = set()
    for r in rows:
        t = r.get("视觉标签") or {}
        if t.get("花纹图案"):
            patterns.add(t["花纹图案"])
        if t.get("织法组织"):
            weaves.add(t["织法组织"])
    return jsonify(
        {
            "config": cfg,
            "kinds": kinds,
            "warehouses": warehouses,
            "patterns": sorted(patterns),
            "weaves": sorted(weaves),
            "unit": cfg.get("stock_unit", "m"),
            "tag_jobs": get_pipeline(cfg).status(),
            **meta,
        }
    )


if __name__ == "__main__":
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix="/fabric")
    app.run(host="127.0.0.1", port=8766, debug=False)
