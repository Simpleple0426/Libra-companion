# 左然的认知与记忆

打开 `backend/life/local-life-v1/prototype.sqlite3`，查看 `life_memories`。

记忆已经并回原生活数据库，不再使用独立的 `memory.sqlite3`。这张表是 Agent 实际写入和召回的来源，不是导出的副本。

| 字段 | 用途 |
| --- | --- |
| id | 稳定的记忆编号 |
| kind | event 为经历；thought 为反思认知，不能直接当作事实 |
| description | 内容；部分经历使用结构化 JSON 保留事实 |
| created_at | 形成时间 |
| last_accessed | 最近召回时间 |
| importance | 重要程度 |
| keywords | 关键词 |
| evidence | 原始证据编号 |
| actor_id | 所属角色 |
| status | observed 已观察、inference 推断、pending_importance 待处理 |

```sql
SELECT kind, description, created_at, importance, keywords, status
FROM life_memories
ORDER BY created_at DESC;
```

只看反思认知，在查询中加入 `WHERE kind = 'thought'`。

Agent 的 `memory.search` 按相关性、重要程度和最近访问时间排序，并继续排除失效或隔离的记忆。其证据、审核、索引也在同一个数据库中。

2026-09-30：陪伴日程的约定、开始、事项更新和结束事件接入 `life_memories`，由认知处理器按事件游标写入，重复处理不会重复记忆。记忆保留事件当时的事项、状态和时间；结束后仍可检索“陪用户看电影／听音乐”等具体事项。旧式预约日程在实际进入预留时段后记录开始事实。内容只证明陪伴约定或状态，不因时段结束就推断影片已看完或共同活动已经完成。这里只接入左然的生活长期记忆，不改变 LMC 或影音室消息入口，也不重放已经越过记忆游标的历史事件。

2026-09-29：增加 SQLite FTS5 增量索引。先取最多 256 条文字相关候选，再合并各最多 64 条近期、重要记忆，精排最多 384 条；提交时只复核候选，不再读全量记忆。失效和隔离过滤在候选截断前生效，避免失效记录占满候选。已有记忆首次检索时分批建索引，后续新增、正文／关键词修改、删除通过事务内脏队列同步；重复召回仍复核证据。

字词编码补充有限的生活词汇对应，例如读书／阅读／看书、观影／电影、散步／走走。存在文字匹配时，不让完全不相关的近期记录仅靠时间与重要性挤掉匹配项。这仍属于本地字词检索优化，不等于通用语义理解；没有下载模型或增加在线模型调用。已有显式配置的语义编码器继续负责候选精排。

完整结构见 [生活数据库说明](life_database_tables.md)。后台运行时请只读查看。
