#!/bin/bash
# pack_deploy.sh
# 打包 fabric-only 部署包到 ../material-inventory-deploy/
#
# 包含：fabric + shared + material_app.py + start.sh + Procfile + requirements.txt
#       deploy/ 部署辅助 + static/ + .env.example
# 排除：button/ venv/ __pycache__/ *.db(0B脏) .env* bi-auth* *.log .git/
#
# 用法：
#   bash pack_deploy.sh
#   bash pack_deploy.sh --output /tmp/deploy.tar.gz
#
# 输出：
#   - material-inventory-deploy/  目录（解压即用）
#   - material-inventory-deploy-YYYYMMDD_HHMMSS.tar.gz  压缩包

set -euo pipefail

# 路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${SCRIPT_DIR}/../material-inventory-deploy"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TARBALL="${SCRIPT_DIR}/../material-inventory-deploy-${TIMESTAMP}.tar.gz"

# 参数
OUTPUT_TARBALL="${TARBALL}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT_TARBALL="$2"; shift 2 ;;
    --dir) DEPLOY_DIR="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

echo "======================================"
echo "MARIUS fabric 部署包打包"
echo "======================================"
echo "源目录: $SCRIPT_DIR"
echo "目标目录: $DEPLOY_DIR"
echo "压缩包: $OUTPUT_TARBALL"
echo ""

# 1. 清理旧目录
if [ -d "$DEPLOY_DIR" ]; then
  echo "🗑️  清理旧目录: $DEPLOY_DIR"
  rm -rf "$DEPLOY_DIR"
fi
mkdir -p "$DEPLOY_DIR"

# 2. 用 rsync 复制（支持排除规则 + 保留目录结构）
echo ""
echo "📦 复制必要文件..."

# 必须包含的文件/目录
INCLUDE=(
  "material_app.py"
  "start.sh"
  "Procfile"
  "requirements.txt"
  "fabric"
  "shared"
  "static"
  "deploy"
)

# 排除规则（适用于 rsync）
EXCLUDE=(
  "venv"
  "__pycache__"
  "*.pyc"
  "*.pyo"
  "*.pyd"
  ".env"
  ".env.bak"
  ".env.testlocal"
  "*.log"
  "bi-auth*.json"
  ".DS_Store"
  "button"
  "button.bak"
  "*.db-shm"
  "*.db-wal"
  ".git"
  "*.sqlite3"
  "*.sqlite3-journal"
)

# 构建 rsync 排除参数
RSYNC_EXCLUDES=()
for ex in "${EXCLUDE[@]}"; do
  RSYNC_EXCLUDES+=(--exclude="$ex")
done

# 逐项复制（文件 vs 目录分别处理）
for item in "${INCLUDE[@]}"; do
  src="$SCRIPT_DIR/$item"
  if [ ! -e "$src" ]; then
    echo "  ⚠️  跳过（不存在）: $item"
    continue
  fi
  if [ -d "$src" ]; then
    # 目录：rsync src/ DEPLOY/item/ 保留结构
    mkdir -p "$DEPLOY_DIR/$item"
    rsync -a "${RSYNC_EXCLUDES[@]}" "$src/" "$DEPLOY_DIR/$item/"
    echo "  📁 目录: $item/ ($(find "$DEPLOY_DIR/$item" -type f | wc -l | tr -d ' ') 文件)"
  else
    # 单文件
    cp "$src" "$DEPLOY_DIR/"
    echo "  📄 文件: $item"
  fi
done

# 3. 特别处理：过滤 0 字节的 fabric/button_tags.db
if [ -f "$DEPLOY_DIR/fabric/button_tags.db" ] && [ ! -s "$DEPLOY_DIR/fabric/button_tags.db" ]; then
  echo "  🗑️  移除 0 字节的 fabric/button_tags.db"
  rm -f "$DEPLOY_DIR/fabric/button_tags.db"
fi

# 4. 复制 .env.example（基于当前 .env 模板，不含真实密钥）
cat > "$DEPLOY_DIR/.env.example" << 'EOF'
# MARIUS 物料看板（fabric）部署配置
# 复制为 .env 后填入实际值

# 登录账号（生产环境务必修改）
MATERIAL_AUTH_USER=admin
MATERIAL_AUTH_PASSWORD=change-me-on-deploy

# Flask session 加密密钥（生产环境务必修改为随机 64 字符）
SECRET_KEY=please-generate-with-python3-secrets-token-hex-32

# 视觉打标 API Keys（打标功能需要，fabric 页面展示也需要）
XIAOMI_API_KEY=
KIMI_API_KEY=

# 服务端口
PORT=8080
HOST=0.0.0.0
EOF
echo "  ✅ 生成 .env.example"

# 5. 写部署说明
cat > "$DEPLOY_DIR/DEPLOY_README.md" << 'EOF'
# MARIUS fabric 部署包

> **fabric-only 模式**：本包只包含面料服务和共享模块，未包含 button 服务。
> **生成时间**：见 git log / 包时间戳
> **版本**：与 GitHub `main` 分支一致

---

## 📁 目录结构

```
material-inventory-deploy/
├── material_app.py            # Flask 入口（fabric + button 兼容，按钮可选）
├── start.sh                   # 启动脚本
├── Procfile                   # Heroku/Paas 启动配置
├── requirements.txt           # 依赖
├── .env.example               # 环境变量模板（不含真实密钥）
│
├── fabric/                    # 面料服务（含视觉打标）
│   ├── inventory_server.py
│   ├── tag_pipeline.py
│   ├── fabric_tags.db         # 面料视觉标签 SQLite
│   ├── visual_cache.json      # 视觉打标缓存
│   ├── inventory.html         # 面料页面
│   ├── inventory_config.json
│   └── .fabric_images/        # 面料图片（39M / 157 张）
│
├── shared/                    # 共享模块
│   ├── auth.py                # 登录鉴权
│   ├── load_env.py
│   ├── tag_store.py           # 视觉标签 SQLite 操作
│   ├── vision_tagger.py       # 大模型打标 API
│   └── ...
│
├── static/                    # 登录页 + 首页
│   ├── index.html
│   └── login.html
│
└── deploy/                    # 部署辅助
    ├── nginx-material.conf
    ├── material-inventory.service
    ├── install-aliyun.sh
    ├── env.example
    └── ...
```

**已排除**：
- `button/` 目录（按本次部署范围 1a=仅 fabric）
- `venv/`、`__pycache__/`、`*.pyc`（编译产物，服务器自建）
- `.env*`、`bi-auth*.json`（敏感信息）
- `*.db-shm`、`*.db-wal`（SQLite 临时文件）
- `.git/`

---

## 🚀 部署步骤

### 方式 A：rsync 推送到服务器（推荐）

```bash
# 在 Mac 上打包
cd /Users/zhangzhang/material-inventory
bash pack_deploy.sh

# 推送到服务器
rsync -avz --delete \
  /Users/zhangzhang/material-inventory-deploy/ \
  user@server:/opt/marius-material-inventory/
```

### 方式 B：scp 传压缩包

```bash
# 打包
cd /Users/zhangzhang/material-inventory
bash pack_deploy.sh

# 推送 tar.gz
scp /Users/zhangzhang/material-inventory-deploy-*.tar.gz \
  user@server:/tmp/

# 服务器上解压
ssh user@server
cd /opt/marius-material-inventory
tar -xzf /tmp/material-inventory-deploy-*.tar.gz
```

### 服务器端启动

```bash
ssh user@server
cd /opt/marius-material-inventory

# 1. 写 .env（不要传 git）
cp .env.example .env
nano .env
# 填入：
#   MATERIAL_AUTH_PASSWORD=<强密码>
#   SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
#   XIAOMI_API_KEY=<从 openclaw.json 取>
#   KIMI_API_KEY=<从 openclaw.json 取>

# 2. 创建 venv 并装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 测试启动
bash start.sh
# 看到 "面料 → /fabric" "纽扣 → 未部署" 即成功

# 4. 用 systemd 守护（可选，参考 deploy/material-inventory.service）
sudo cp deploy/material-inventory.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now material-inventory
sudo systemctl status material-inventory

# 5. 用 nginx 反向代理（可选，参考 deploy/nginx-material.conf）
sudo cp deploy/nginx-material.conf /etc/nginx/sites-available/marius-material
sudo ln -s /etc/nginx/sites-available/marius-material /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## 🔍 部署后验证

```bash
# 健康检查
curl http://server:8080/health
# 期望：{"ok":true,"services":["fabric"],"auth":true,"vision":{...}}

# 面料 API
curl -X POST -c cookies.txt -d "username=admin&password=$MATERIAL_AUTH_PASSWORD" \
  http://server:8080/login
curl -b cookies.txt http://server:8080/fabric/api/fabrics | jq '.items | length'
# 期望：返回面料数（100+）

# 视觉打标 API 是否通
curl -b cookies.txt http://server:8080/fabric/api/meta
```

---

## 🔄 与本地 Mac 的同步

服务器打完标后，让本地 Mac 拿到最新视觉标签：

### 服务器端导出
```bash
# 跑打标任务后
python3 fabric/extract_fabric_visual_tags.py   # 重新生成
python3 fabric/merge_fabric_visual_tags.py     # 合并 cache

# 导出为 JSON
sqlite3 fabric/fabric_tags.db ".dump sku_tags" > /tmp/sku_tags_dump.sql
# 或更干净：只导出 tag 内容
python3 -c "
import sqlite3, json
conn = sqlite3.connect('fabric/fabric_tags.db')
rows = conn.execute('SELECT detail_code, tags_json, status, has_vision FROM sku_tags').fetchall()
json.dump([{'detail_code':r[0],'tags':json.loads(r[1]),'status':r[2],'has_vision':bool(r[3])} for r in rows],
          open('/tmp/fabric_tags_export.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2)
print(f'导出 {len(rows)} 条')
"
```

### 推回本地
```bash
# 通过 GitHub 中转
cd /opt/marius-material-inventory
git add fabric/fabric_tags_export.json
git commit -m "vision: $(date +%Y-%m-%d) 自动导出 ($(date +%H:%M))"
git push origin main

# Mac 本地
cd /Users/zhangzhang/material-inventory
git pull
python3 fabric/merge_fabric_visual_tags.py --import /path/to/fabric_tags_export.json
```

---

## ⚠️ 常见问题

### Q: 启动报 `ModuleNotFoundError: No module named 'flask'`
A: 没装依赖。`source venv/bin/activate && pip install -r requirements.txt`

### Q: 启动报 `RuntimeError: 已启用登录但未设置 SECRET_KEY`
A: `.env` 没设 SECRET_KEY。`python3 -c 'import secrets; print(secrets.token_hex(32))'`

### Q: 视觉打标报 401 / 403
A: `.env` 里 XIAOMI_API_KEY / KIMI_API_KEY 没填。

### Q: 面料图片显示破图
A: 检查 `fabric/.fabric_images/` 是否完整（应有 157 个文件）。

### Q: /health 报 500
A: 99% 是 `vision_tagger` 的 API key 没配。看日志 `journalctl -u material-inventory -n 50`。
EOF

# 6. 统计
echo ""
echo "======================================"
echo "📊 打包结果统计"
echo "======================================"
TOTAL_SIZE=$(du -sh "$DEPLOY_DIR" | awk '{print $1}')
FILE_COUNT=$(find "$DEPLOY_DIR" -type f | wc -l)
IMG_COUNT=$(find "$DEPLOY_DIR/fabric/.fabric_images" -type f 2>/dev/null | wc -l)
DB_SIZE=$(du -sh "$DEPLOY_DIR/fabric/fabric_tags.db" 2>/dev/null | awk '{print $1}')

echo "📦 部署包大小: $TOTAL_SIZE"
echo "📁 文件数: $FILE_COUNT"
echo "🖼️  图片数: $IMG_COUNT"
echo "💾 视觉标签库: $DB_SIZE"
echo ""
echo "目录结构:"
find "$DEPLOY_DIR" -maxdepth 2 -type d | sed "s|$DEPLOY_DIR|.|" | sort

# 7. 打 tar.gz
echo ""
echo "📦 压缩中..."
tar -czf "$OUTPUT_TARBALL" -C "$(dirname "$DEPLOY_DIR")" "$(basename "$DEPLOY_DIR")"
TARBALL_SIZE=$(du -sh "$OUTPUT_TARBALL" | awk '{print $1}')
echo "✅ 压缩包: $OUTPUT_TARBALL ($TARBALL_SIZE)"

# 8. 计算 SHA256
SHASUM=$(shasum -a 256 "$OUTPUT_TARBALL" | awk '{print $1}')
echo "🔐 SHA256: $SHASUM"

echo ""
echo "✅ 打包完成！"
echo ""
echo "下一步："
echo "  1. 查看:  ls -lah $DEPLOY_DIR"
echo "  2. 推送到服务器:"
echo "     rsync -avz --delete $DEPLOY_DIR/ user@server:/opt/marius-material-inventory/"
echo "  3. 或传压缩包:"
echo "     scp $OUTPUT_TARBALL user@server:/tmp/"
