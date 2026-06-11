#!/usr/bin/env python3
"""MARIUS 物料库存统一入口：/ 首页 · /button 纽扣 · /fabric 面料"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for p in (ROOT, ROOT / "shared", ROOT / "button", ROOT / "fabric"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from load_env import load_project_env

load_project_env(ROOT)

from flask import Flask, jsonify, redirect, request, send_from_directory, session

from auth import auth_enabled, is_logged_in, public_paths, secret_key, verify_credentials
from fabric.inventory_server import bp as fabric_bp

# 尝试加载 button blueprint（仅在 fabric-only 部署时缺失）
_button_bp = None
try:
    from button.inventory_server import bp as _button_bp  # type: ignore
except Exception:
    pass

app = Flask(__name__, static_folder=str(ROOT / "static"))
app.secret_key = secret_key()
app.permanent_session_lifetime = timedelta(days=7)


@app.before_request
def require_login():
    if not auth_enabled() or is_logged_in(session):
        return None
    path = request.path.rstrip("/") or "/"
    if path in public_paths():
        return None
    if request.path.startswith("/static/"):
        return None
    if request.accept_mimetypes.best_match(["application/json", "text/html"]) == "application/json":
        return jsonify({"error": "unauthorized", "login": "/login"}), 401
    next_url = request.full_path if request.query_string else request.path
    return redirect(f"/login?next={next_url}")


@app.get("/login")
def login_page():
    if is_logged_in(session):
        return redirect(request.args.get("next") or "/")
    return send_from_directory(app.static_folder, "login.html")


@app.post("/login")
def login_submit():
    user = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    next_url = (request.form.get("next") or request.args.get("next") or "/").strip()
    if not next_url.startswith("/"):
        next_url = "/"
    if verify_credentials(user, password):
        session.permanent = True
        session["user"] = user
        return redirect(next_url)
    return redirect(f"/login?error=1&next={next_url}")


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


def _vision_health() -> dict:
    import json

    from vision_tagger import resolve_api_key, uses_vision_api, vision_settings

    out: dict = {}
    # fabric-only 部署可能没有 button，依次尝试读取 config
    for name, rel in (("button", "button/inventory_config.json"), ("fabric", "fabric/inventory_config.json")):
        if _button_bp is None and name == "button":
            # fabric-only 部署：跳过 button
            continue
        path = ROOT / rel
        if not path.exists():
            # 该服务未部署
            continue
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        vision_cfg = cfg.get("vision") or {}
        provider = (vision_cfg.get("provider") or ("xiaomi" if name == "button" else "agent")).strip().lower()
        if not uses_vision_api(provider):
            out[name] = {"provider": provider, "api_configured": None}
            continue
        vs = vision_settings(vision_cfg)
        p = vs["provider"]
        out[name] = {
            "provider": p,
            "model": vs["model"],
            "api_configured": bool(resolve_api_key(p)),
        }
    return out


@app.get("/health")
def health():
    return {
        "ok": True,
        "services": [s for s in ("button", "fabric") if s == "fabric" or _button_bp is not None],
        "auth": auth_enabled(),
        "auth_user": __import__("auth").username() if auth_enabled() else None,
        "vision": _vision_health(),
    }


app.register_blueprint(fabric_bp, url_prefix="/fabric")
if _button_bp is not None:
    app.register_blueprint(_button_bp, url_prefix="/button")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MARIUS 物料库存看板")
    parser.add_argument("--port", type=int, default=int(__import__("os").environ.get("PORT", "8080")))
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    print(f"物料看板: http://{args.host}:{args.port}/")
    print(f"  纽扣 → /button" if _button_bp is not None else "  纽扣 → 未部署（fabric-only 模式）")
    print(f"  面料 → /fabric")
    if auth_enabled():
        print("  登录已启用 → /login")
    else:
        print("  登录未启用（请在 .env 设置 MATERIAL_AUTH_PASSWORD）")
    app.run(host=args.host, port=args.port, debug=False)
