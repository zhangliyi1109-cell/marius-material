#!/usr/bin/env python3
"""小米 Mimo 视觉 API：纽扣主图结构化打标。"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.5"

VISION_PROMPT = """你是服装辅料（纽扣）视觉分析师。根据图片输出 JSON（不要 markdown 代码块），字段如下：
{
  "主色描述": "字符串",
  "孔型": "二眼/四眼/工字/四合/无孔/其他",
  "造型": "扁圆/拱形/脚扣/异形/其他",
  "光泽": "哑光/亮面/珠光/镜面/其他",
  "边缘": "平边/有边/凸边/斜边/其他",
  "装饰元素": ["数组，如品牌刻字、珍珠、水钻、镂空等"],
  "风格": ["数组，如小香风、商务、牛仔、复古等"],
  "适用场景": ["数组，如西装、外套、衬衫、裤装等"],
  "视觉描述": "一两句中文，描述造型与装饰，供设计师筛选",
  "关键词": ["10个以内检索词"]
}
只输出 JSON。"""

FABRIC_VISION_PROMPT = """你是服装面料视觉分析师。根据面料图片输出 JSON（不要 markdown 代码块），字段如下：
{
  "主色描述": "字符串，如藏青、米白、驼色",
  "色系": "冷色/暖色/中性/其他",
  "织法组织": "针织/梭织/斜纹/平纹/提花/绒类/其他",
  "表面质感": "哑光/亮面/绒感/颗粒感/肌理感/光滑/其他",
  "花纹图案": "纯色/格纹/条纹/人字纹/花型/杂色/其他",
  "厚薄感": "轻薄/中等/厚重/不确定",
  "风格": ["数组，如商务、休闲、小香风、复古、户外等"],
  "适用场景": ["数组，如西装、大衣、衬衫、连衣裙、裤装等"],
  "视觉描述": "一两句中文，描述颜色、纹理与整体观感，供设计师选料",
  "关键词": ["10个以内检索词"]
}
只输出 JSON。"""


def _sanitize_api_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    # 误粘贴多次时只取第一段 tp- key（约 50 字符）
    m = re.match(r"^(tp-[a-zA-Z0-9]{20,60})", key)
    if m:
        return m.group(1)
    if len(key) > 80 and key.startswith("tp-"):
        return key[:60]
    return key


def resolve_api_key() -> str | None:
    key = _sanitize_api_key(os.environ.get("XIAOMI_API_KEY", ""))
    if key:
        return key
    oc = Path.home() / ".openclaw" / "openclaw.json"
    if oc.exists():
        try:
            data = json.loads(oc.read_text(encoding="utf-8"))
            env = data.get("env") or {}
            key = env.get("XIAOMI_API_KEY") or (env.get("vars") or {}).get("XIAOMI_API_KEY")
            if key:
                return str(key).strip()
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _image_mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".png",):
        return "image/png"
    if ext in (".webp",):
        return "image/webp"
    return "image/jpeg"


def _parse_json_blob(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model response")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in response: {text[:200]}")
    return json.loads(text[start : end + 1])


def _normalize_fields(
    raw: dict,
    *,
    string_keys: tuple[str, ...],
    list_keys: tuple[str, ...],
) -> dict:
    out: dict = {}
    for key in string_keys:
        v = raw.get(key)
        if v:
            out[key] = str(v).strip()
    for key in list_keys:
        v = raw.get(key)
        if isinstance(v, list):
            out[key] = [str(x).strip() for x in v if str(x).strip()]
        elif v:
            out[key] = [str(v).strip()]
        else:
            out[key] = []
    if not out.get("视觉描述"):
        raise ValueError("missing 视觉描述")
    return out


def normalize_vision(raw: dict) -> dict:
    """纽扣视觉标签。"""
    return _normalize_fields(
        raw,
        string_keys=("主色描述", "孔型", "造型", "光泽", "边缘", "视觉描述"),
        list_keys=("装饰元素", "风格", "适用场景", "关键词"),
    )


def normalize_fabric_vision(raw: dict) -> dict:
    """面料视觉标签。"""
    return _normalize_fields(
        raw,
        string_keys=(
            "主色描述",
            "色系",
            "织法组织",
            "表面质感",
            "花纹图案",
            "厚薄感",
            "视觉描述",
        ),
        list_keys=("风格", "适用场景", "关键词"),
    )


def analyze_image(
    image_path: Path,
    *,
    prompt: str = VISION_PROMPT,
    normalize_fn=normalize_vision,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    timeout: int = 120,
) -> dict:
    api_key = api_key or resolve_api_key()
    if not api_key:
        raise RuntimeError("未配置 XIAOMI_API_KEY（环境变量或 ~/.openclaw/openclaw.json）")

    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    b64 = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    mime = _image_mime(path)
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 1200,
        "temperature": 0.2,
    }
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"xiaomi vision HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("xiaomi vision: empty choices")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        content = "\n".join(parts)
    return normalize_fn(_parse_json_blob(str(content)))


def analyze_fabric_image(image_path: Path, **kwargs) -> dict:
    return analyze_image(
        image_path,
        prompt=FABRIC_VISION_PROMPT,
        normalize_fn=normalize_fabric_vision,
        **kwargs,
    )
