"""下载物料主图（带重试与常见请求头）。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def download_image(url: str, dest: Path, *, timeout: int = 45, retries: int = 3) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    headers = dict(DEFAULT_HEADERS)
    host = urlparse(url).netloc
    if host:
        headers["Referer"] = f"https://{host}/"

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            content = resp.content
            if len(content) < 128:
                raise RuntimeError(f"图片过小 ({len(content)} bytes)")
            dest.write_bytes(content)
            return dest
        except Exception as exc:
            last_err = exc
            logger.warning("download attempt %s/%s failed %s: %s", attempt, retries, url, exc)
            if attempt < retries:
                time.sleep(min(2 * attempt, 6))
    raise RuntimeError(f"主图下载失败: {last_err}")
