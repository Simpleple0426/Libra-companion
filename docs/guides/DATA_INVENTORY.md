# 项目数据与迁移清单

核对日期：2026-09-27。范围为当前项目源码、服务器文件目录、五个主要业务数据库及额外的音乐歌单数据库。没有读取手机设备内的实际数据，也没有执行导出、迁移或修改业务数据。

以下列出系统涉及的数据类型；代码支持某种类型不代表本机已有对应记录。文末是实际数据库表清单及现有私人数据 ZIP 导出的表级覆盖情况。

## 1. 用户与双方互动

- 会话线程、双方聊天消息、消息收藏、图片和语音附件。
- 通话会话与通话轮次。
- 用户状态、用户时间线、日历事件、待办、习惯与打卡。
- 专注记录、进行中的专注会话、使用时长和本地活动记录。
- 生日、纪念日等重要日期：存在 `important_dates` 表；当前移动端 ImportantDatesStore 使用 `mobile_state` 中的 `important_dates` 键。
- 名称、昵称、相识日期、头像、用户地址、主动联系频率等个性化设置。
- 动态、日记、信件、评论及关联媒体。

主要位置：`data/libra.db`、`data/content.db`、`data/uploads/`，以及手机应用私有存储。部分个性化配置在服务器 `app_settings` 与手机 SharedPreferences 中各有一份。

## 2. 左然基础设定与素材

- 人物设定、对话规则、提示词、生活引擎的固定人物配置。
- 个人线和卡面剧情、角色语料、候选与审核后的材料。
- 原作共同历史、结构化场景与原文片段。
- 城市、家庭、律所、地点、物品、世界规则与配置来源。
- 阅读知识、影视知识、经核对的台词。
- 默认头像、表情包、背景、图标、开屏视频、自习室音视频等应用资源。

主要位置：`libra/`、`backend/persona/`、`backend/prompts/`、`backend/config/`、`backend/life_prototype/` 内的配置文件、`docs/character/`、`mobile/assets/`，以及 `cognition.db` 的角色语料和共同历史表。

这些基础设定与运行存档应分开维护。配置中的来源字符串可能参与版本指纹比对，不能随文档移动随意改写。

## 3. 左然当前生活与个人经历

- 当前地点、活动、物品状态、需求、睡眠和生活世界配置。
- 每日粗日程、细日程、细日程执行状态、日程消息与修改记录。
- 生活事件、事件记忆、想法、观察、认知结果与证据。
- 工作和阅读等活动的结果、校验、尝试及执行回执。
- 生活 Agent 的运行步骤、调度任务、任务尝试、信号、恢复和运行日志。
- 生活与聊天之间的收件箱、发件箱、投递与处理状态。
- 模型调用账本、用量累计、失败和保护性暂停标记。

主要位置：`data/life/local-life-v1/prototype.sqlite3`、`agent-mailbox.sqlite3` 和 `cli-operations/`。`libra.db` 中还保留状态事件、属性、世界事件、思绪与时间线等数据，不能直接视为可删除的重复数据。

## 4. 记忆、情绪和聊天认知

- 原始经历、经历分段、分段关联、流边界与记忆任务。
- LMC 长期记忆、候选记忆、来源证据、版本、关系、坐标和事件上下文。
- 记忆抽取决策、审计、使用记录、召回记录与会话召回状态。
- 日历记忆摘要与来源关联、梦境页面、梦境条目、梦境任务和使用记录。
- 情绪当前状态、情绪事件与观察。
- 聊天认知回合、上下文版本、输入、动作、投递、通知、反馈和后处理任务。
- 模型用量统计、认知追踪和生活线索。
- 全文检索与向量索引：通常可从源数据重建，属于派生数据。

主要位置：`data/cognition.db`。

## 5. 公共日历与外部内容

- 工作日、周末、法定假日、调休日和所属假期：`libra.db/work_calendar`；本次核对覆盖 2026 年全年，共 365 条。
- 天气位置、最近天气观测、提醒设置与天气感知事件。
- 私人书库原始导入文件、解析后的书籍、章节/文本块、清单及阅读进度：`data/private_reading/`。
- 房间视频：`data/room_media/movies/`。
- 小红书搜索、笔记、浏览会话、分享记录、下载素材与任务输出：`content.db`、`data/uploads/xhs/`、`data/xhs_runs/`。
- 音乐组件支持的歌单、最近播放、资料、歌曲备注、收听次数和临时播放指令：`data/music/service/`；本次目录检查仅发现 `music_cache/`，其他 JSON 文件是代码定义的按需存储。
- 网易云远端账号与歌单：由外部平台保存，本地登录凭据和缓存不能替代远端数据。
- 应用自己的本地歌单另存于 `data/music/music.db`，已确认有 `playlists`、`playlist_songs` 两张表，均未包含在现有私人 ZIP 导出中。

## 6. 手机侧独立数据

- 后端地址 `libra_api_base_url`。
- 个性化设置的本地副本、用户当前状态、头像文件与本地文件路径。
- `focus_sessions.json` 专注记录及尚未同步的记录。
- 当前专注计时、进入专注前的状态、首页本地活动记录。
- 系统日历同步元数据、设备权限、通知注册信息。
- `mobile_state` 是服务器数据库表，不是手机文件：当前重要日期、使用时长等部分移动端状态保存在这里。

仅迁移服务器无法带走手机上尚未同步的数据。设备权限需要在新设备上重新授予，本机文件路径不能直接作为云端媒体地址。

## 7. 配置、凭据与部署依赖

- `.env` 中的模型、服务地址、开关和密钥，以及 `config/secrets/` 中的服务凭据。
- 模型 CLI 的程序、认证和本地配置；其中部分在项目目录之外。
- Firebase 服务账号、Android Firebase 配置与设备推送 token。
- 网易云 cookie/凭据、音乐服务认证文件及其他第三方登录状态。
- Android 签名密钥和 `key.properties`：属于应用发布资产。
- Windows 计划任务、启动脚本、Python/Node/Flutter/Java/Android SDK 路径与依赖版本。
- 后端与手机客户端源码、维护脚本、第三方组件和许可证。

服务器凭据需单独受控配置。设备 token、机器路径、锁文件和 CLI 会话状态不能当作普通业务记录原样恢复到另一台机器。

## 8. 备份、派生文件与诊断

- 数据库备份和迁移备份。
- 缩略图、音乐音频/歌词缓存、检索索引和向量缓存。
- HTTP/启动日志、模型调用审计和诊断输出。
- `output/` 中的表格导出与媒体工作文件。
- APK、构建缓存和 Python 缓存。

缓存可重建；审计与输出文件根据保留需求迁移。数据库 WAL/SHM 是运行时事务文件，迁移应使用一致性备份或停服后的完整数据库，不能只复制正在写入的主 `.db` 文件。

## 现有导出限制

`backend/application/private_data.py` 当前提供 v12 私人数据 ZIP，按固定表白名单导出，并附带受支持记录引用的 `/uploads/chat/` 媒体。它不是整个项目的完整迁移备份。

未完整覆盖的范围包括：独立生活库、消息邮箱、工作日历、`mobile_state`、重要日期表、角色知识资产、私人书库、房间媒体、音乐组件数据及手机本地文件等。导出中的 `app_settings` 也会过滤设备/运行专用键。全文检索、向量与部分摘要属于可重建数据。

表在导出白名单中只表示被导出，不表示其全部外部附件、运行依赖和关系恢复已获验证。

## Actual database tables / export coverage

Generated from read-only SQLite schema inspection. FTS internal shadow tables are grouped separately.


### `data/libra.db`

| Table | Included in current private ZIP |
|---|---|
| `app_settings` | Yes |
| `calendar_events` | Yes |
| `call_sessions` | Yes |
| `call_turns` | Yes |
| `checkin_events` | No |
| `focus_sessions` | Yes |
| `habit_checkins` | Yes |
| `habits` | Yes |
| `important_dates` | No |
| `libra_attribute_adjustments` | Yes |
| `libra_attribute_effects` | No |
| `libra_attribute_snapshots` | Yes |
| `libra_schedule_timeline_keys` | No |
| `libra_state_events` | Yes |
| `libra_thoughts` | No |
| `libra_timeline_events` | Yes |
| `messages` | Yes |
| `mobile_state` | No |
| `push_tokens` | No |
| `threads` | No |
| `todos` | Yes |
| `user_timeline_events` | Yes |
| `weather_awareness_events` | No |
| `work_calendar` | No |
| `world_events` | No |

### `data/content.db`

| Table | Included in current private ZIP |
|---|---|
| `favorite_messages` | Yes |
| `letters` | Yes |
| `shared_moment_comments` | Yes |
| `shared_moments` | Yes |
| `xhs_browse_sessions` | No |
| `xhs_notes` | No |
| `xhs_search_runs` | No |
| `xhs_shared_notes` | No |

### `data/cognition.db`

| Table | Included in current private ZIP |
|---|---|
| `affect_events` | Yes |
| `affect_observations` | Yes |
| `affect_state` | Yes |
| `canonical_shared_history` | No |
| `canonical_shared_history_chunk_embeddings` | No |
| `canonical_shared_history_chunks` | No |
| `canonical_shared_history_chunks_fts` | No |
| `canonical_shared_history_embeddings` | No |
| `canonical_shared_history_fts` | No |
| `character_corpus_v2` | No |
| `character_corpus_v2_embeddings` | No |
| `character_corpus_v2_fts` | No |
| `cognition_actions` | Yes |
| `cognition_call_inputs` | Yes |
| `cognition_context_revisions` | Yes |
| `cognition_delivery` | Yes |
| `cognition_feedback` | Yes |
| `cognition_inputs` | Yes |
| `cognition_notifications` | Yes |
| `cognition_post_jobs` | Yes |
| `cognition_turns` | Yes |
| `cognitive_traces` | Yes |
| `experience_segments` | Yes |
| `life_threads` | No |
| `llm_usage_events` | No |
| `lmc_calendar_sources` | No |
| `lmc_calendar_summaries` | No |
| `lmc_candidates` | No |
| `lmc_dream_entries` | Yes |
| `lmc_dream_jobs` | No |
| `lmc_dream_pages` | Yes |
| `lmc_dream_usage` | Yes |
| `lmc_embeddings` | No |
| `lmc_event_context` | Yes |
| `lmc_extraction_decisions` | Yes |
| `lmc_fts` | No |
| `lmc_memories` | Yes |
| `lmc_memory_audits` | Yes |
| `lmc_memory_coordinates` | Yes |
| `lmc_memory_relations` | Yes |
| `lmc_recall_logs` | Yes |
| `lmc_relation_jobs` | Yes |
| `lmc_revisions` | Yes |
| `lmc_search_documents` | No |
| `lmc_session_recall` | No |
| `lmc_sources` | Yes |
| `lmc_usage_events` | Yes |
| `memory_config` | No |
| `memory_jobs` | Yes |
| `memory_stream_boundaries` | No |
| `raw_experiences` | Yes |
| `segment_experiences` | Yes |

FTS internal tables: `canonical_shared_history_chunks_fts_config`, `canonical_shared_history_chunks_fts_content`, `canonical_shared_history_chunks_fts_data`, `canonical_shared_history_chunks_fts_docsize`, `canonical_shared_history_chunks_fts_idx`, `canonical_shared_history_fts_config`, `canonical_shared_history_fts_content`, `canonical_shared_history_fts_data`, `canonical_shared_history_fts_docsize`, `canonical_shared_history_fts_idx`, `character_corpus_v2_fts_config`, `character_corpus_v2_fts_content`, `character_corpus_v2_fts_data`, `character_corpus_v2_fts_docsize`, `character_corpus_v2_fts_idx`, `lmc_fts_config`, `lmc_fts_content`, `lmc_fts_data`, `lmc_fts_docsize`, `lmc_fts_idx`.


### `data/life/local-life-v1/prototype.sqlite3`

| Table | Included in current private ZIP |
|---|---|
| `events` | No |
| `life_agenda_messages` | No |
| `life_agent_runs` | No |
| `life_agent_steps` | No |
| `life_cognition_runs` | No |
| `life_daily_agendas` | No |
| `life_evidence` | No |
| `life_fine_agendas` | No |
| `life_fine_execution` | No |
| `life_interaction_replies` | No |
| `life_memories` | No |
| `life_memory_index` | No |
| `life_memory_validity` | No |
| `life_model_calls` | No |
| `life_model_transport_attempts` | No |
| `life_observations` | No |
| `life_receipts` | No |
| `life_received_messages` | No |
| `life_scheduler_attempts` | No |
| `life_scheduler_inbox` | No |
| `life_scheduler_jobs` | No |
| `life_scheduler_logs` | No |
| `life_scheduler_recoveries` | No |
| `life_scheduler_signals` | No |
| `life_state` | No |
| `result_attempts` | No |
| `result_controls` | No |
| `results` | No |

### `data/life/local-life-v1/agent-mailbox.sqlite3`

| Table | Included in current private ZIP |
|---|---|
| `life_agent_inbox` | No |
| `life_agent_outbox` | No |
| `mailbox_meta` | No |

### `data/music/music.db`

| Table | Included in current private ZIP |
|---|---|
| `playlists` | No |
| `playlist_songs` | No |
