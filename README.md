# fsdoc_pass_refresh

飞书在线文档密码刷新 —— 添加在线文档链接，一键或定时刷新文档的访问密码，密码可通过对外 API 按条目 ID 获取。

## 功能特性

- **文档密码管理**：支持 wiki / docx / doc / sheet / file / base（bitable）等飞书文档类型，启用或刷新链接访问密码
- **一键刷新**：支持单个刷新、批量刷新所选、一键刷新全部
- **定时刷新**：每个条目可配置 5 字段 cron 表达式（如 `0 9 * * *`），到点自动换新密码
- **文档名称显示**：自动获取并展示文档名称，点击可跳转原文档
- **统一认证**：全站共用一份飞书应用凭证（App ID / App Secret）
- **页面访问认证**：访问密码登录，30 天免重复登录，支持修改密码（原密码 + 两次新密码校验），密码入库、升级不重置
- **对外接口**：`GET /api/password/{条目ID}`，请求头携带访问密码（`Authorization: Bearer <访问密码>`）认证，供程序直接获取最新密码
- **权限自动修复**：链接分享未开放时自动设置为「互联网可阅读」；权限不足时给出「添加文档应用」操作指引

## 快速开始

### Docker 部署（推荐）

```bash
docker compose up -d
```

访问 `http://localhost:8000`，默认访问密码为 `admin123`（可在 `docker-compose.yml` 中通过 `PAGE_PASSWORD` 修改；页面修改密码后会存入数据库，此后以库内密码为准，升级镜像不会重置）。

### 本地运行

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
PAGE_PASSWORD=admin123 .venv/bin/python -m uvicorn app.main:app --port 8000
```

## 使用说明

1. **配置飞书应用**：在 [飞书开放平台](https://open.feishu.cn/app) 创建企业自建应用，开通云文档相关权限并发布版本；在页面「统一认证信息」处保存 App ID / App Secret。
2. **添加文档条目**：粘贴文档链接（如 `https://xxx.feishu.cn/wiki/xxxx`），可选填定时 cron 表达式，点击「添加」。
3. **添加文档应用**：首次使用某文档时，需在飞书文档页面「···」→「更多」→「添加文档应用」中为应用授权，否则会提示权限不足（1063002）。
4. **获取密码**：点击「刷新」或等待定时任务执行后，在列表中查看当前密码；外部程序调用 `GET /api/password/{条目ID}` 获取，请求头直接携带访问密码认证（登录后页面「对外接口」卡片会展示请求示例）：

```bash
curl http://localhost:8000/api/password/1 \
  -H "Authorization: Bearer 你的访问密码"
```

返回示例：

```json
{"id": 1, "url": "...", "status": "正常", "password": "q795xx", "message": "备注", "last_refresh": "..."}
```

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `PAGE_PASSWORD` | 页面访问初始密码（库内未存密码时生效） | `admin123` |
| `DB_PATH` | SQLite 数据库路径 | `./data/app.db` |
| `TZ` | 时区 | `Asia/Shanghai` |

## 开源协议

本项目基于 [Apache License 2.0](LICENSE) 开源。
