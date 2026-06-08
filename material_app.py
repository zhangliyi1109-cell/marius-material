#!/usr/bin/env python3
"""MARIUS 物料库存统一入口：/ 首页 · /button 纽扣 · /fabric 面料"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for p in (ROOT, ROOT / "shared", ROOT / "button", ROOT / "fabric"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from flask import Flask, send_from_directory

from button.inventory_server import bp as button_bp
from fabric.inventory_server import bp as fabric_bp

app = Flask(__name__, static_folder=str(ROOT / "static"))


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/health")
def health():
    return {"ok": True, "services": ["button", "fabric"]}


app.register_blueprint(button_bp, url_prefix="/button")
app.register_blueprint(fabric_bp, url_prefix="/fabric")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MARIUS 物料库存看板")
    parser.add_argument("--port", type=int, default=int(__import__("os").environ.get("PORT", "8080")))
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    print(f"物料看板: http://{args.host}:{args.port}/")
    print(f"  纽扣 → /button")
    print(f"  面料 → /fabric")
    app.run(host=args.host, port=args.port, debug=False)
