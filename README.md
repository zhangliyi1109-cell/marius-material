# MARIUS 物料库存看板

观远 BI 实时物料库存与视觉标签筛选。

## 路由

| 路径 | 说明 |
|------|------|
| `/` | 物料首页（入口） |
| `/button/` | 纽扣库存看板 |
| `/fabric/` | 面料库存看板（默认 ≥300m） |

## 登录

设置环境变量后启用登录页（`/login`），未设置 `MATERIAL_AUTH_PASSWORD` 时本地开发可直接访问：

| 变量 | 说明 |
|------|------|
| `MATERIAL_AUTH_PASSWORD` | 登录密码（必填才启用） |
| `MATERIAL_AUTH_USER` | 用户名，默认 `admin` |
| `SECRET_KEY` | Flask 会话密钥，启用登录时必填 |

```bash
export SECRET_KEY="$(openssl rand -hex 32)"
export MATERIAL_AUTH_USER=admin
export MATERIAL_AUTH_PASSWORD=你的密码
python3 material_app.py
```

## 本地运行

依赖：

- Python 3.10+
- [guancli](https://github.com/guan-data/guancli) 已配置观远 BI 凭证
- 视觉 API Key（新增 SKU 自动打标，可选）：`XIAOMI_API_KEY` 或 `KIMI_API_KEY`

```bash
cd material-inventory
chmod +x start.sh
./start.sh
# 或
pip install -r requirements.txt
python3 material_app.py --port 8080
```

## 部署（GitHub + Railway / Render）

### 1. 推送到 GitHub

本地已 `git init` 并 commit 后，任选一种方式：

**方式 A：安装 GitHub CLI 后一键创建**

```bash
brew install gh
gh auth login
cd material-inventory
gh repo create marius-material --public --source=. --push
```

**方式 B：网页建库 + 手动 push**

1. 打开 https://github.com/new 新建仓库 `marius-material`（不要勾选 README）
2. 本地执行：

```bash
cd material-inventory
git remote add origin git@github.com:zhangliyi1109-cell/marius-material.git
git branch -M main
git push -u origin main
```

（HTTPS 亦可：`https://github.com/zhangliyi1109-cell/marius-material.git`）

### 2. 云平台

- **Start command**: `python3 material_app.py --host 0.0.0.0 --port $PORT`
- **Env**: `XIAOMI_API_KEY` / `KIMI_API_KEY`，以及 guancli 所需配置（需在运行环境安装 guancli 并登录）

## 视觉打标 Provider

在 `button/inventory_config.json` 与 `fabric/inventory_config.json` 的 `vision` 段切换：

| provider | 说明 | 环境变量 | 默认 model |
|----------|------|----------|------------|
| `xiaomi` | 小米 Mimo 视觉 API | `XIAOMI_API_KEY` | `mimo-v2.5` |
| `kimi` | Moonshot Kimi 视觉 API | `KIMI_API_KEY` 或 `MOONSHOT_API_KEY` | `kimi-k2.6` |
| `agent` | 仅面料：使用本地 `visual_cache.json`，不调 API | — | — |

纽扣示例（小米）：

```json
"vision": {
  "provider": "xiaomi",
  "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
  "model": "mimo-v2.5"
}
```

切换 Kimi 时改 `provider` 并填写对应 Key，重启服务即可：

```json
"vision": {
  "provider": "kimi",
  "base_url": "https://api.moonshot.cn/v1",
  "model": "kimi-k2.6"
}
```

健康检查：`GET /health` 返回各模块当前 provider 与 Key 是否已配置。

## 目录结构

```
material-inventory/
├── material_app.py      # 统一入口
├── static/index.html    # 首页
├── shared/              # 标签库、视觉 API（xiaomi / kimi）
├── button/              # 纽扣服务 + 视觉缓存
└── fabric/              # 面料服务 + 视觉缓存
```

## 维护脚本

```bash
# 纽扣：合并 visual_cache → seed_inventory.json
python3 button/merge_visual_tags.py

# 面料：合并 visual_cache → fabric_tags.db（需 guancli）
python3 fabric/merge_visual_tags.py
```

## 数据说明

- `button/visual_cache.json` / `fabric/visual_cache.json`：主图 URL → 视觉标签（可提交）
- `*.db`：运行时 SQLite，已在 `.gitignore`，部署后首次启动自动从 cache 迁移
- `.button_images/` / `.fabric_images/`：图片下载缓存，不提交
