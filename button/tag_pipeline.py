#!/usr/bin/env python3
"""纽扣自动打标队列 + 内嵌 Worker（小米视觉 + 文本合并）。"""

from __future__ import annotations

import importlib.util
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from tag_store import TagStore
from vision_tagger import analyze_image, resolve_api_key

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
PROJECT = ROOT.parent
IMG_DIR = ROOT / ".button_images"


def _extract_script(name: str) -> Path:
    for path in (PROJECT / "shared" / name, ROOT / name):
        if path.is_file():
            return path
    raise FileNotFoundError(name)


def _load_extract_mod():
    spec = importlib.util.spec_from_file_location(
        "extract", _extract_script("extract_button_visual_tags.py")
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


@dataclass
class WorkerStats:
    pending: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0
    last_error: str | None = None
    last_finished_at: float | None = None
    queue_size: int = 0


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
        self._stats = WorkerStats()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="button-tag-worker", daemon=True)
        self._thread.start()
        logger.info("tag worker started")

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)

    def status(self) -> dict[str, Any]:
        db = self.store.count_by_status()
        with self._lock:
            s = self._stats
            active = (
                self._queue.qsize()
                + s.running
                + db.get("pending", 0)
                + db.get("running", 0)
            )
            return {
                "pending": db.get("pending", 0),
                "running": s.running + db.get("running", 0),
                "done": db.get("done", 0),
                "failed": db.get("failed", 0),
                "text_only": db.get("text_only", 0),
                "queue_size": self._queue.qsize(),
                "active": active,
                "last_error": s.last_error,
                "last_finished_at": s.last_finished_at,
                "api_configured": bool(resolve_api_key()),
                "db_counts": db,
            }

    def enqueue_rows(self, rows: list[dict]) -> int:
        """将需要打标的 SKU 入队，返回入队数量。"""
        added = 0
        mod = extract_mod()
        for row in rows:
            detail = (row.get("物料明细编码") or "").strip()
            if not detail:
                continue
            url = (row.get("主图") or "").strip()
            item_for_check = {
                "物料明细编码": detail,
                "物料名称": row.get("物料名称", ""),
                "物料编码": row.get("物料编码", ""),
                "颜色规格": row.get("颜色规格", ""),
                "纽扣类型": row.get("纽扣类型", ""),
                "主图": url,
            }
            meta = self.store.get_tag_meta(detail)
            if meta["status"] == "done" and meta.get("has_vision"):
                continue
            if meta["status"] == "running":
                continue
            if not url:
                tags = mod.parse_text_tags(item_for_check)
                self._apply_no_image(detail, item_for_check, tags)
                continue
            if self.store.get_vision(url):
                tags = self._merge_for_row(item_for_check, url)
                self.store.save_sku_tags(
                    detail, tags, image_url=url, status="done", has_vision=True
                )
                with self._lock:
                    self._stats.done += 1
                continue
            if not self.store.needs_tagging(detail, url):
                continue
            with self._lock:
                if detail in self._seen:
                    continue
                self._seen.add(detail)
            self.store.save_sku_tags(
                detail,
                mod.parse_text_tags(item_for_check),
                image_url=url,
                status="pending",
                has_vision=False,
            )
            self._queue.put(TagJob(detail_code=detail, row=dict(row)))
            with self._lock:
                self._stats.pending += 1
            added += 1
        return added

    def enqueue_all_pending(self, rows: list[dict]) -> int:
        with self._lock:
            self._seen.clear()
        return self.enqueue_rows(rows)

    def _apply_no_image(self, detail: str, item: dict, tags: dict) -> None:
        mod = extract_mod()
        merged = mod.merge_tags(tags, None)
        self.store.save_sku_tags(
            detail,
            merged,
            image_url="",
            status="text_only",
            has_vision=False,
        )

    def _merge_for_row(self, item: dict, image_url: str) -> dict:
        mod = extract_mod()
        text_tags = mod.parse_text_tags(item)
        vision = self.store.get_vision(image_url)
        return mod.merge_tags(text_tags, vision)

    def _url_key(self, url: str) -> str:
        import hashlib

        return hashlib.md5(url.encode()).hexdigest()[:12]

    def _download(self, url: str) -> Path | None:
        IMG_DIR.mkdir(exist_ok=True)
        key = self._url_key(url)
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
        item = {
            "物料明细编码": detail,
            "物料名称": row.get("物料名称", ""),
            "物料编码": row.get("物料编码", ""),
            "颜色规格": row.get("颜色规格", ""),
            "纽扣类型": row.get("纽扣类型", ""),
            "主图": url,
        }
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
                vision = analyze_image(
                    path,
                    base_url=self.base_url,
                    model=self.model,
                )
                self.store.save_vision(url, vision, status="done")
            merged = mod.merge_tags(mod.parse_text_tags(item), vision)
            self.store.save_sku_tags(
                detail, merged, image_url=url, status="done", has_vision=True
            )
            with self._lock:
                self._stats.pending = max(0, self._stats.pending - 1)
                self._stats.done += 1
                self._stats.last_finished_at = time.time()
                self._stats.last_error = None
                self._seen.discard(detail)
        except Exception as exc:
            logger.exception("tag failed %s", detail)
            err = str(exc)[:500]
            tags = mod.parse_text_tags(item)
            self.store.save_sku_tags(
                detail,
                tags,
                image_url=url,
                status="failed",
                has_vision=False,
                error=err,
            )
            with self._lock:
                self._stats.pending = max(0, self._stats.pending - 1)
                self._stats.failed += 1
                self._stats.last_error = err
                self._seen.discard(detail)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:
                break
            with self._lock:
                self._stats.running = 1
            try:
                self._process_job(job)
            finally:
                with self._lock:
                    self._stats.running = 0
                self._queue.task_done()


_pipeline: TagPipeline | None = None
_store: TagStore | None = None


def get_store(cfg: dict) -> TagStore:
    global _store
    if _store is None:
        db = ROOT / cfg.get("tag_db", "button_tags.db")
        _store = TagStore(db)
        _store.import_legacy_if_empty(ROOT)
    return _store


def get_pipeline(cfg: dict) -> TagPipeline:
    global _pipeline
    if _pipeline is None:
        store = get_store(cfg)
        _pipeline = TagPipeline(store, cfg)
        _pipeline.start()
    return _pipeline
