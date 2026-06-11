#!/usr/bin/env python3
"""纽扣视觉标签 SQLite 存储 + 旧缓存迁移。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent


class TagStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS image_vision (
                image_url TEXT PRIMARY KEY,
                vision_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'done',
                error TEXT,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sku_tags (
                detail_code TEXT PRIMARY KEY,
                image_url TEXT,
                tags_json TEXT NOT NULL,
                status TEXT NOT NULL,
                has_vision INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                updated_at REAL NOT NULL
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def import_legacy_if_empty(self, root: Path, category: str = "button") -> dict[str, int]:
        """从旧缓存与 JSON 迁移，入库前强制标准化。"""
        with self._lock:
            return self._import_legacy_if_empty(root, category)

    def _import_legacy_if_empty(self, root: Path, category: str = "button") -> dict[str, int]:
        stats = {"images": 0, "skus": 0}
        img_n = self._conn.execute("SELECT COUNT(*) FROM image_vision").fetchone()[0]
        sku_n = self._conn.execute("SELECT COUNT(*) FROM sku_tags").fetchone()[0]
        now = time.time()

        cache_path = root / "visual_cache.json"
        cache: dict[str, dict] = {}
        if cache_path.exists():
            cache = json.loads(cache_path.read_text(encoding="utf-8"))

        if img_n == 0 and cache:
            for url, vision in cache.items():
                if not url or not isinstance(vision, dict):
                    continue
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO image_vision
                    (image_url, vision_json, status, error, updated_at)
                    VALUES (?, ?, 'done', NULL, ?)
                    """,
                    (url.strip(), json.dumps(vision, ensure_ascii=False), now),
                )
                stats["images"] += 1

        # ── 强制标准化：2026-06-11 Iris 要求 ──
        try:
            from tag_normalizer import normalize_tags_for_category
        except ImportError:
            from shared.tag_normalizer import normalize_tags_for_category
        # ─────────────────────────────────────

        json_path = root / "seed_inventory.json"
        if sku_n == 0 and json_path.exists():
            items = json.loads(json_path.read_text(encoding="utf-8"))
            for item in items:
                detail = (item.get("物料明细编码") or "").strip()
                tags = item.get("视觉标签")
                if not detail or not isinstance(tags, dict) or not tags:
                    continue
                # 强制标准化入库
                tags = normalize_tags_for_category(category, tags)
                url = (item.get("主图") or "").strip()
                has_v = 1 if url and url in cache else int(bool(tags.get("视觉描述")))
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO sku_tags
                    (detail_code, image_url, tags_json, status, has_vision, error, updated_at)
                    VALUES (?, ?, ?, 'done', ?, NULL, ?)
                    """,
                    (
                        detail,
                        url or None,
                        json.dumps(tags, ensure_ascii=False),
                        has_v,
                        now,
                    ),
                )
                stats["skus"] += 1
        self._conn.commit()
        return stats

    def get_vision(self, image_url: str) -> dict | None:
        with self._lock:
            if not image_url:
                return None
            row = self._conn.execute(
                "SELECT vision_json, status FROM image_vision WHERE image_url = ?",
                (image_url.strip(),),
            ).fetchone()
            if not row or row["status"] != "done":
                return None
            return json.loads(row["vision_json"])

    def save_vision(self, image_url: str, vision: dict, *, status: str = "done", error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO image_vision (image_url, vision_json, status, error, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(image_url) DO UPDATE SET
                  vision_json=excluded.vision_json,
                  status=excluded.status,
                  error=excluded.error,
                  updated_at=excluded.updated_at
                """,
                (
                    image_url.strip(),
                    json.dumps(vision, ensure_ascii=False),
                    status,
                    error,
                    time.time(),
                ),
            )
            self._conn.commit()

    def get_sku_tags(self, detail_code: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT tags_json, status, has_vision FROM sku_tags WHERE detail_code = ?",
                (detail_code.strip(),),
            ).fetchone()
            if not row:
                return None
            tags = json.loads(row["tags_json"])
            tags["_tag_status"] = row["status"]
            tags["_has_vision"] = bool(row["has_vision"])
            return tags

    def get_tags_for_detail(self, detail_code: str) -> dict:
        tags = self.get_sku_tags(detail_code)
        if not tags:
            return {}
        return {k: v for k, v in tags.items() if not k.startswith("_")}

    def get_tag_meta(self, detail_code: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT status, has_vision, error FROM sku_tags WHERE detail_code = ?",
                (detail_code.strip(),),
            ).fetchone()
            if not row:
                return {"status": "pending", "has_vision": False}
            return {
                "status": row["status"],
                "has_vision": bool(row["has_vision"]),
                "error": row["error"],
            }

    def save_sku_tags(
        self,
        detail_code: str,
        tags: dict,
        *,
        image_url: str = "",
        status: str = "done",
        has_vision: bool = False,
        error: str | None = None,
    ) -> None:
        clean = {k: v for k, v in tags.items() if not k.startswith("_")}
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sku_tags
                (detail_code, image_url, tags_json, status, has_vision, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(detail_code) DO UPDATE SET
                  image_url=excluded.image_url,
                  tags_json=excluded.tags_json,
                  status=excluded.status,
                  has_vision=excluded.has_vision,
                  error=excluded.error,
                  updated_at=excluded.updated_at
                """,
                (
                    detail_code.strip(),
                    (image_url or "").strip() or None,
                    json.dumps(clean, ensure_ascii=False),
                    status,
                    1 if has_vision else 0,
                    error,
                    time.time(),
                ),
            )
            self._conn.commit()

    def build_visual_index(self) -> dict[str, dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT detail_code, tags_json FROM sku_tags WHERE status IN ('done', 'text_only')"
            ).fetchall()
            index: dict[str, dict] = {}
            for row in rows:
                tags = json.loads(row["tags_json"])
                index[row["detail_code"]] = tags
            return index

    def count_by_status(self) -> dict[str, int]:
        with self._lock:
            out: dict[str, int] = {}
            for status, cnt in self._conn.execute(
                "SELECT status, COUNT(*) FROM sku_tags GROUP BY status"
            ):
                out[status] = cnt
            return out

    def list_details_by_status(self, *statuses: str) -> list[str]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT detail_code FROM sku_tags WHERE status IN ({placeholders})",
                statuses,
            ).fetchall()
            return [r["detail_code"] for r in rows]

    def needs_tagging(self, detail_code: str, image_url: str) -> bool:
        meta = self.get_tag_meta(detail_code)
        if meta["status"] == "text_only":
            return False
        if meta["status"] == "failed":
            return bool(image_url)
        if meta["status"] == "done" and meta.get("has_vision"):
            return False
        if not image_url:
            return meta["status"] not in ("done", "text_only")
        return meta["status"] != "done" or not meta.get("has_vision")
