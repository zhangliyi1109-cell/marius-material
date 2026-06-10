#!/bin/bash
set -e
cd "$(dirname "$0")"
export PORT="${PORT:-8080}"
export HOST="${HOST:-0.0.0.0}"

# 加载 .env
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# 从 openclaw.json 加载 API keys（如果 .env 里没有）
if [ -z "$XIAOMI_API_KEY" ] || [ -z "$KIMI_API_KEY" ]; then
  if [ -f ~/.openclaw/openclaw.json ]; then
    while IFS='=' read -r k v; do
      [ -n "$k" ] && [ -z "${!k}" ] && export "$k=$v"
    done < <(python3 -c "
import json,sys
d=json.load(open('$HOME/.openclaw/openclaw.json'))
v=(d.get('env',{}).get('vars',{}))
for k in ('XIAOMI_API_KEY','KIMI_API_KEY'):
    if v.get(k): print(f'{k}={v[k]}')
" 2>/dev/null)
  fi
fi

# 创建虚拟环境
VENV="$(dirname "$0")/venv"
PYTHON="${VENV}/bin/python3"
if [ ! -x "$PYTHON" ]; then
  echo "创建虚拟环境…"
  python3 -m venv "$VENV"
fi

echo "安装依赖…"
"$VENV/bin/pip" install -q -r requirements.txt

echo "MARIUS 物料看板"
echo "  首页  http://127.0.0.1:${PORT}/"
echo "  纽扣  http://127.0.0.1:${PORT}/button/"
echo "  面料  http://127.0.0.1:${PORT}/fabric/"
exec "$PYTHON" material_app.py --host "$HOST" --port "$PORT"
