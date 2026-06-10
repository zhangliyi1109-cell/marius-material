#!/usr/bin/env python3
"""视觉打标：支持 xiaomi / kimi，OpenAI 兼容 chat/completions + 图片 base64。"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import requests

API_PROVIDERS = frozenset({"xiaomi", "kimi"})

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "xiaomi": {
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "model": "mimo-v2.5",
        "api_key_env": "XIAOMI_API_KEY",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k2.6",
        "api_key_env": "KIMI_API_KEY",
    },
}

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


def normalize_provider(provider: str | None) -> str:
    p = (provider or "xiaomi").strip().lower()
    return p if p in API_PROVIDERS else "xiaomi"


def uses_vision_api(provider: str | None) -> bool:
    return (provider or "").strip().lower() in API_PROVIDERS


def vision_settings(vision_cfg: dict | None) -> dict[str, Any]:
    cfg = vision_cfg or {}
    provider = normalize_provider(cfg.get("provider"))
    preset = PROVIDER_PRESETS[provider]
    return {
        "provider": provider,
        "base_url": (cfg.get("base_url") or preset["base_url"]).rstrip("/"),
        "model": cfg.get("model") or preset["model"],
        "request_interval_sec": float(cfg.get("request_interval_sec", 3)),
        "max_enqueue_per_run": int(cfg.get("max_enqueue_per_run", 20)),
        "max_enqueue_per_fetch": int(cfg.get("max_enqueue_per_fetch", 10)),
        "quota_pause_sec": float(cfg.get("quota_pause_sec", 600)),
    }


def _openclaw_env() -> dict[str, Any]:
    oc = Path.home() / ".openclaw" / "openclaw.json"
    if not oc.exists():
        return {}
    try:
        data = json.loads(oc.read_text(encoding="utf-8"))
        env = data.get("env") or {}
        if isinstance(env.get("vars"), dict):
            return {**env, **env["vars"]}
        return env
    except (json.JSONDecodeError, OSError):
        return {}


def _sanitize_xiaomi_key(key: str) -> str:
    key = (key or "").strip()
    if not key or not key.startswith("tp-"):
        return key
    body = key[3:]
    dup = body.find("tp-")
    if dup > 0:
        body = body[:dup]
    if len(body) >= 48:
        return "tp-" + body[:48]
    return "tp-" + body


def resolve_api_key(provider: str | None = None) -> str | None:
    """按 provider 解析 API Key；未传 provider 时兼容旧逻辑（优先小米）。"""
    p = normalize_provider(provider) if provider else None
    oc = _openclaw_env()

    def from_env(names: tuple[str, ...], *, sanitize=None) -> str | None:
        for name in names:
            val = (os.environ.get(name) or oc.get(name) or "").strip()
            if not val:
                continue
            return sanitize(val) if sanitize else val
        return None

    if p == "kimi":
        return from_env(("KIMI_API_KEY", "MOONSHOT_API_KEY"))
    if p == "xiaomi":
        return from_env(("XIAOMI_API_KEY",), sanitize=_sanitize_xiaomi_key)

    # 兼容：未指定 provider
    return from_env(("XIAOMI_API_KEY",), sanitize=_sanitize_xiaomi_key) or from_env(
        ("KIMI_API_KEY", "MOONSHOT_API_KEY")
    )


def api_key_env_name(provider: str) -> str:
    return PROVIDER_PRESETS[normalize_provider(provider)]["api_key_env"]


def _image_mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".png",):
        return "image/png"
    if ext in (".webp",):
        return "image/webp"
    if ext in (".gif",):
        return "image/gif"
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
    return _normalize_fields(
        raw,
        string_keys=("主色描述", "孔型", "造型", "光泽", "边缘", "视觉描述"),
        list_keys=("装饰元素", "风格", "适用场景", "关键词"),
    )


def normalize_fabric_vision(raw: dict) -> dict:
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


def _extract_message_content(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("vision: empty choices")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
        content = "\n".join(parts)
    return str(content)


def analyze_image(
    image_path: Path,
    *,
    prompt: str = VISION_PROMPT,
    normalize_fn=normalize_vision,
    provider: str = "xiaomi",
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int = 120,
) -> dict:
    settings = vision_settings({"provider": provider, "base_url": base_url, "model": model})
    provider = settings["provider"]
    api_key = api_key or resolve_api_key(provider)
    if not api_key:
        env_name = api_key_env_name(provider)
        raise RuntimeError(
            f"未配置 {provider} API Key（环境变量 {env_name} 或 ~/.openclaw/openclaw.json）"
        )

    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    b64 = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    mime = _image_mime(path)
    image_part = {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"},
    }
    text_part = {"type": "text", "text": prompt}
    # Kimi 文档示例：图在前；小米无严格要求，统一图在前
    content = [image_part, text_part]

    url = settings["base_url"] + "/chat/completions"
    payload = {
        "model": settings["model"],
        "messages": [{"role": "user", "content": content}],
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
    if resp.status_code == 429:
        raise RuntimeError(
            f"{provider} vision HTTP 429: quota exhausted（配额已用尽，请稍后再试）"
        )
    if resp.status_code != 200:
        raise RuntimeError(f"{provider} vision HTTP {resp.status_code}: {resp.text[:500]}")
    return normalize_fn(_parse_json_blob(_extract_message_content(resp.json())))


def analyze_fabric_image(image_path: Path, **kwargs) -> dict:
    return analyze_image(
        image_path,
        prompt=FABRIC_VISION_PROMPT,
        normalize_fn=normalize_fabric_vision,
        **kwargs,
    )
