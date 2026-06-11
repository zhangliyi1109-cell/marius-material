# 视觉标签服务器 ↔ 本地同步方案

> **方案确认**：1a + 2a + 3a（2026-06-11 与 Iris 对齐）
> **流程**：服务器打完标 → 立刻 push → Mac 本地 cron 每小时 pull → 导入本地 DB → 知识库同步

---

## 🔄 数据流

```
┌────────────────────┐                            ┌────────────────────┐
│ 服务器（VPS）       │                            │ 本地 Mac            │
│                    │                            │                    │
│ 视觉打标（pipeline）│                            │ OpenClaw + 知识库    │
│        ↓           │                            │                    │
│ fabric_tags.db      │                            │ fabric_tags.db     │
│ shared/button_tags.db│                           │ shared/button_tags.db│
│        ↓           │                            │                    │
│ export_tags.py     │                            │                    │
│    ↓                │                            │                    │
│ tags/*.json        │   ←  git push (即时)        │ tags/*.json        │
│                    │ ──────────────────────────→ │                    │
│                    │   →  GitHub origin/main     │ pull_tags.py       │
│                    │                            │    ↓               │
│                    │                            │ 写回本地 .db        │
│                    │                            │    ↓               │
│                    │                            │ vision_sync_local.py│
│                    │                            │    ↓               │
│                    │                            │ 知识库MD更新        │
└────────────────────┘                            └────────────────────┘
```

---

## 📂 目录结构

```
material-inventory/
├── export_tags.py             # 1) db → tags/*.json
├── export_tags.sh             # 2) git add + commit + push
├── pull_tags.py               # 3) tags/*.json → db
├── pull_tags.sh               # 4) git pull + pull_tags.py
└── tags/                      # 🆕 视觉标签导出文件（git 跟踪）
    ├── fabric_2026-06-11.json
    └── button_2026-06-11.json
```

---

## 🖥️ 服务器端（打标完后）

### 手动触发

```bash
cd /opt/marius-material-inventory
bash export_tags.sh            # 导出 + 提交 + 推送
```

### 自动化：打标 pipeline 完成后 hook

```bash
# 在打标脚本末尾追加：
python3 tag_pipeline.py --full
bash export_tags.sh
```

### 自动化：每天定时

```bash
# 服务器 crontab
0 18 * * * cd /opt/marius-material-inventory && bash export_tags.sh >> /var/log/material-tags.log 2>&1
```

---

## 💻 本地 Mac

### 手动拉取

```bash
cd /Users/zhangzhang/material-inventory
bash pull_tags.sh              # git pull + 导入
```

### 自动化：每小时拉一次（推荐）

```bash
# OpenClaw cron
0 * * * * cd /Users/zhangzhang/material-inventory && bash pull_tags.sh --auto >> ~/.openclaw/logs/tag-sync.log 2>&1
```

之后由已有的 `vision_sync_local.py` 周一 9:30 cron 触发知识库 MD 同步。

### 临时跳过 git pull（手动复制 JSON 后）

```bash
# 比如手工 scp 了 JSON 过来
bash pull_tags.sh --no-pull   # 只导入，不 git pull
```

---

## 📊 数据 schema

### `tags/{kind}_{YYYY-MM-DD}.json` 顶层结构

```json
{
  "_meta": {
    "kind": "fabric" | "button",
    "export_time": "2026-06-11T15:52:21",
    "db_path": "fabric/fabric_tags.db",
    "count": 298,
    "schema_version": 1
  },
  "items": [
    {
      "detail_code": "6090100",
      "image_url": null,
      "tags": {
        "主色描述": "白色-1#",
        "色系": "中性",
        "织法组织": "",
        "花纹图案": "纯色",
        "厚薄感": "中等",
        "风格": ["休闲", "日常"],
        "适用场景": ["衬衫", "裤装", "外套"],
        "关键词": ["棉", "白色-1#", ...]
      },
      "status": "done",
      "has_vision": true,
      "error": null,
      "updated_at": 1781000000.0
    }
  ]
}
```

### 数据库表

```sql
CREATE TABLE sku_tags (
  detail_code TEXT PRIMARY KEY,
  image_url TEXT,
  tags_json TEXT NOT NULL,
  status TEXT NOT NULL,
  has_vision INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  updated_at REAL NOT NULL
);
```

---

## 🔧 故障排查

### Q: pull_tags.py 报 "tags 目录不存在"
A: `cd /Users/zhangzhang/material-inventory && git pull`

### Q: 导入后库条数没增加
A: 说明所有 detail_code 已存在 → 全部走"更新"分支，正常。日志会显示 "新增 0 / 更新 N"。

### Q: 服务器 push 失败
A: 检查 SSH key 是否配好：
```bash
ssh -T git@github.com
# 期望: "Hi zhangliyi1109-cell! You've successfully authenticated..."
```

### Q: pull_tags.py 报"备份失败"
A: 检查 db 文件权限：
```bash
ls -la fabric/fabric_tags.db shared/button_tags.db
# 应是当前用户可写
```

### Q: 怎么回滚？
A: 备份文件名是 `*.db.backup_YYYYMMDD_HHMMSS`，找到出问题前的备份覆盖即可：
```bash
cp fabric/fabric_tags.db.backup_20260611_155226 fabric/fabric_tags.db
```

### Q: tags/ 目录会占很多空间吗？
A: 不会。每天一份 JSON：
- fabric_2026-06-11.json: 307KB
- button_2026-06-11.json: 39KB
- 一年约 100MB
- 建议加个清理：保留 30 天

---

## 📋 与其他流程的衔接

| 流程 | 时机 | 关联 |
|------|------|------|
| 服务器打标 | 手动/定时 | 结束后调 `export_tags.sh` |
| 本地拉标签 | cron 每小时 | `pull_tags.sh` |
| 知识库 MD 同步 | cron 周一 9:30 | `vision_sync_local.py` 读 `127.0.0.1:8080` API（已被本地 DB 更新） |
| BI 库存快照 | cron 每天 9:00 | `inventory_snapshot.py` 独立运行 |
