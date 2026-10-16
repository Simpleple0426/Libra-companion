> 清理说明（2026-09-26）：测试、评测脚本、测试夹具和外部参考副本已按用户要求删除。下文涉及这些文件的评测结果仅为历史记录，相关命令不再适用。

# Libra 记忆系统：当前实现与验收记录

最新集成：记忆链路现由 [统一认知回合](Libra_Cognition_Pipeline_Implementation.md) 调用，备份现为 V6；以下 V3/V5 与阶段性测试数字保留为当时记录。

后续集成说明：新记忆链路保留；旧记忆表及 CRUD 已清理，情绪与语料已独立重构，私有备份现为 V5，不恢复退役旧表。本文下方的 V3 / 82 项测试属于当时验收记录，新增实现边界见 [情绪与语料当前实现](情绪系统/Libra_Affect_Corpus_Implementation.md)。

记录日期：2026-09-05。本文合并 A–C 与 D–I 的实现情况，是当前功能、接口和验收状态的统一入口。设计规范见 [Libra Memory System](Libra_Memory_System.md)，早期开发快照见 [A–C 历史归档](archive/Memory_Phase_ABC_Implementation.md)。

状态：A–I 首版后端链路已接通；最近一次完整测试 82 项通过；开发结束时未重启真实服务，尚未完成真实模型质量验收。本文不是生产已启用的证明。

## 已实现

| 阶段 | 当前代码行为 |
|---|---|
| A：数据与证据 | 新保存的文本聊天与 RawExperience 同事务提交；保留来源、修订和审计，不回填旧聊天、不迁移旧画像。 |
| B：Episode | 分段后由模型提出写入建议，独立核验再经原文、说话人、类型与版本检查，事务提交 Episode、来源、索引及任务结果。 |
| C：召回 | FTS5、实体及时间检索结合有效性、版本、敏感性和近期上下文去重；可选向量故障不阻断本地检索，纠正待处理时保守停用相关旧结论。 |
| D：Semantic | Episode 提交后产生持久化归纳任务。独立日期、明确原话、反例和来源版本参与校验；一次普通表达不会直接成为稳定画像。用户模型是有效 Semantic 的视图，不是另一份会漂移的档案。 |
| E：Story / Timeline | 保存事件成员、阶段、事件关系和未完成事项；因果关系须有原文支持，禁止关系环；更新不得静默丢弃仍有效的历史成员。提供时间线查询。 |
| F：生命周期 | 可配置半衰期、保护下限、迟滞状态转换；弱化与休眠不删除正文。明确回忆确认、后续证据可强化；普通检索不强化，收据防重复，自动强化有日/会话限额。 |
| G：Relationship / Self | 区分单方表达与共同约定；边界需直接证据，自我认识需真实参与或明确纠错。稳定边界进入回复约束，不覆盖人格，也不授予外部操作权限。 |
| H：Reflection | 至少三个独立证据组、限定范围、反例检索说明和替代解释；默认有效期 30 天，置信度最高 0.85。检索保留假设标签、范围及替代解释；后台至少间隔 24 小时。 |
| I：认知闭环 | 当前消息先落原始记录，再召回、评价、构建回应计划。旧情绪不直接当作当前情绪；回复经规则与独立模型校验，不通过则在原线程重试仅当前事实，必要时使用保守短回复。实际使用与成功保存后才记录 response_used。 |

基础实现位于 `backend/memory_system.py`、`memory_schema.sql`；演化与认知位于 `memory_evolution.py`、`memory_evolution.sql`、`memory_lifecycle.py`、`memory_context.py`、`memory_cognition.py`。消息事务接线位于 `database.py`，聊天和后台接线位于 `main.py`，备份适配位于 `private_data.py`。

## 分段、检索与后台任务

- 每 15 秒扫描原始经历，按线程、话题、时间和长度分段。闲置 2 分钟关闭片段，最多 16 条消息，20 分钟间隔形成边界；一条消息中的多个事件可共用原始证据。
- 整理模型每次调用超时 60 秒，任务租约 10 分钟，失败指数退避，5 次后标为 failed，可手动重试。回复校验另有独立调用，整理超时不是整个聊天的延迟上限。
- FTS5 使用中文单字/二元片段、英文及数字 token。Packet 最多 4 条记忆，默认 2200 字符预算，转义计入预算；不是精确 tokenizer token 上限。
- 本地文本索引与记忆同事务提交，可从记录重建。可选向量在事务外计算，提交时检查 revision、模型和维度。默认不调用 embedding 服务；适配器实现 `model_id`、`dimensions` 和 `embed(text, timeout_seconds=...)`。
- `context_selected` 表示入选上下文；`response_used` 表示经校验实际使用且回复成功保存。两者都不自动等同于强化证据。
- 结构化 affect / commitments 字段仍有预留；首版主要在带证据的 Episode 正文中保留报告的情绪与计划。

## 一致性与运行方式

- 新结构按单用户设计，没有 `user_id`。`memory_used_ids` 是回复实际使用的**记忆编号**，不是用户编号。
- 保留主 Codex 线程；整理、核验使用独立会话，不改主线程指针。线程历史仍依赖原 Codex 会话存储。
- 新版记忆独立于旧长期记忆表。没有删除旧文件、清空真实数据库或迁移旧画像；旧表不再参与聊天记忆注入。
- Episode 更新或失效会沿依赖链将旧派生结论降为待复核，检索还会检查原始证据和版本。
- 任务有租约、重试和幂等提交；阶段关闭时暂停领取，不丢任务。所有阶段默认开启，后端下次启动后生效。
- 聊天执行期间暂缓原始经历分段，避免慢回复尚未结束就形成长期认识；退出时释放，崩溃残留屏障 30 分钟到期。后台可继续整理先前已封闭的片段。
- 状态接口的用户主动状态变更接入 state_snapshot；多模态和其它世界事件生产者尚未全部接线。
- 备份升为 V3，包含派生对象、依赖、生命周期收据和认知审计。兼容 V1/V2；导入 V2 后为其中的新系统 Episode 补建演化任务。导入保留本机主线程指针，重建索引，不导入线程会话文件。

## 管理接口

| 接口 | 用途 |
|---|---|
| `GET /memory/status` | 查看能力、记忆摘要、任务状态及错误代码 |
| `GET /memory/records/{memory_id}` | 查看内容、来源与版本历史 |
| `POST /memory/jobs/{job_id}/retry` | 重试 failed 任务 |
| `POST /memory/records/{memory_id}/invalidate` | 标记失效并保留审计，关联派生认识进入复核 |
| `PATCH /memory/features` | 配置 consolidation / story / projection / reflection / lifecycle / cognition 开关 |
| `PATCH /memory/lifecycle-policy` | 配置半衰期、状态阈值与强化限额 |
| `GET /memory/user-model` | 查看有效、有来源支持的用户语义认识 |
| `GET /memory/timeline` | 查看事件时间线；可按 story_memory_id 查询成员和未完成事项 |

现阶段提供后端接口，未新增专用前端管理页。

## 验证与未验证项

### 多通道召回 V1

个人记忆召回现按显式通道生成候选：dense、FTS sparse、实体、日期、情绪以及安全事件关系图；通道间使用 RRF 融合，不直接比较不同检索器的原始分数。默认开放一跳关系扩展，仅遍历 `precedes`、`continues_as`、`resolved_by`、`clarified_by` 中状态有效、来源为 explicit/derived 且两端 revision 有效的边；二跳需要调用方显式指定 `graph_hops=2`。

短专名、代号和引用短语可触发 `literal_raw` 救援。它只检索尚未晋升且未被任何 MemoryRecord 引用的正常原始经历，并排除当前上下文、纠错、敏感内容和凭据。结果标记为 `fallback_archive / navigation_only / unverified_raw_event`，最多使用召回预算的四分之一，不能作为稳定事实。

每个结果携带 `recall_layer`、`recall_channels` 和 `score_breakdown`；召回日志记录查询变体、各通道候选、RRF 分解、过滤数量和最终选择。相同正文跨 ID/通道按规范化内容指纹去重，数字仍参与指纹。query expansion 和情绪共振为 A/B 开关，默认关闭；扩展器由调用方注入，失败时降级且不影响原始查询。情绪通道还要求主题重叠，不能只因情绪坐标相近召回无关经历。

### 时间层级摘要与注入分辨率

`memory_calendar.py` 将有效、非敏感且原始证据仍有效的 Episode 投影为可重建的日、周、月、季、年摘要。每条摘要记录时间范围、scope、来源数量和来源签名，`memory_calendar_sources` 保存具体 `memory_id + source_revision`。它们是上下文索引，不是 MemoryRecord，也不能覆盖原始事实；来源失效、revision 变化或生命周期进入 dormant 后会在刷新时移出。摘要索引不进入私人数据备份，恢复后由权威 Episode 重建。

召回完成安全过滤后，根据查询意图、年龄、保护状态、strength 和 access_state 标记 `retrieval_resolution`：近期且活跃的记忆使用 `full`，较旧但仍可访问的记忆使用对应日期层级的 `summary`，低可访问性结果只输出 `pointer`。显式回忆请求和 protected 记忆保持 full；raw rescue 永远是 pointer。分辨率投影不更新生命周期，也不构成召回强化。

检索夹具位于 `backend/fixtures/memory_v1_cases.json`，包含 60 组人工设计案例（40 development、20 heldout）；另有 20 事件混合检索测试。以下结果是上次代码验收记录，本次文档整理没有重新运行代码测试。

使用临时 SQLite 数据库测试，不启动真实应用或调用真实模型：

```powershell
python -m unittest discover -s backend -p 'test_*.py'
python -m py_compile backend/main.py backend/memory_system.py backend/memory_evolution.py backend/memory_context.py backend/memory_lifecycle.py backend/memory_cognition.py backend/application/private_data.py
python backend/benchmark_memory.py --size 10000 --queries 100
```

本轮完整测试：82 项通过。覆盖证据独立性、反例、来源级联失效、并发版本、Story/因果、关系边界、自我经历限制、Reflection、衰减、强化收据、回复校验、进行中会话屏障、V1/V2/V3 备份及主线程连续性。

本地合成 10,000 条 Episode / 100 次热缓存检索：中位 38.44 ms，P95 41.09 ms，精确项目命中 100/100，无远程模型调用。这不是端到端聊天延迟或真实语义召回质量指标。

尚未完成真实模型质量验收和线上观察；独立核验会增加模型调用与回复延迟，不能保证绝无误判。当前分段、候选选择和 Appraisal 调整是有界首版规则，并非设计文档全部评分公式的逐项复刻。归纳候选限最近 200 条 Episode 中的 30 条，已有派生对象限最近 100 条；超长 Story 在证据不足时保守拒绝更新，需要后续真实数据评估这些窗口。向量仍是可选适配器，默认没有额外 embedding 服务。

本轮没有重启正在运行的服务。代码测试通过与生产已启用是两件事；重启后才会自动建表并运行新链路，原 Codex 会话存储必须继续保留。
