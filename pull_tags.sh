#!/bin/bash
# pull_tags.sh — git pull + 导入 tags/*.json 到本地 db
#
# 用法：
#   bash pull_tags.sh                 # 拉 + 导入
#   bash pull_tags.sh --no-pull       # 只导入（不 git pull）
#   bash pull_tags.sh --auto          # 用于 cron（静默模式，无变更不输出）
#
# 通常用法：
#   - 本地 cron 每小时跑一次 (0 * * * *)
#   - 或打完服务器标签后立即手动跑
#
# 流程：
#   1. git pull origin main   (拿服务器最新 tags/*.json)
#   2. python3 pull_tags.py   (导入到本地 fabric_tags.db / button_tags.db)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DO_PULL=1
AUTO=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-pull) DO_PULL=0; shift ;;
    --auto) AUTO=1; shift ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# 静默模式：只在有变化时输出
log() {
  if [ "$AUTO" = "0" ] || [ "${2:-info}" = "important" ]; then
    echo "$1"
  fi
}

log "======================================"
log "MARIUS 视觉标签本地同步"
log "======================================"

# 1. git pull
if [ "$DO_PULL" = "1" ]; then
  log ""
  log "📥 步骤 1/2: git pull origin main"

  # 记录 pull 前的 hash
  BEFORE=$(git rev-parse HEAD 2>/dev/null || echo "none")

  if git pull origin main --rebase 2>&1 | tee /tmp/pull.log; then
    AFTER=$(git rev-parse HEAD)
    if [ "$BEFORE" = "$AFTER" ]; then
      log "  ⏭️  无新提交"
    else
      log "  ✅ 已更新: ${BEFORE:0:7} → ${AFTER:0:7}"
    fi
  else
    log "  ❌ git pull 失败！"
    exit 1
  fi
else
  log ""
  log "⏭️  跳过 git pull（--no-pull 模式）"
fi

# 2. 导入
log ""
log "🔄 步骤 2/2: 导入 tags/*.json → 本地 db"
log "" "important"
python3 pull_tags.py 2>&1 | tee /tmp/import.log
IMPORT_STATUS=$?

# 检查是否有变更
NEW_TAGS=$(ls -1t tags/*_*.json 2>/dev/null | head -2 | wc -l | tr -d ' ')

if [ $IMPORT_STATUS -ne 0 ]; then
  log ""
  log "❌ 导入失败"
  exit $IMPORT_STATUS
fi

log ""
log "======================================"
log "✅ 同步完成"
log "======================================"
log ""
log "📊 当前本地状态:"
log "  fabric DB: $(sqlite3 fabric/fabric_tags.db 'SELECT COUNT(*) FROM sku_tags' 2>/dev/null || echo '?') 款"
log "  button DB: $(sqlite3 shared/button_tags.db 'SELECT COUNT(*) FROM sku_tags' 2>/dev/null || echo '?') 款"
log ""
log "📋 下一步：让本地知识库拿到最新视觉标签："
log "   python3 /Users/zhangzhang/.openclaw/workspace/1_MARIUS/AI项目/知识库/原始数据/库存快照/vision_sync_local.py"
