# 持久数据与代码发布

## 本地目录

代码继续位于 backend、mobile、libra、third_party、tools；项目根目录新增独立的 data、config、logs、backups。启动入口和手机后端地址不变。

| 路径 | 内容 |
|---|---|
| `data/libra.db`、`content.db`、`cognition.db` | 聊天、记忆、情绪、日历、节假日、设置等全部原有主库数据 |
| `data/life/` | 生活状态、日程、生活记忆、消息邮箱、调用账本、原有暂停标记 |
| `data/uploads/` | 实际上传媒体及缩略图；原 `/uploads/` URL 不变 |
| `data/private_reading/`、`data/room_media/` | 私人书库、阅读进度、房间媒体 |
| `data/music/music.db`、`data/music/service/` | 自建歌单和音乐服务数据，含现有音乐缓存 |
| `data/xhs_runs/` | 小红书任务输出 |
| `config/.env`、`config/secrets/`、`config/music/` | 本机设置、推送凭据和音乐认证文件 |
| `logs/` | 启动及运行日志 |
| `backups/database/`、`backups/migrations/` | 日常备份和搬迁前快照/校验记录 |

`backend/config/` 仍是程序默认配置和 schema；它与根目录 `config/` 的本机凭据用途不同。角色原始语料、默认人设和提示词随版本维护；数据库内的已运行角色状态和配置不会被代码包覆盖。生活人物指纹变化仍需要显式迁移。

## 配置路径

`infrastructure/paths.py` 先加载配置，再确定所有数据路径。进程环境变量优先于 `.env`；相对路径以项目根目录为基准。

- `LIBRA_CONFIG_DIR`：外置配置目录，必须通过进程环境设置；默认 `<项目>/config`。
- `LIBRA_ENV_FILE`：可直接指定环境配置文件，默认 `<配置目录>/.env`。
- `LIBRA_RUNTIME_DIR`：持久数据目录，默认 `<项目>/data`。
- `LIBRA_BACKUP_DIR`：日常备份目录，默认 `<项目>/backups/database`。
- `LIBRA_LOG_DIR`：正常后端日志目录，默认 `<项目>/logs`。
- `LIBRA_CACHE_DIR`：预留统一缓存目录，默认 `<项目>/cache`；当前已有音乐缓存和媒体缩略图仍随其数据子目录保留。

发现旧 `backend/libra.db` 或仅有部分主数据库时，程序拒绝启动，防止误用空库掩盖旧数据。

## 发布到独立程序目录

在项目根目录执行：

```powershell
python tools/package_release.py
```

产物在 releases/。脚本只从明确的代码目录取文件，排除 data/config/logs/backups、数据库、环境文件、签名密钥、第三方认证文件和构建缓存。

VPS 可以采用：

```text
/srv/libra/app/       # 解压代码包
/srv/libra/data/      # 正式使用数据
/srv/libra/config/    # 正式配置与凭据
/srv/libra/logs/
/srv/libra/backups/
```

服务进程环境设置 `LIBRA_CONFIG_DIR=/srv/libra/config`。在其 `.env` 中设置：

```dotenv
LIBRA_RUNTIME_DIR=/srv/libra/data
LIBRA_BACKUP_DIR=/srv/libra/backups/database
LIBRA_LOG_DIR=/srv/libra/logs
```

第一次上云才迁移现有 data 与适用于新机器的配置；后续只更新 app。不要上传本地开发数据库覆盖服务器，不要向 `/srv/libra/` 整体执行覆盖或删除同步。新机器还需配置依赖、模型 CLI、Linux 服务管理和平台相关第三方程序；本次本地路径迁移不代表 Linux VPS 已部署完成。

## 升级验证

2026-09-27 本地搬迁验证：5,889 个文件搬迁前后的文件标识和大小一致，9 个关键数据库及配置文件的 SHA-256 一致；6 个数据库完整性检查通过，所有表记录数一致。启动后，健康检查、书库、当前阅读、歌单及歌曲、媒体列表、生活状态和音乐服务接口均返回 200，上传文件抽样读取内容一致。旧位置未重新生成数据库。审计结果和迁移前数据库快照位于 `backups/migrations/20260927-storage/`。

生活系统此前因 `CLI turn failed` 进入的保护性暂停仍保留，未在搬迁中解除；本次没有触发模型对话或验证外部平台登录。

先备份并在副本验证版本兼容和数据库迁移。更新代码后，在 backend/ 执行 `python -m scripts.check_runtime`，并核对书库、媒体、歌单和生活状态。模型调用原有保护性暂停会保留，因此应区分“原有暂停”与“迁移故障”。

开发环境路径隔离回归检查：`python -B -m unittest discover -s backend/tests -v`（项目根目录）。数据版本变化需增量迁移；不能靠代码包清空、重建或替换线上数据库。
