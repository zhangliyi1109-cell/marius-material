"""简单会话登录：通过环境变量配置账号密码。"""

from __future__ import annotations

import os
import secrets
from typing import Any


def auth_enabled() -> bool:
    return bool(_password())


def username() -> str:
    return (os.environ.get("MATERIAL_AUTH_USER") or "admin").strip() or "admin"


def _password() -> str:
    return (os.environ.get("MATERIAL_AUTH_PASSWORD") or "").strip()


def secret_key() -> str:
    key = (os.environ.get("SECRET_KEY") or "").strip()
    if key:
        return key
    if auth_enabled():
        raise RuntimeError("已启用登录但未设置 SECRET_KEY 环境变量")
    return secrets.token_hex(32)


def verify_credentials(user: str, password: str) -> bool:
    if not auth_enabled():
        return True
    return user.strip() == username() and password == _password()


def is_logged_in(session: dict[str, Any]) -> bool:
    if not auth_enabled():
        return True
    return bool(session.get("user"))


def public_paths() -> frozenset[str]:
    return frozenset({"/login", "/health"})
