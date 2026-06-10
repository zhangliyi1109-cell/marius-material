#!/usr/bin/env python3
"""面料打标：agent 缓存模式（默认）或 xiaomi / kimi 视觉 API 模式。"""

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

from tag_store import TagStore
from tag_utils import is_quota_error, quota_user_message
from vision_tagger import (
    analyze_fabric_image,
    api_key_env_name,
    resolve_api_key,
    uses_vision_api,
    vision_settings,
)

try:
    from image_fetch import download_image
except ImportError:
    from shared.image_fetch import download_image

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
PROJECT = ROOT.parent
IMG_DIR = ROOT / ".fabric_images"
CACHE_PATH = ROOT / "visual_cache.json"


def _extract_script(name: str) -> Path:
    for path in (PROJECT / "shared" / name, ROOT / name):
        if path.is_file():
            return path
    raise FileNotFoundError(name)


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
        "fabric_extract", _extract_script("extract_fabric_visual_tags.py")
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
        vp = vision_provider(cfg)
        if uses_vision_api(vp):
            vs = vision_settings(vision_cfg)
            self.provider = vs["provider"]
            self.base_url = vs["base_url"]
            self.model = vs["model"]
            self.request_interval = vs["request_interval_sec"]
            self.quota_pause_sec = vs["quota_pause_sec"]
            self.max_enqueue_per_run = vs["max_enqueue_per_run"]
        else:
            self.provider = "agent"
            self.base_url = ""
            self.model = ""
            self.request_interval = 3.0
            self.quota_pause_sec = 600.0
            self.max_enqueue_per_run = 20
        self._queue: queue.Queue[TagJob | None] = queue.Queue()
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_finished_at: float | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_api_at: float = 0.0
        self._quota_pause_until: float = 0.0

    def start(self) -> None:
        if not uses_vision_api(vision_provider(self.cfg)):
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
                "api_configured": (
                    bool(resolve_api_key(self.provider))
                    if uses_vision_api(self.provider)
                    else None
                ),
                "provider": self.provider,
                "model": self.model,
                "agent_cache_urls": len(load_agent_cache()),
                "db_counts": db,
                "quota_paused": time.time() < self._quota_pause_until,
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

    def enqueue_rows(self, rows: list[dict], *, limit: int | None = None) -> int:
        if not uses_vision_api(vision_provider(self.cfg)):
            return apply_agent_cache(self.store, rows)
        cap = limit if limit is not None else self.max_enqueue_per_run
        added = 0
        mod = extract_mod()
        for row in rows:
            if added >= cap:
                break
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
            if meta["status"] == "failed":
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
                    error=None,
                )
                self._queue.put(TagJob(detail_code=detail, row=dict(row)))
                added += 1
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
        added = self.enqueue_rows(rows)
        row_map = {(r.get("物料明细编码") or "").strip(): r for r in rows}
        codes = [
            c for c in self.store.list_details_by_status("pending", "failed")
            if c in row_map
        ]
        if codes:
            added += self.retry_details(rows, codes)
        return added

    def retry_details(self, rows: list[dict], detail_codes: list[str]) -> int:
        codes = {c.strip() for c in detail_codes if c and c.strip()}
        if not codes:
            return 0
        row_map = {(r.get("物料明细编码") or "").strip(): r for r in rows}
        added = 0
        mod = extract_mod()
        for detail in codes:
            row = row_map.get(detail)
            if not row:
                continue
            meta = self.store.get_tag_meta(detail)
            if meta["status"] not in ("failed", "pending"):
                continue
            url = (row.get("主图") or "").strip()
            if not url:
                continue
            item = self._item_from_row(row)
            with self._lock:
                self._seen.discard(detail)
            self.store.save_sku_tags(
                detail,
                mod.parse_text_tags(item),
                image_url=url,
                status="pending",
                has_vision=False,
                error=None,
            )
            self._queue.put(TagJob(detail_code=detail, row=dict(row)))
            added += 1
        return added

    def _download(self, url: str) -> Path | None:
        import hashlib

        IMG_DIR.mkdir(exist_ok=True)
        key = hashlib.md5(url.encode()).hexdigest()[:12]
        ext = Path(urlparse(url).path).suffix or ".jpg"
        path = IMG_DIR / f"{key}{ext}"
        if path.exists() and path.stat().st_size > 128:
            return path
        try:
            download_image(url, path)
            return path
        except Exception as exc:
            logger.warning("download %s: %s", url, exc)
            return None

    def _throttle_api(self) -> None:
        wait = self.request_interval - (time.time() - self._last_api_at)
        if wait > 0:
            time.sleep(wait)

    def _analyze_with_retry(self, path: Path, attempts: int = 3) -> dict:
        last_err: Exception | None = None
        for i in range(attempts):
            try:
                self._throttle_api()
                vision = analyze_fabric_image(
                    path,
                    provider=self.provider,
                    base_url=self.base_url,
                    model=self.model,
                )
                self._last_api_at = time.time()
                return vision
            except Exception as exc:
                last_err = exc
                logger.warning("fabric vision attempt %s/%s failed: %s", i + 1, attempts, exc)
                if i + 1 < attempts:
                    if is_quota_error(str(exc)):
                        time.sleep(90 * (i + 1))
                    else:
                        time.sleep(min(2 * (i + 1), 8))
        raise RuntimeError(str(last_err) if last_err else "视觉打标失败")

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
                if not resolve_api_key(self.provider):
                    raise RuntimeError(
                        f"未配置 {self.provider} API Key，请在 .env 设置 "
                        f"{api_key_env_name(self.provider)} 后重启服务"
                    )
                path = self._download(url)
                if not path:
                    raise RuntimeError("主图下载失败")
                vision = self._analyze_with_retry(path)
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
            if is_quota_error(err):
                err = quota_user_message()
                self._quota_pause_until = time.time() + self.quota_pause_sec
                self.store.save_sku_tags(
                    detail,
                    mod.parse_text_tags(item),
                    image_url=url,
                    status="pending",
                    has_vision=False,
                    error=err,
                )
                with self._lock:
                    self._last_error = err
                    self._seen.discard(detail)
                return
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
            if time.time() < self._quota_pause_until:
                time.sleep(5)
                continue
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
