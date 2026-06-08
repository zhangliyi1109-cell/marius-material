# MARIUS 物料库存看板

独立于 [weather](https://github.com/zhangliyi1109-cell/weather) 项目，提供观远 BI 实时物料库存与视觉标签筛选。

## 路由

| 路径 | 说明 |
|------|------|
| `/` | 物料首页（入口） |
| `/button/` | 纽扣库存看板 |
| `/fabric/` | 面料库存看板（默认 ≥300m） |

## 本地运行

依赖：

- Python 3.10+
- [guancli](https://github.com/guan-data/guancli) 已配置观远 BI 凭证
- 环境变量 `XIAOMI_API_KEY`（新增 SKU 自动视觉打标，可选）

```bash
cd material-inventory
chmod +x start.sh
./start.sh
# 或
pip install -r requirements.txt
python3 material_app.py --port 8080
```

## 部署（Railway / Render / 自建）

1. 新建 GitHub 仓库（勿放入 weather 仓库）：

```bash
cd material-inventory
git init
git add .
git commit -m "Initial material inventory (button + fabric)"
gh repo create marius-material --public --source=. --push
```

2. 平台设置：

- **Start command**: `python3 material_app.py --host 0.0.0.0 --port $PORT`
- **Env**: `XIAOMI_API_KEY`, 以及 guancli 所需配置（需在运行环境安装 guancli 并登录）

## 目录结构

```
material-inventory/
├── material_app.py      # 统一入口
├── static/index.html    # 首页
├── shared/              # 标签库、小米视觉 API
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
