#!/usr/bin/env python3
"""面料打标：agent 缓存模式（默认）或 xiaomi API 模式。"""

from __future__ import annotations

import importlib.util
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from tag_store import TagStore
from vision_tagger import analyze_fabric_image, resolve_api_key

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
IMG_DIR = ROOT / ".fabric_images"
CACHE_PATH = ROOT / "visual_cache.json"


def vision_provider(cfg: dict) -> str:
    return (cfg.get("vision") or {}).get("provider", "agent").strip().lower()


def load_agent_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def save_agent_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_extract_mod():
    spec = importlib.util.spec_from_file_location(
        "fabric_extract", ROOT / "extract_fabric_visual_tags.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_extract = None


def extract_mod():
    global _extract
    if _extract is None:
        _extract = _load_extract_mod()
    return _extract


@dataclass
class TagJob:
    detail_code: str
    row: dict


class TagPipeline:
    def __init__(self, store: TagStore, cfg: dict) -> None:
        self.store = store
        self.cfg = cfg
        vision_cfg = cfg.get("vision") or {}
        self.base_url = vision_cfg.get("base_url", "https://token-plan-cn.xiaomimimo.com/v1")
        self.model = vision_cfg.get("model", "mimo-v2.5")
        self._queue: queue.Queue[TagJob | None] = queue.Queue()
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_finished_at: float | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if vision_provider(self.cfg) != "xiaomi":
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="fabric-tag-worker", daemon=True
        )
        self._thread.start()

    def status(self) -> dict[str, Any]:
        db = self.store.count_by_status()
        with self._lock:
            active = (
                self._queue.qsize()
                + db.get("pending", 0)
                + db.get("running", 0)
            )
            return {
                "pending": db.get("pending", 0),
                "running": db.get("running", 0),
                "done": db.get("done", 0),
                "failed": db.get("failed", 0),
                "text_only": db.get("text_only", 0),
                "queue_size": self._queue.qsize(),
                "active": active,
                "last_error": self._last_error,
                "last_finished_at": self._last_finished_at,
                "api_configured": bool(resolve_api_key()),
                "provider": vision_provider(self.cfg),
                "agent_cache_urls": len(load_agent_cache()),
                "db_counts": db,
            }

    def _item_from_row(self, row: dict) -> dict:
        return {
            "物料明细编码": row.get("物料明细编码", ""),
            "物料名称": row.get("物料名称", ""),
            "物料编码": row.get("物料编码", ""),
            "颜色规格": row.get("颜色规格", ""),
            "颜色": row.get("颜色", ""),
            "物料种类": row.get("物料种类", ""),
            "主图": row.get("主图", ""),
        }

    def enqueue_rows(self, rows: list[dict]) -> int:
        if vision_provider(self.cfg) != "xiaomi":
            return apply_agent_cache(self.store, rows)
        added = 0
        mod = extract_mod()
        for row in rows:
            detail = (row.get("物料明细编码") or "").strip()
            if not detail:
                continue
            url = (row.get("主图") or "").strip()
            item = self._item_from_row(row)
            meta = self.store.get_tag_meta(detail)
            if meta["status"] == "done" and meta.get("has_vision"):
                continue
            if meta["status"] == "running":
                continue
            if not url:
                self.store.save_sku_tags(
                    detail,
                    mod.merge_tags(mod.parse_text_tags(item), None),
                    image_url="",
                    status="text_only",
                    has_vision=False,
                )
                continue
            if self.store.get_vision(url):
                tags = mod.merge_tags(
                    mod.parse_text_tags(item), self.store.get_vision(url)
                )
                self.store.save_sku_tags(
                    detail, tags, image_url=url, status="done", has_vision=True
                )
                continue
            if not self.store.needs_tagging(detail, url):
                continue
            with self._lock:
                if detail in self._seen:
                    continue
                self._seen.add(detail)
            self.store.save_sku_tags(
                detail,
                mod.parse_text_tags(item),
                image_url=url,
                status="pending",
                has_vision=False,
            )
            self._queue.put(TagJob(detail_code=detail, row=dict(row)))
            added += 1
        return added

    def enqueue_all_pending(self, rows: list[dict]) -> int:
        with self._lock:
            self._seen.clear()
        return self.enqueue_rows(rows)

    def _download(self, url: str) -> Path | None:
        import hashlib

        IMG_DIR.mkdir(exist_ok=True)
        key = hashlib.md5(url.encode()).hexdigest()[:12]
        ext = Path(urlparse(url).path).suffix or ".jpg"
        path = IMG_DIR / f"{key}{ext}"
        if path.exists():
            return path
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
            return path
        except Exception as exc:
            logger.warning("download %s: %s", url, exc)
            return None

    def _process_job(self, job: TagJob) -> None:
        detail = job.detail_code
        row = job.row
        url = (row.get("主图") or "").strip()
        mod = extract_mod()
        item = self._item_from_row(row)
        self.store.save_sku_tags(
            detail,
            mod.parse_text_tags(item),
            image_url=url,
            status="running",
            has_vision=False,
        )
        try:
            vision = self.store.get_vision(url)
            if not vision:
                path = self._download(url)
                if not path:
                    raise RuntimeError("主图下载失败")
                vision = analyze_fabric_image(
                    path, base_url=self.base_url, model=self.model
                )
                self.store.save_vision(url, vision, status="done")
            merged = mod.merge_tags(mod.parse_text_tags(item), vision)
            self.store.save_sku_tags(
                detail, merged, image_url=url, status="done", has_vision=True
            )
            with self._lock:
                self._last_finished_at = time.time()
                self._last_error = None
                self._seen.discard(detail)
        except Exception as exc:
            err = str(exc)[:500]
            logger.exception("fabric tag failed %s", detail)
            self.store.save_sku_tags(
                detail,
                mod.parse_text_tags(item),
                image_url=url,
                status="failed",
                has_vision=False,
                error=err,
            )
            with self._lock:
                self._last_error = err
                self._seen.discard(detail)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:
                break
            try:
                self._process_job(job)
            finally:
                self._queue.task_done()


_pipeline: TagPipeline | None = None
_store: TagStore | None = None


def get_store(cfg: dict) -> TagStore:
    global _store
    if _store is None:
        db = ROOT / cfg.get("tag_db", "fabric_tags.db")
        _store = TagStore(db)
    return _store


def apply_agent_cache(store: TagStore, rows: list[dict]) -> int:
    """从 .fabric_visual_cache.json 同步到 DB，无缓存的标为 pending。"""
    cache = load_agent_cache()
    for url, vision in cache.items():
        if url and isinstance(vision, dict):
            store.save_vision(url.strip(), vision, status="done")
    mod = extract_mod()
    updated = 0
    for row in rows:
        detail = (row.get("物料明细编码") or "").strip()
        if not detail:
            continue
        url = (row.get("主图") or "").strip()
        item = {
            "物料明细编码": detail,
            "物料名称": row.get("物料名称", ""),
            "物料编码": row.get("物料编码", ""),
            "颜色规格": row.get("颜色规格", ""),
            "颜色": row.get("颜色", ""),
            "物料种类": row.get("物料种类", ""),
            "主图": url,
        }
        meta = store.get_tag_meta(detail)
        if meta["status"] == "done" and meta.get("has_vision"):
            continue
        if not url:
            store.save_sku_tags(
                detail,
                mod.merge_tags(mod.parse_text_tags(item), None),
                image_url="",
                status="text_only",
                has_vision=False,
            )
            updated += 1
            continue
        vision = store.get_vision(url)
        if vision:
            tags = mod.merge_tags(mod.parse_text_tags(item), vision)
            store.save_sku_tags(
                detail, tags, image_url=url, status="done", has_vision=True
            )
            updated += 1
        else:
            store.save_sku_tags(
                detail,
                mod.parse_text_tags(item),
                image_url=url,
                status="pending",
                has_vision=False,
            )
    return updated


def get_pipeline(cfg: dict) -> TagPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = TagPipeline(get_store(cfg), cfg)
        _pipeline.start()
    return _pipeline
