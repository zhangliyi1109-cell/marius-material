#!/bin/bash
# export_tags.sh — 导出视觉标签 → git push
#
# 用法：
#   bash export_tags.sh                # 默认（导出今天 + 推送）
#   bash export_tags.sh --no-push      # 只导出，不推送
#
# 通常用法：
#   1) 打标任务结束后 hook 调用
#   2) 或每天定时（cron 0 18 * * *）
#
# 流程：
#   1. 跑 export_tags.py → tags/fabric_YYYY-MM-DD.json + button_YYYY-MM-DD.json
#   2. git add tags/
#   3. git commit -m "vision: 自动导出 $(date)"
#   4. git push origin main
#
# 触发端：服务器 crontab / 打标 pipeline 的 callback

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DO_PUSH=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-push) DO_PUSH=0; shift ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

echo "======================================"
echo "MARIUS 视觉标签导出 + 推送"
echo "======================================"

# 1. 导出
echo ""
echo "📦 步骤 1/4: 导出 db → JSON"
python3 export_tags.py

# 2. 检查是否有变更
echo ""
echo "🔍 步骤 2/4: 检查 git 状态"
if ! git diff --quiet tags/ 2>/dev/null; then
  HAS_CHANGES=1
  echo "  ✏️  有变更，将提交"
else
  # 看 untracked 文件
  if [ -n "$(git ls-files --others --exclude-standard tags/ 2>/dev/null)" ]; then
    HAS_CHANGES=1
    echo "  📄 有新文件，将提交"
  else
    HAS_CHANGES=0
    echo "  ⏭️  无变更，跳过 commit"
  fi
fi

if [ "$HAS_CHANGES" = "0" ]; then
  if [ "$DO_PUSH" = "1" ]; then
    echo ""
    echo "📡 步骤 3-4/4: 跳过（无变更）"
  fi
  echo ""
  echo "✅ 完成（无变更）"
  exit 0
fi

# 3. 提交
echo ""
echo "💬 步骤 3/4: git commit"
TIMESTAMP="$(date +%Y-%m-%d) $(date +%H:%M)"
git add tags/

# 统计变更
NEW_FILES=$(git status --porcelain tags/ | grep '^??' | wc -l | tr -d ' ')
MOD_FILES=$(git status --porcelain tags/ | grep '^ M' | wc -l | tr -d ' ')

MSG="vision: 自动导出 $TIMESTAMP"
if [ "$NEW_FILES" -gt 0 ] && [ "$MOD_FILES" -gt 0 ]; then
  MSG="$MSG (+$NEW_FILES 新文件 / ~$MOD_FILES 修改)"
elif [ "$NEW_FILES" -gt 0 ]; then
  MSG="$MSG (+$NEW_FILES 新文件)"
elif [ "$MOD_FILES" -gt 0 ]; then
  MSG="$MSG (~$MOD_FILES 修改)"
fi

git commit -m "$MSG"
echo "  ✅ $MSG"

# 4. 推送
if [ "$DO_PUSH" = "1" ]; then
  echo ""
  echo "📡 步骤 4/4: git push"
  if git push origin main 2>&1; then
    echo "  ✅ 已推送到 origin/main"
  else
    echo "  ❌ 推送失败！请检查 SSH key / 网络"
    exit 1
  fi
else
  echo ""
  echo "⏭️  跳过 push（--no-push 模式）"
fi

echo ""
echo "✅ 完成"
echo ""
echo "📋 下一步（Mac 本地）:"
echo "  cd /Users/zhangzhang/material-inventory"
echo "  bash pull_tags.sh    # 拉最新 + 导入本地 DB"
