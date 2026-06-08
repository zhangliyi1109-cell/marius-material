#!/bin/bash
# 启动面料实时库存看板（默认 ≥300m）
cd "$(dirname "$0")"
PORT="${PORT:-8766}"
echo "打开 http://127.0.0.1:${PORT}/"
python3 fabric_inventory_server.py --port "$PORT" --host 127.0.0.1
