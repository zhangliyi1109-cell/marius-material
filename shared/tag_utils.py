"""打标队列通用工具。"""

from __future__ import annotations


def is_quota_error(message: str) -> bool:
    s = (message or "").lower()
    return (
        "429" in s
        or "quota exhausted" in s
        or "limitation" in s
        or "配额" in s
        or "quota" in s
    )


def quota_user_message() -> str:
    return "小米视觉 API 配额已用尽，请次日再点「补打标」，或联系管理员充值/换 Key"
