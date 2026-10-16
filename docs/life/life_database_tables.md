# 生活数据库

用户主导的陪伴保存于 `life_state.current.companionships`，结束后的重规划版本为 `companion_epoch`；无需新增数据库表。协议与状态语义见 [用户主导的陪伴](companionship.md)。

生活数据统一保存在 `backend/life/local-life-v1/prototype.sqlite3`。不再依赖独立的 `memory.sqlite3`。

此前存储整理将原库的 43 张表精简为 28 张，同时把原来拆出的记忆表并回。19 张同类表合并为 3 张表；没有建立同名视图把旧表藏起来，也没有将这些表搬到另一个运行数据库。此后新增的预约与派生检索索引见下文，28 张是当时的数量。

日常主要查看：

| 表 | 内容 |
| --- | --- |
| life_memories | 经历、反思认知；`kind` 区分 event 和 thought |
| life_state | 当前生活状态、人设环境配置、认知进度和调度状态；`name` 区分用途 |
| life_daily_agendas | 按日期、版本保存粗日程；每项为开始／结束时间、粗略状态和地点 |
| life_appointments | 跨日期约定：时间范围、planned/cancelled 状态和包含原消息引用的 body；属于意图，不是活动事实 |
| life_fine_agendas | 细日程 |
| life_received_messages | 收到的消息 |
| events | 左然实际发生的经历，以自然语言保存，不包含重启、时间空档等程序日志 |
| life_evidence | 观察更新、阅读记录、认知依据、资源版本、消息归档等证据；`category` 区分来源 |
| life_receipts | 睡眠推进、Agent 操作、结果审核的幂等回执；`event_control` 保存内部状态提交回执，供去重、认知和恢复使用 |

`events` 字段：`id`（事件 ID）、`occurred_at`（发生时间）、`description`（自然语言描述）、`kind`（事件类型），以及可为空的 `activity_id`、`coarse_plan_id`、`fine_plan_id`。例如“左然到达书房。”“左然开始阅读《某本书》。”事实随活动提交一并写入，展示时不根据后来的状态重新改写历史描述。开始、进展、中断、完成分别记录，不能用开始事件冒充完成；移动仅在最后一段完成时记录到达。

2026-09-26 按用户要求清空旧事件历史并重建上述结构，旧历史不回填。原表的程序控制回执归入已有 `life_receipts`，保留恢复和去重所需依据；没有新增表。运行状态、已有记忆和粗细计划保持不变。

`life_state.name`：`current` 为当前生活状态，`world` 为固定环境配置，`cognition` 为认知处理状态，`interaction` 为交互与睡眠配置，`scheduler` 为调度状态，`encoder` 为检索编码器配置，`resources` 为资源配置，`work_extension` 为工作扩展配置。

粗计划格式 `coarse-state-v3`：`body.items` 中每项包含 `id`、`start_time`、`end_time`、`state_type`、`from_location`、`end_location`、`intent`。状态沿用旧日程的 commuting/working/eating/exercising/resting/free/sleeping；地点名称用于阅读，`location_id`、`destination_id` 用于执行。`source_window` 用于跨版本识别，`constraints` 保留用户预约和必要生活安排。粗计划不保存选定的书目、电影或具体工作；旧版本保留可读，新的写入统一采用上述格式。

`intent` 是宽泛的优先方向，如工作、阅读、娱乐、备餐、家务、洗漱、洗澡、准备睡觉；自由选择或移动时可为空。由适配当前世界后的活动生成，不从旧来源地点推断。细计划优先参考意图，允许在合法候选中调整，并在理由中说明，不按意图额外缩小可用资源集合。必要日常安排和预约仍由 `constraints` 约束。

每日未完成的洗澡保留为必要安排，生成与改期不得提前到18:00之前，执行可用时间同样设有18:00下限。睡前卧室时段的意图为“准备睡觉”，保持 `free` 与清醒语义，入睡仍由晚安机制负责。版本更新后，后台下次清醒规划周期按现有版本机制重建剩余日程；历史计划不回填意图。此修改尚未引入活动 Skill 加载器。

影音区的自由休闲意图为“看电影”；客厅的一般自由休闲意图为“看电视”，原有整理、清洁、衣物活动仍为“家务”。完整家庭目录包含二层影音区 `home.f2.media`，电影资源及新计划使用该地点；旧历史中适配到客厅的电影记录保留。意图不授予电视播放或家务执行能力，相关 Skill 和资源仍待接入。

到达实际地点后，`life_state.current.coarse_state` 记录当前粗状态，`events` 写入“左然正在书房”等地点事实。细计划随后结合当前状态、记忆和可用资源选择任务：free 可选阅读、观影或工作，working 只选工作。事件措辞参考旧 `libra_timeline_events`，但不会预写未来事实或虚构 Wi-Fi、设备操作。

剩余表用于实际执行：

- 日程执行：life_agenda_messages、life_fine_execution。
- 自主 Agent：life_agent_runs、life_agent_steps。
- 认知与召回：life_cognition_runs、life_observations、life_memory_index、life_memory_validity。
- 派生候选索引（2026-09-29）：life_memory_fts（FTS5 及 SQLite 自动维护的内部表）、life_memory_search_ids、life_memory_search_dirty、life_memory_search_meta。原记忆仍以 life_memories 为准；初始化仅添加索引结构并排队建索引，不删除历史。
- 模型调用：life_model_calls、life_model_transport_attempts。
- 内部交互：life_interaction_replies。
- 调度恢复：life_scheduler_jobs、life_scheduler_attempts、life_scheduler_inbox、life_scheduler_logs、life_scheduler_recoveries、life_scheduler_signals。
- 活动结果：results、result_controls、result_attempts。

这些仍独立的表承担不同的查询、执行或恢复职责，没有因为追求表数少而删除必要的恢复数据。应用只连接一个生活数据库，正常备份也只需备份这个文件；聊天邮箱仍由独立通信模块管理。

跨日期预约初始化会接纳已有最新日程中的预约，保留取消记录避免再次接纳。普通失败任务的自动恢复沿用 life_scheduler_recoveries 保存链路，life_scheduler_jobs.receipt 中的 automatic_retry_at 保存冷却时间；不清空原审计记录。

迁移脚本：`backend/scripts/simplify_life_storage.py`。它先备份并在副本试迁移，逐组验证记录，再迁移正式库。旧审计报告可以保留旧分组名称供历史比较，这不代表数据库仍有这些表。
