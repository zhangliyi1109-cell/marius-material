"""从项目根目录加载 .env（不覆盖已有环境变量）。"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> bool:
    if not path.is_file():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value
    return True


def load_project_env(root: Path) -> Path | None:
    for name in (".env", "deploy/auth.env"):
        path = root / name
        if load_env_file(path):
            return path
    return None
