#!/bin/bash
set -e
cd "$(dirname "$0")"
export PORT="${PORT:-8080}"
export HOST="${HOST:-0.0.0.0}"

pip3 install -q -r requirements.txt 2>/dev/null || true
echo "MARIUS 物料看板"
echo "  首页  http://127.0.0.1:${PORT}/"
echo "  纽扣  http://127.0.0.1:${PORT}/button/"
echo "  面料  http://127.0.0.1:${PORT}/fabric/"
python3 material_app.py --host "$HOST" --port "$PORT"
