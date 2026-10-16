# 维护命令

所有命令均从 `backend/` 目录执行，统一使用模块入口：

```powershell
cd backend
python -m scripts.check_text_encoding
python -m scripts.check_runtime
python -m scripts.prepare_story_corpus --help
```

根目录的同名兼容启动器已移除，现有自动化若调用 `python backfill_llm_usage.py`，应改为 `python -m scripts.backfill_llm_usage`。各脚本的参数以其源码和命令行帮助为准。

| 用途 | 模块 |
|---|---|
| 编码和诊断 | `check_text_encoding`、`check_runtime`、`life_status`、`audit_database_shards`、`verify_life_chat_agents` |
| 内容导入与准备 | `import_canon_corpus`、`import_reviewed_shared_history`、`prepare_story_corpus`、`normalize_material_pronouns`、`promote_six_point_candidates` |
| 数据回填 | `backfill_llm_usage`、`backfill_message_memory` |
| 日历与日程 | `sync_work_calendar`、`retire_schedule_data`（停服迁移旧日程） |
| 数据维护 | `migrate_database_shards`、`simplify_life_storage`、`repair_sticker_event_context`、`retire_legacy_data`、`reset_memory` |

这些模块包含数据修改操作；目录整理不执行迁移、重置或回填。

`check_runtime` 只读取健康状态、API 定义和媒体列表，不发送聊天或调用模型。需要额外检查数据库完整性时使用 `python -m scripts.check_runtime --integrity --timeout 60`。

`python -m scripts.verify_life_chat_agents --live` 现转入固定 `gpt-5.6-sol` 的五场景评测；原 `--message` 任意消息参数不再提供，使用 `--case` 选择有确定判分标准的用例。完整范围、30 场景及报告格式见 [评测说明](../evals/README.md)。
