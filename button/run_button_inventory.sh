#!/bin/bash
# 启动纽扣实时库存看板
cd "$(dirname "$0")"
PORT="${PORT:-8765}"
echo "打开 http://127.0.0.1:${PORT}/"
python3 button_inventory_server.py --port "$PORT" --host 127.0.0.1
