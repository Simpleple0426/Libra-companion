# 功能与实现说明

这份文档说明归然 / Libra 目前各项功能的大致实现路径，适合想了解项目结构、调整功能或进行二次开发的使用者。

## 整体架构

```text
Android App（Flutter）
        │ HTTP / Tailscale
        ▼
电脑本地后端（FastAPI）
        ├── SQLite：聊天、状态、日记、日历等本地数据
        ├── Codex CLI 或 Claude Code：角色回复与创作内容
        ├── 本地人设、提示词、语料库：约束角色表达
        └── 可选外部服务：天气、语音、推送、音乐
```

手机不直接保存模型密钥；后端和私有数据保留在自己的电脑。

## 对话与角色回复

- 前端：`mobile/lib/screens/chat_page.dart`
- 后端：`backend/main.py`、`backend/model_cli.py`
- 人设与规则：`backend/persona/`、`backend/prompts/`

用户消息发送到 FastAPI 后端。后端读取近期聊天、当前情绪状态、角色人设、相关语料和用户设置，再调用 `.env` 中选择的 Codex CLI 或 Claude Code 生成回复。聊天记录写入 `libra.db`，因此重启后端不会丢失对话历史。

图片与配套文字会作为一次请求提交；语音先转写为文字，再进入同一条对话链路。

## 情绪与状态系统

- 核心逻辑：`backend/emotion.py`
- 规则说明：`backend/persona/emotion_engine.md`
- 数据表：`emotional_state`、`emotional_events`、`libra_state_events`、`libra_attribute_snapshots`

系统会结合聊天内容、角色工作/休息状态、互动间隔和时间推进，维护情绪、疲劳、压力、亲密、想念、责任等状态。首页“他的内心”展示的是当前状态快照，不是模型临时编造的文字。

聊天会对疲劳和压力产生恢复效果；每天起床时会按规则重置或校正状态，数值会限制在合理范围内。

## 主动联系与 Check-in

- 定时与事件入口：`backend/main.py`
- 提示词：`backend/prompts/weather_reminder.md` 等

后端按设置的 check-in 间隔检查当前时间、左然状态、最近聊天和用户近期动态，再决定是否生成主动消息。主动消息和用户发起的聊天使用同一角色线程，避免他忘记近期对话。

天气变化、状态变化、动态/行程事件是否触发联系，受个性化设置中的开关和主动程度影响。

## 动态、日记与信件

| 功能 | 提示词 | 写入内容 |
| --- | --- | --- |
| 私人动态 | `backend/prompts/moment.md` | 近期状态、事件与聊天中值得记录的片段 |
| 每日日记 | `backend/prompts/diary.md` | 当日聊天、状态、动态与互动事件 |
| 信件 | `backend/prompts/letter.md` | 定时触发或用户在聊天中明确请求 |

三者由后端调用模型生成，并写入 SQLite。提示词要求只使用已提供的真实事实，尽量避免把当天内容写成流水账。

## 语料库与检索

- 新语料入口：`libra/zuoran_corpus_v2/`（旧库已删除）
- 导入脚本：`backend/import_canon_corpus.py`
- 配置：`backend/corpus_config.py`
- 数据表：`character_corpus_v2` 及其 FTS 索引表，仅使用审核通过的 V2 样本

语料按 V2 格式导入 `character_corpus_v2`，保留来源定位、人物逻辑、表达方向和审核状态。SQLite FTS 负责全文检索；只有审核通过的非运行时生成样本用于回复参考，新库为空时不回退旧库。

## 首页、状态与动态记录

- 首页：`mobile/lib/screens/home_page.dart`
- 状态页：`mobile/lib/screens/libra_activity_page.dart`
- 用户事件记录：`mobile/lib/services/activity_event_store.dart`

首页会读取后端返回的左然状态、动态、天气和用户自身的使用事件。进入自习室、书房或影音室等行为会写入用户动态，后端可在后续 check-in 中读取这些事件。

当前版本**不再包含“用户到家 / 离家”地理围栏、家庭坐标或后台定位服务**。天气定位只在前台刷新天气时使用手机 GPS。

## 语音、图片与收藏

- 接口与媒体处理：`backend/main.py`
- 上传目录：`backend/uploads/`
- 收藏数据表：`favorite_messages`

语音上传后由 Groq Whisper 转写；当前默认模型由 `.env` 的 `WHISPER_MODEL=whisper-large-v3` 控制。文字、语音转写结果均可收藏；收藏列表只保存需要展示的内容。图片上传到后端本地目录，并由聊天消息关联。

## 天气

- 手机定位与请求：`mobile/lib/services/weather_service.dart`
- 后端天气处理：`backend/weather.py`、`backend/weather_awareness.py`

每次天气刷新优先使用手机当前 GPS；失败时才使用已缓存的位置。后端将经纬度转换为天气摘要，并可将明显天气变化作为主动提醒的候选信息。天气所需定位权限与已移除的家庭地理围栏功能无关。

## 日历、习惯与专注

- 日历：`mobile/lib/screens/calendar_page.dart`、`mobile/lib/services/calendar_service.dart`
- 专注：`mobile/lib/screens/study_room_page.dart`、`mobile/lib/services/focus_stats_store.dart`
- 数据表：`calendar_events`、`habits`、`habit_checkins`、`focus_sessions`

日历支持待办、打卡和重要日期。自习室开始/结束专注时会记录会话，统计页根据 `focus_sessions` 汇总。系统日历可按规则向未来补充，用户自行编辑的日期仍保留在本地数据库。

## 书房与影音室

- 书房：`mobile/lib/screens/book_room_page.dart`、`backend/reading.py`
- 影音室：`mobile/lib/screens/music_room_page.dart`

书房把导入的书籍拆分为章节和文本片段，支持按章节阅读、生成阅读感想，以及围绕当前章节与左然聊天。影音室提供歌曲搜索、播放队列和本地列表；音乐搜索服务是可选组件，外部播放地址可能会过期。

进入或离开书房、影音室会写入用户动态，供首页展示和后端后续互动参考。

## 个性化设置与连接

- 设置页：`mobile/lib/screens/personalization_settings_page.dart`
- 后端地址：`mobile/lib/config/api_config.dart`
- 首次连接页：`mobile/lib/screens/backend_connection_page.dart`

用户可设置双方头像、首页显示名、昵称、称呼、相遇日期、主动程度、check-in 范围和可选权限。后端地址首次由用户直接填写 `http://100.x.x.x:8000`，保存到手机本地；因此同一个 APK 可以由不同用户连接自己的电脑后端。

## 推送通知

- 手机端：`mobile/lib/services/push_service.dart`
- 后端：`backend/main.py`、`push_tokens` 数据表

启用 Firebase 后，后端主动消息可推送到手机。没有配置 Firebase 时，聊天和本地功能仍可使用，只是无法依赖系统级后台推送；打开 App 后仍会同步数据。
