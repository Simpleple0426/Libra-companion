# 后端目录

在本目录运行 `python -m uvicorn main:app --host 0.0.0.0 --port 8000`，或使用 `启动后端.cmd`。Windows 计划任务继续使用 `start_backend.ps1`。

启动后执行 `python -m scripts.check_runtime` 检查 HTTP、数据库健康、生活引擎和媒体接口。Windows 计划任务部署可用 `./restart_backend_task.ps1` 重启；脚本会等待 `/health` 返回正常，而不只检查端口。

`start_backend.ps1` 通过 `scripts.run_server` 将 Uvicorn 日志直接写入文件，避免依赖 PowerShell 日志管道。需要排查依赖加载耗时时可添加 `-TraceImports`；正常启动默认关闭。

| 路径 | 职责 |
|---|---|
| `main.py` | ASGI 入口 |
| `app/` | 服务组合、HTTP 路由和事件循环 |
| `application/` | 聊天、工具和生活等用例编排；私人数据导入导出位于 `private_data.py` |
| `domains/` | 记忆、情绪、内容、角色和世界领域逻辑 |
| `infrastructure/` | 数据库、模型、向量和天气等基础设施 |
| `life_prototype/` | 当前实际使用的生活引擎；保留包名以兼容现有运行环境 |
| `scripts/` | 唯一的维护命令实现目录，详见[命令说明](scripts/README.md) |
| `config/` | 配置模板和 JSON schema |
| `prompts/`、`persona/` | 提示词和角色规则 |
| `vendor/` | 后端使用的第三方组件 |

## 本地运行数据

以下路径均相对于项目根目录，已与后端源码分离并由 Git 忽略：

- `config/.env`、`config/secrets/`、`config/music/`：本机配置和凭据。
- `data/*.db`：三个主数据库；运行时可能有对应 WAL/SHM。
- `data/life/`：生活引擎、消息邮箱和模型调用账本。
- `data/uploads/`、`data/private_reading/`、`data/room_media/`：实际媒体和书库。
- `data/music/`：歌单数据库与音乐服务数据。
- `data/xhs_runs/`：浏览任务输出。
- `backups/database/`、`backups/migrations/`、`logs/`：日常备份、迁移快照和日志。

运行数据路径集中定义在 `infrastructure/paths.py`。不要在服务运行期间移动数据库或单独删除 WAL/SHM 文件。

配置文件在路径初始化之前加载。VPS 可通过进程环境变量 `LIBRA_CONFIG_DIR` 指向外置配置目录，再在该目录的 `.env` 设置绝对 `LIBRA_RUNTIME_DIR`、`LIBRA_BACKUP_DIR`、`LIBRA_LOG_DIR`。具体操作见[持久数据与发布](../docs/guides/PERSISTENT_STORAGE.md)。

生活引擎配置里的来源字符串也是版本数据，可能参与完整配置比对或人物指纹校验。移动文档时保留这些已持久化的来源值，通过文档索引说明新位置；不要把它们当普通文件链接批量替换。
