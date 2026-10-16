# Libra Memory System

> 状态：Phase A–I 首版后端链路已接通，真实模型质量验收待完成  
> 当前版本：V1.1  
> 当前范围：单用户 Greenfield 重写；保留当前 Codex 线程；A–C 基础与 D–I 演化/认知链路已落地，未重启真实服务

本文是完整设计规范，回答“系统应该怎样工作”；当前代码行为、接口、取舍与测试结果统一见 [记忆系统实现与验收记录](Libra_Memory_Implementation.md)。下文的阶段限制和“先实现／暂缓”描述属于分阶段路线，不代表当前仍停留在 A–C；设计目标不能视为已达到的指标。早期开发数据单独保留在 [A–C 历史归档](archive/Memory_Phase_ABC_Implementation.md)。

## 阅读导航

1. **设计基础**：参考来源、目标、系统边界与总体架构；
2. **记忆形成与写入**：Raw Experience、Episode、写入策略、数据模型与分段合并；
3. **记忆组织与演化**：Timeline、Story、遗忘强化、关系记忆、自我记忆与 Reflection；
4. **记忆召回**：候选生成、过滤、重排、上下文组装与评估；
5. **实施路线**：从数据契约到完整认知链路的工程里程碑；
6. **附录**：文档版本迭代记录。

> **规范说明：**第 12–21 节为 V1 实现规范，第 1–10 节用于解释设计思想。概念章节中的简写应按第 21 节 Canonical Contract 映射；数据库字段、枚举、接口与状态机一律以 Canonical Contract 为准。



# 第一部分：设计基础

## 1. 参考来源与设计取舍

Libra 记忆系统综合参考以下 5 个论文 / 项目方向，并结合陪伴型 Agent 的长期关系需求进行重新设计。

> **该系统不是对任何单一论文框架的直接复刻，而是将不同工作的核心机制重新组合，并针对 Libra 的陪伴场景做二次设计。**

### MemoryBank

主要参考：

- 长期记忆的持续保存；
- 遗忘机制；
- 记忆再次出现后的强化；
- User Portrait / 长期用户认识。

Libra 中的对应设计：

```text
Memory Strength
Decay
Reinforcement
Semantic Memory / User Model
```

同时，Libra 不采用“弱记忆直接消失”的思路，而是进一步设计为：

```text
Active
 ↓
Weak
 ↓
Dormant
```

Dormant Memory 平时不容易被召回，但在出现强线索时仍可以重新激活。

### LD-Agent


主要参考：

- event perception；
- long-term dialogue memory；
- dynamic user persona；
- dynamic agent persona。

Libra 中的对应设计：

```text
Raw Experience
→ Memory Perception
→ Episode

Episodes
→ Semantic Memory / User Model
```

同时，LD-Agent 对 agent persona 的动态建模启发了 Libra 的：

```text
Self Memory
```

但 Libra 的 Self Memory 不等同于直接修改 Core Persona。

它表示：

> 作为这个长期存在的 Libra / 左然，他后来真实经历过什么。



### THEANINE

主要参考：

- memory timeline；
- 时间关系；
- 因果关系；
- 保留状态随时间发生的变化。

Libra 不希望长期记忆最终只剩下：

```text
用户喜欢咖啡。
```

而希望保留：

```text
以前不太喝咖啡
        ↓
开始偶尔喝
        ↓
开始研究咖啡机
        ↓
开始自己做咖啡
```

因此：

> “变化过程”本身也是记忆。

这部分对应后续的：

```text
Episode ↔ Episode
Timeline
Causality
Story / Episode Cluster
```



### RMM

主要参考：

- 多粒度记忆；
- 避免把长期对话切成大量固定粒度的碎片；
- 从 utterance / turn / session 等不同层级组织和总结记忆。

Libra 中对应为：

```text
Raw Messages
    ↓
Conversation Segment
    ↓
Episode
    ↓
Episode Cluster / Story
```

因此：

> Episode 不等于单条 Message，也不要求“一句话生成一条记忆”。



### Generative Agents

主要参考经典的：

```text
Memory Stream
→ Retrieval
→ Reflection
→ Planning
```

Libra 当前重点借鉴其中：

```text
Retrieval
Reflection
```

也就是：

- 记忆不仅要存下来；
- 当前需要时要能正确召回；
- 多段经历之间还可以形成更高层理解。

例如：

```text
Episode A
Episode B
Episode C
    ↓
Reflection
    ↓
对近期状态或长期关系形成新的理解
```



### Libra 的新增设计

以下机制不是简单从某一篇论文中原样复制，而是为了陪伴型 Agent 进一步设计。


表示：

> “我们共同经历过什么。”

它与普通用户画像不同。

```text
Semantic Memory
= 我认识的你

Relationship Memory
= 我们之间发生过什么
```



受动态 agent persona 思路启发，但在 Libra 中进一步明确为：

> “这个长期存在的 Libra 自己后来经历过什么。”

```text
Core Persona
稳定人格核心

+

Self Memory
长期经历

=

当前的 Libra
```



用于明确：

```text
记不记？
为什么记？
记成什么类型？
```

从而避免：

- 什么都记；
- 单句话直接形成永久画像；
- 无法解释某条记忆为什么被保存。



在遗忘机制基础上进一步设计：

```text
Active
→ Weak
→ Dormant
```

而不是：

```text
strength 太低
→ DELETE
```

这更符合长期陪伴场景中的“平时想不起来，但遇到线索还能想起”。



```text
MemoryBank
→ 遗忘 / 强化 / 长期保存 / 用户长期认识

LD-Agent
→ Event Perception / Long-term Dialogue Memory
→ Dynamic Persona / Self Memory 启发

THEANINE
→ Timeline / 时间关系 / 因果关系 / 变化过程

RMM
→ 多粒度 Memory / Episode 聚合

Generative Agents
→ Retrieval / Reflection

            ↓

     Libra Memory System

            +

Relationship Memory
Memory Write Policy
Dormant Memory
陪伴型 Agent 的长期关系需求
```



## 2. 系统目标与总体架构

Libra 的长期记忆系统不再等同于“用户画像”或“若干条长期事实”。

新的 Memory System 需要让 Libra 能够：

- 记住真实发生过的经历；
- 从多次经历中逐渐形成对用户的稳定认识；
- 保留关系中的共同经历；
- 保留 Libra 自己经历过的事情；
- 感知用户和关系随时间发生的变化；
- 对记忆进行遗忘、强化、重新激活；
- 在当前对话中召回真正相关的过去经历；
- 将记忆提供给 Appraisal、Emotion、Need 和 Response 系统使用。

核心目标不是：

> “把更多信息存下来。”

而是：

> “让 Libra 拥有可持续、可解释、会变化的长期记忆。”



### 与 Codex Thread 的关系

Codex CLI 当前的 thread / resume 机制继续保留。

V1.1 的历史连续性要求：升级前后继续使用当前主聊天的同一 thread_id，并保留该线程实际使用的 Codex 会话存储和恢复配置。线程号是恢复入口，单独保存号码不能重建丢失的会话内容，也不保证每条旧消息始终进入模型上下文。官方恢复入口见 [Codex CLI](https://learn.chatgpt.com/docs/codex/cli)。

主聊天线程 ID 必须持久化；应用重启后按准确 ID 恢复，不能依靠“最近一个线程”选中后台抽取会话。恢复失败、空回复重试、人格刷新及新记忆库初始化均不得自动替换主线程 ID；恢复失败应保留原 ID 并返回可重试错误。后台抽取使用独立会话，不能覆盖主聊天线程。只有用户明确要求新开或重置主聊天时才允许换号。

本次旧数据保留要求仅为当前 Codex 线程连续性。旧 user_memories / long_term_memories 无需迁移、双写或回退读取；新 Memory DB 从启用时的新 RawExperience 开始积累。旧线程里曾出现的内容仍可能影响对话，但不能未经原始证据校验就当作新 Episode。thread_id 是来源和上下文去重信息；本阶段不建设跨线程历史导入。

两者不是二选一，而是承担不同职责。

```text
Codex Thread
≈ 当前会话 / 工作记忆

Libra Memory System
≈ 长期记忆
```

推荐结构：

```text
                    当前用户消息
                         │
                         ↓
                  Libra Backend
                         │
              ┌──────────┴──────────┐
              ↓                     ↓
       Codex 当前 Thread       Libra Memory DB
       最近聊天上下文           长期记忆
              │                     │
              │              Memory Retrieval
              │                     │
              └──────────┬──────────┘
                         ↓
                   Context Builder
                         ↓
                       Codex
                         ↓
                       Reply
```

原则：

- 当前 thread 已经明确包含的信息，优先依赖当前上下文；
- 跨 session、跨 thread、长时间以前的信息，由 Libra Memory System 负责；
- Libra 自己的 Memory DB 才是长期记忆的 Source of Truth；
- 不依赖 Codex 自身是否还保留某段旧上下文。



### 总体架构

```text
                        USER / WORLD
                             │
                             ↓
                    ┌────────────────┐
                    │ Raw Experience │
                    │ 聊天 / 状态 / 事件 │
                    └───────┬────────┘
                            ↓
                    Memory Perception
                    什么值得形成经历？
                            ↓
                  ┌────────────────────┐
                  │ Episodic Memory    │
                  │ 「发生过什么」      │
                  └─────────┬──────────┘
                            │
              ┌─────────────┼─────────────┐
              ↓             ↓             ↓
            Topic          Time         Causality
              │             │             │
              └─────────────┼─────────────┘
                            ↓
                      Memory Timeline
                            │
                  ┌─────────┴─────────┐
                  ↓                   ↓
            Consolidation         Reflection
                  ↓                   ↓
       ┌──────────┼──────────┐     Insights
       ↓          ↓          ↓
   Semantic   Relationship   Self
    Memory       Memory     Memory
 「认识你」     「我们的故事」 「我的经历」
       │          │          │
       └──────────┼──────────┘
                  ↓
             Memory Bank
                  │
      Decay / Reinforcement / Update
                  │
                  ↓
              Retrieval
                  ↓
      当前相关的过去经历与认识
                  ↓
             Appraisal
                  ↓
       Emotion / Mood / Need
                  ↓
              Response
```


# 第二部分：记忆形成与写入

## 3. 从原始经历到长期记忆

Raw Experience 是记忆系统能够观察到的原始经历来源。

它本身还不是长期记忆。

可能包括：

```text
Chat Message
用户和 Libra 的聊天

UnifiedEvent
来自状态系统、世界事件、提醒等的事件

Libra State
Libra 自己的生活状态与行为

User State
用户状态变化

Relationship Interaction
共同完成、共同讨论、共同经历的事情
```

Raw Experience 的作用是：

> 为后续 Memory Perception 提供原始证据。

原则上应尽量保留原始聊天记录和事件记录，但不代表所有原始内容都会进入长期记忆。




### Episode：经历单元

Episode 是：

> 对一段真实发生过的经历进行整理后形成的长期记忆单元。

它回答的是：

> “发生过什么？”

而不是：

> “用户是什么样的人？”

例如用户说：

```text
“我明天下午考试，有点紧张。”
```

不应该立刻形成：

```text
用户考试前容易紧张。
```

更适合先形成：

```text
Episode：
考试前的聊天

用户说明天下午有考试，
对这件事有些紧张，
并准备继续复习。
```




```text
用户明天下午考试。
```

描述的是一个孤立事实。


```text
今晚用户提到明天下午有考试，
因为这件事有些紧张，
并准备继续复习。
```

描述的是一段经历。

因此：

```text
Fact
= 某件事是什么

Episode
= 某件事是怎样发生的
```



Libra 当前已经有 UnifiedEvent，因此必须和 Episode 清楚区分。

```text
UnifiedEvent
= 当前正在发生、用于实时认知与 Appraisal 的事件

Episode
= 对已经发生的一段经历进行整理后形成的长期记忆
```

例如：

```text
用户：
“我明天下午考试，好紧张。”

        ↓

UnifiedEvent
user_message / exam / nervous
        ↓
Appraisal
        ↓
Emotion / Mood / Need

聊天继续……

        ↓

Episode
“考试前，她因为明天下午的考试感到紧张，
并准备继续复习。”
```

因此：

> Event 是实时认知输入，Episode 是长期记忆产物。



不能：

```text
Message A → Episode
Message B → Episode
Message C → Episode
```

更合理的是：

```text
Messages
   ↓
Conversation Segment
   ↓
Episode
   ↓
Episode Cluster / Story
```

例如连续讨论：

```text
“need 系统不太对。”
“connection baseline 要不要更高？”
“其他 need 是不是也要一起调整？”
```

可以整理成：

```text
Episode：
重新调整 Libra Need System

用户发现当前 need 的恢复逻辑存在问题，
重点讨论了 connection baseline、
随时间回归以及主动联系概率之间的关系，
并开始考虑其他 need 是否也需要统一调整。
```




### Semantic Memory：长期认识

Semantic Memory 表示：

> Libra 在长期相处中逐渐形成的、对用户较稳定的认识。

它回答：

> “我逐渐知道你是什么样的人。”

其中就包括传统意义上的“用户画像”。

例如：

```text
用户喜欢泰奶。
用户喜欢自己做咖啡。
用户很重视表达是否准确。
用户不喜欢模板化安慰。
用户做重要汇报前通常会比较紧张。
```



旧逻辑：

```text
用户说：
“突然好想喝泰奶。”

↓

用户画像：
用户喜欢泰奶。
```

这种方式过于激进。

新的逻辑应该更像：

```text
Episode A
用户主动提到想喝泰奶

Episode B
之后再次主动提到泰奶

Episode C
选择饮品时优先考虑泰奶

        ↓
Consolidation

Semantic Memory
用户对泰奶有较稳定偏好
confidence: 0.82
evidence: [A, B, C]
```

因此 Semantic Memory 应该：

- 有证据来源；
- 有 confidence；
- 可以被新证据增强；
- 可以被新证据修正；
- 可以发生变化；
- 不应永久写死。



Semantic Memory 后续可以进一步组织成 User Model。

第一版建议包含：

```text
preferences
偏好
- 食物
- 饮品
- 音乐
- 兴趣
- 互动偏好

habits
习惯
- 作息
- 工作习惯
- 常见行为模式

goals
长期目标
- 正在推进的项目
- 想完成的事情
- 长期计划

traits / tendencies
稳定倾向
- 表达习惯
- 决策习惯
- 常见应对方式

relationship_preferences
关系与互动偏好
- 喜欢怎样被关心
- 不喜欢怎样被安慰
- 对主动联系的接受方式
```

注意：

> User Model 是长期认识，不是所有用户信息的垃圾桶。



### Memory Perception

Memory Perception 位于 Raw Experience 和 Episode 之间。

它负责判断：

```text
这件事需不需要记？

为什么值得记？

应该记成什么？
```

即：

```text
Raw Chat / Event
      ↓
Memory Perception
      ↓
Memory Write Decision
      ↓
Episode / Ignore / Merge / Update
```




### Memory Write Policy

Memory Write Policy 用来避免 Libra：

- 什么都记；
- 一句话就形成永久用户画像；
- 将无意义闲聊大量写入长期记忆；
- 无法解释为什么记住某件事。

每一次长期记忆写入，都应该能够回答：

> “为什么这件事值得记？”



第一版可以包含：

```text
store_decision
true / false

memory_reasons
结构化原因标签

reason_explanation
自然语言说明

importance
当前重要程度
```

示例：

```json
{
  "store_decision": true,
  "memory_reasons": [
    "future_relevance",
    "emotional_salience",
    "personal_significance"
  ],
  "reason_explanation": "用户提到明天第一次进行正式汇报，并明确表达紧张，具有后续追问价值和较高个人意义。",
  "importance": 0.76
}
```




出现明显偏好线索。

例如：

```text
“这个我特别喜欢。”
“我一直很爱喝泰奶。”
```

可能用于后续 Semantic Memory consolidation。



较重要的个人事实。

例如：

```text
重要身份信息
长期固定安排
具有长期参考价值的背景信息
```

不代表任何个人事实都必须进入长期记忆。



当前信息会在未来继续影响互动。

例如：

```text
明天有考试
下周要汇报
周末准备出去玩
正在等待某件事的结果
```

这类记忆通常具有 follow-up 价值。



该事件具有明显情绪意义。

例如：

```text
第一次重要汇报前很紧张
完成一件期待很久的事情后很开心
某件事情让用户持续烦躁
```



该事件对用户具有明确的个人意义，但不一定表现为强烈情绪。

例如：

```text
第一次独立完成重要工作
做出长期考虑后的决定
达成一个持续投入的阶段性成果
```

它和 `emotional_salience` 可以同时出现，也可以独立出现。



对 Libra 与用户的共同关系具有意义。

例如：

```text
第一次一起做某件事
共同形成的小习惯
重要纪念日
关系中的冲突与修复
```

可能进一步进入 Relationship Memory。



和用户持续推进的目标或项目有关。

例如：

```text
正在开发 Libra
正在准备某项考试
正在做一个长期项目
```

这类内容通常不应被拆成大量独立小记忆，而更适合合并到持续 Episode / Story 中。



表明用户状态、偏好、习惯、目标等发生变化。

例如：

```text
以前不喝咖啡，现在开始经常自己做。
以前很抗拒某件事，现在开始接受。
```

变化本身具有长期记忆价值。



某类信息反复出现，可能已经形成稳定模式。

例如：

```text
多次在重要汇报前表现出类似紧张
多次修改文字时特别关注表达准确性
```

这类信号尤其适合进入 Semantic Memory consolidation。



例如：

```text
“哈哈哈哈”
“我去洗手了”
“嗯嗯”
“好的”
```

通常：

```text
store_decision = false
reason = low_long_term_value
```

但 Memory Write Policy 必须结合上下文。

例如：

```text
“这个按钮好丑。”
```

单独看可能不值得长期记忆。

但如果它处于：

```text
持续数周的 Libra UI 设计 Episode
```

那么它可以作为当前 Episode 的 sub-event，而不一定单独形成新的 Episode。



### 核心写入关系

目前可以先把系统理解成：

```text
Raw Experience
      ↓
Memory Perception
      ↓
Memory Write Policy
      ↓
Episode
      ↓
多次 Episode
      ↓
Consolidation
      ↓
Semantic Memory / User Model
```

其中：

```text
Episode
= 发生过什么

Semantic Memory
= 从这些经历里，我逐渐认识到你是什么样的人
```




## 4. Episode 数据模型

Episode 的数据结构需要同时满足以下要求：

- **可追溯**：每条记忆都能回到原始消息或事件；
- **可修正**：摘要、时间和判断出错时可以更新，而不是生成重复记忆；
- **可演化**：Episode 阶段支持从 ongoing 到 finalized；检索可访问性由独立生命周期进入 weak / dormant；
- **可关联**：可以与其他 Episode、Semantic Memory、Relationship Memory 建立关系；
- **可解释**：能够说明为什么保存、为什么召回，以及哪些内容只是推断；
- **最小必要**：第一版只保留实际会参与写入、更新、检索的字段。

其中最重要的约束是：

> Episode 中的事实、用户原话和系统推断必须能够区分。

下面是 Episode Memory 的聚合读取视图；持久化时公共字段、Episode 专属字段、实体和原始证据分别保存：



```json
{
  "memory_id": "mem_ep_01J...",
  "schema_version": 1,
  "title": "第一次正式汇报前的准备",
  "content": "用户说明天下午将进行第一次正式汇报，感到紧张，今晚准备继续修改材料。",
  "episode_phase": "ongoing",
  "occurred_at": {
    "start": "2026-09-04T21:10:00+08:00",
    "end": null,
    "precision": "minute",
    "timezone": "Asia/Shanghai"
  },
  "participants": ["user", "libra"],
  "topics": ["工作", "正式汇报", "准备"],
  "source_experience_ids": ["rx_01J..."],
  "memory_reasons": [
    "future_relevance",
    "emotional_salience",
    "personal_significance"
  ],
  "salience": {
    "importance": 0.76,
    "emotional": 0.68,
    "relationship": 0.30
  },
  "affect": {
    "user_emotions": ["紧张"],
    "valence": -0.35,
    "arousal": 0.62
  },
  "commitments": [
    {
      "actor": "user",
      "action": "今晚继续修改汇报材料",
      "due_at": "2026-09-04T23:59:59+08:00",
      "commitment_status": "planned"
    }
  ],
  "epistemic": {
    "confidence": 0.92,
    "inferences": []
  },
  "lifecycle": {
    "access_state": "active",
    "strength": 0.76,
    "created_at": "2026-09-04T21:12:00+08:00",
    "updated_at": "2026-09-04T21:12:00+08:00",
    "last_recalled_at": null,
    "recall_count": 0
  },
  "links": []
}
```

### 字段语义与证据边界

这是一份逻辑模型。具体存储时可以拆表，也可以先使用 JSON；字段语义应保持一致。




| 字段 | 必填 | 说明 |
|---|---:|---|
| `memory_id` | 是 | 全局唯一且稳定的 MemoryRecord 标识；更新时不改变。 |
| `schema_version` | 是 | 数据结构版本，用于后续迁移。 |


| 字段 | 必填 | 说明 |
|---|---:|---|
| `title` | 是 | 简短、可浏览的事件标题，不加入未经证实的判断。 |
| `summary` | 是 | 对经历的事实性概括，应包含主体、事件、重要状态和结果。 |
| `topics` | 是 | 多值主题标签，用于聚合和辅助检索；不承担全文语义检索。 |
| `participants` | 是 | 实际参与者，而不是被顺带提到的人。 |

`summary` 应优先回答：

```text
谁，在什么时候，经历或做了什么，为什么重要，目前结果怎样？
```

不要求每条摘要机械地包含全部要素，但不能把推断写成已经发生的事实。


| 字段 | 必填 | 说明 |
|---|---:|---|
| `occurred_at.start` | 是 | 经历开始时间或当前可知的最早时间。 |
| `occurred_at.end` | 否 | 经历结束时间；ongoing 时可以为空。 |
| `occurred_at.precision` | 是 | `exact`、`minute`、`hour`、`day`、`approximate` 或 `unknown`。 |
| `occurred_at.timezone` | 是 | 保留原始时区，避免跨时区后产生错误。 |

`occurred_at` 表示事件发生时间，`lifecycle.created_at` 表示记忆被写入的时间，两者不得混用。

当用户只说“明天下午”时，应结合消息时间解析，同时保存较低的时间精度；无法可靠解析时，不应伪造精确时间。


| 字段 | 必填 | 说明 |
|---|---:|---|
| `source_experience_ids` | 是 | 概念视图；持久化时通过 MemorySource 指向 RawExperience。 |
| `source_type` | 是 | `message`、`event`、`state` 或 `episode`。 |
| `source_id` | 是 | 原始数据的稳定 ID。 |
| `relation` | 是 | `direct_evidence`、`context`、`update` 或 `contradiction`。 |

原则：

- Episode 至少需要一条 `direct_evidence`；
- 原始内容保留在源数据中，Episode 不重复保存大段聊天全文；
- 后续修正或反例追加 MemorySource，不覆盖旧证据；
- 删除原始记录时，需要有明确的数据保留与级联策略。


| 字段 | 范围 | 说明 |
|---|---:|---|
| `memory_reasons` | 枚举数组 | 对应第 8 节的写入原因；至少一项。 |
| `salience.importance` | 0–1 | 对用户未来生活或持续目标的重要程度。 |
| `salience.emotional` | 0–1 | 当下情绪强度与情绪意义。 |
| `salience.relationship` | 0–1 | 对用户与 Libra 共同关系的意义。 |

这三个分数彼此独立，不应压缩为一个模糊的“重要度”。例如，一次轻松但具有纪念意义的互动，可以有较低 emotional、较高 relationship。


`affect` 记录 Episode 中与长期理解有关的情绪线索，而不是完整复制实时 Emotion State。

```text
user_emotions
= 用户明确表达或有充分证据支持的情绪

valence
= 整体正负效价，范围 -1 到 1

arousal
= 唤醒强度，范围 0 到 1
```

如果情绪只是模型推断，应写入 `epistemic.inferences`，并降低 confidence。


`commitments` 用于保存 Episode 内部明确出现、未来可能需要跟进的行动，例如考试、预约、等待结果或约定。

它不是通用 Todo List。只有对后续对话有意义的承诺才应进入这里。

推荐状态：

```text
planned → completed
        → cancelled
        → unknown
```

到期不等于失败。没有得到后续证据时，应标记为 `unknown`，不能擅自推断结果。


```json
{
  "confidence": 0.74,
  "inferences": [
    {
      "claim": "这次汇报对用户具有较高个人意义",
      "confidence": 0.66,
      "basis": ["msg_01J..."]
    }
  ]
}
```

- `confidence` 表示 Episode 整体摘要的可信程度；
- `inferences` 单独存放系统推断；
- 用户直接陈述不等于客观世界已被验证，但可以视为“用户明确表达过”的可靠证据；
- 敏感结论、稳定人格判断不得只凭单个 Episode 固化。


`episode_phase` 表示 Episode 的整理阶段：

```text
candidate
尚在收集证据，不一定写入长期记忆

ongoing
同一经历仍在发展，可以继续合并新内容

finalized
当前阶段已经结束，内容相对稳定
```

内容被替代或确认错误时，分别使用 `record_status = superseded / invalid`，不写入 episode_phase。

`lifecycle.access_state` 表示记忆可用状态：

```text
active → weak → dormant
          ↑        │
          └────────┘
           重新激活
```

两者是不同维度：一个 Episode 可以已经 `finalized`，同时仍处于 `active`。



### 更新、生命周期与有效性

新内容到来时，不应默认创建新 Episode。系统依次判断：

```text
新 Raw Experience
        ↓
是否属于已有 ongoing Episode？
        ├─ 是 → append evidence + 更新摘要
        └─ 否
            ↓
是否在修正或否定已有 Episode？
        ├─ 是 → 添加 update / contradiction 证据并修正
        └─ 否 → 创建 candidate Episode
```

更新时遵循：

1. 保持 `memory_id` 不变；
2. 追加 MemorySource，不丢弃旧证据；
3. 重新生成的摘要不得改变已经确认的事实；
4. 事件发生时间和记忆更新时间分别维护；
5. 重大修正需要留下 revision 记录；
6. 同一事实的措辞变化不应制造重复 Episode。

建议另存简化的 revision log：

```json
{
  "memory_id": "mem_ep_01J...",
  "revision": 3,
  "changed_at": "2026-09-05T19:20:00+08:00",
  "change_type": "result_update",
  "trigger_experience_ids": ["rx_01K..."],
  "previous_revision": 2
}
```



一条 Episode 在进入 `ongoing` 或 `finalized` 前，至少必须满足：

```text
memory_id 非空
title / summary 非空
至少一个 participant
至少一个 direct_evidence
至少一个 memory_reason
occurred_at.start 可用，或明确标记 unknown
confidence 在 0–1 之间
strength 在 0–1 之间
```

同时禁止：

- 没有证据来源的长期记忆；
- 把模型推断伪装成用户原话；
- 使用未来信息回写并假装当时已经知道；
- 仅因一次随口表达就生成稳定人格结论；
- 因为摘要相似就直接覆盖不同时间发生的经历。



为了避免 Episode 逐渐变成所有信息的容器，以下内容先放在其他层：

| 内容 | 所属位置 |
|---|---|
| 原始聊天全文 | Raw Message Store |
| 当前实时情绪数值 | Emotion / Mood State |
| 稳定偏好和长期倾向 | Semantic Memory / User Model |
| 我们关系的长期总结 | Relationship Memory |
| Libra 稳定人格规则 | Core Persona |
| 向量表示 | Retrieval Index，由 Episode 派生 |
| 多个 Episode 的高阶理解 | Reflection |




## 5. Episode 分段与合并

Raw Message 不能直接一条一条变成 Episode，但整场 session 也不能只生成一条过大的记忆。

这一层需要回答：

```text
哪些连续内容属于同一段经历？
新内容应该追加到已有 Episode，还是创建新 Episode？
一段经历什么时候可以认为暂时结束？
结束后再次提起，应该更新旧 Episode，还是建立新的关联 Episode？
```

Libra 使用两层结构处理这个问题：

```text
Raw Experience
      ↓
Conversation Segment
短期、可变的对话片段
      ↓
Episode Candidate
经过记忆价值判断的候选经历
      ↓
Ongoing Episode
仍可继续吸收新证据
      ↓
Finalized Episode
当前阶段已经结束的长期记忆
```



### Segment 模型与连续性

Conversation Segment 是：

> 围绕同一个局部事件、目标或情绪焦点形成的一组连续 Raw Experience。

它是写入 Episode 之前的临时组织单位，本身不一定进入长期记忆。

例如：

```text
用户：明天下午要汇报。
用户：还是第一次正式汇报，有点紧张。
Libra：材料准备到哪一步了？
用户：主体完成了，今晚再改一下结尾。
```

可以形成一个 Segment：

```text
focus: 第一次正式汇报前的准备
source_experience_ids: [rx_1, rx_2, rx_3, rx_4]
segment_state: open
```

如果后续只是转而闲聊晚饭，则结束当前 Segment；但 Segment 是否生成 Episode，仍由 Memory Write Policy 决定。



第一版不需要把 Segment 设计成复杂的永久对象，只需保留实时判断需要的信息：

```json
{
  "segment_id": "seg_01J...",
  "segment_state": "open",
  "focus": "第一次正式汇报前的准备",
  "topic_hints": ["工作", "汇报", "准备"],
  "participant_ids": ["user", "libra"],
  "source_experience_ids": ["rx_01J...", "rx_01K..."],
  "started_at": "2026-09-04T21:10:00+08:00",
  "last_activity_at": "2026-09-04T21:16:00+08:00",
  "candidate_reasons": [
    "future_relevance",
    "emotional_salience",
    "personal_significance"
  ],
  "linked_memory_id": null
}
```

Segment 状态只需要：

```text
open
仍在接收相关内容

closed
边界已经出现，等待或已经完成 Memory Perception

discarded
长期价值不足，不生成 Episode
```

Segment 是工作缓冲区，因此不承担遗忘、强化、召回等长期记忆职责。



每条新 Raw Experience 到来时，计算它与当前 open Segment 的连续性。

第一版建议考虑六类信号：

| 信号 | 含义 | 示例 |
|---|---|---|
| `topic_continuity` | 讨论对象是否一致 | 都在谈明天的汇报 |
| `entity_continuity` | 人、项目、地点或物品是否重合 | 同一个客户、考试或功能模块 |
| `goal_continuity` | 是否服务于同一个目标 | 都在解决汇报准备问题 |
| `temporal_continuity` | 时间距离是否支持连续 | 几分钟内的连续对话 |
| `causal_continuity` | 是否存在原因、结果或后续关系 | “因为紧张，所以继续修改” |
| `referential_continuity` | 是否用代词、省略或承接词指向前文 | “然后呢”“那个结果出来了” |

可以先使用一个可解释的连续性分数：

```text
continuity_score =
    0.25 × topic_continuity
  + 0.20 × entity_continuity
  + 0.20 × goal_continuity
  + 0.15 × temporal_continuity
  + 0.10 × causal_continuity
  + 0.10 × referential_continuity
```

初始决策区间建议为：

```text
score ≥ 0.72
→ append 到当前 Segment

score ≤ 0.42
→ 关闭当前 Segment，创建新 Segment

0.42 < score < 0.72
→ 暂缓边界决定，保留最近上下文继续观察
```

这些权重和阈值只是冷启动参数，后续应根据真实对话样本调优，而不是视为固定真理。



### 边界与写入决策

连续性评分之外，还需要识别边界信号。


出现后通常直接结束当前 Segment：

- 用户明确说“换个话题”；
- 当前任务明确完成或取消；
- 对话主体发生明确切换，且与前文没有因果关系；
- 新内容明确发生在另一段时间、另一场事件中；
- 当前 session 结束并超过 finalize grace period。


只降低连续性，不单独决定切分：

- 短暂无关闲聊；
- 回复间隔较长；
- 出现新的名词或次级话题；
- 情绪发生变化；
- 从讨论问题转为讨论解决方案。

特别注意：

> 时间间隔只能作为信号，不能单独作为 Episode 边界。

用户隔天说“昨天那个汇报结束了”，在消息时间上不连续，但在事件和因果上仍可能属于原 Episode 的结果更新。



Segment 关闭时，进入 Memory Perception：

```text
Closed Segment
      ↓
是否具有长期价值？
      ├─ 否 → discarded
      └─ 是
          ↓
是否属于某个已有 Episode？
      ├─ 是 → merge / update
      └─ 否 → new Episode Candidate
                    ↓
             校验最低有效性约束
                    ↓
             Ongoing / Finalized Episode
```

Memory Write Policy 的输出在这一层增加：

```json
{
  "store_decision": true,
  "operation": "create",
  "target_memory_id": null,
  "memory_reasons": ["future_relevance"],
  "confidence": 0.88,
  "explanation": "该片段描述了明天将发生的重要事件，具有明确的后续追问价值。"
}
```

`operation` 第一版包含：

```text
ignore
长期价值不足

create
创建新的 Episode

append
向 ongoing Episode 追加同一阶段的信息

update
补充结果、纠正内容或改变已有状态

link
创建新 Episode，并与旧 Episode 建立关系
```



### Merge、Finalize 与特殊情况

判断 Segment 是否属于已有 Episode 时，不应在整个数据库中盲目比较。先生成候选集合：

```text
最近的 ongoing Episodes
+ 时间窗口内的相关 finalized Episodes
+ 语义检索得到的高相关 Episodes
+ commitments 到期或等待结果的 Episodes
```

再对每个候选 Episode 计算 merge score：

```text
merge_score =
    0.25 × event_identity
  + 0.20 × entity_overlap
  + 0.20 × goal_overlap
  + 0.15 × temporal_fit
  + 0.10 × causal_fit
  + 0.10 × participant_overlap
```

其中 `event_identity` 判断的是“是否在谈同一次具体事件”，权重最高。

初始决策建议：

```text
score ≥ 0.78
→ append 或 update 已有 Episode

score ≤ 0.48
→ 创建新 Episode

0.48 < score < 0.78
→ 优先 link，不强行 merge
```

低置信度时，宁可保留两个可关联的 Episode，也不要错误合并。错误拆分之后还能聚合，错误合并则容易破坏事实边界。




同一事件、同一阶段、内容继续发展：

```text
“明天下午第一次正式汇报。”
+
“今晚还要修改材料。”
→ append
```


同一事件出现结果、纠正或状态变化：

```text
“汇报结束了，比预想顺利。”
→ update 原 Episode 的结果与 commitment 状态
```


事件相关，但各自具有独立时间和意义：

```text
Episode A：第一次正式汇报
Episode B：一个月后的第二次汇报

关系：B follows A
主题和变化过程相关，但不是同一次事件
```

不得仅因为标题、人物或主题相似就 Merge。例如，多次考试、多次就医、多次争执都应先判断是否为同一次具体事件。



Episode 不应在每次暂时停聊后立刻 finalized。第一版采用“事件完成信号 + 宽限期”的组合。

可以 finalized 的条件：

- 用户明确说明事件已经结束；
- commitment 已获得 completed / cancelled 证据；
- 对话中出现明确结果；
- 已出现强边界，且宽限期内没有新的相关内容；
- session 结束后，事件本身不再等待自然后续。

应继续保持 ongoing 的情况：

- 等待考试、汇报、预约等即将发生的事件；
- 等待结果、回复或决定；
- 持续推进中的项目阶段；
- 用户明确表示稍后继续讨论。

推荐将 finalize grace period 按 Episode 类型配置，而不是统一为固定小时数：

| 类型 | 初始宽限策略 |
|---|---|
| 普通话题讨论 | session 结束后短宽限期 |
| 当日事件 | 当日结束或结果出现后 |
| 有明确 due time 的事件 | due time 后等待结果窗口 |
| 长期项目 | 阶段完成、目标改变或长期无更新时 |
| 关系事件 | 语义完成信号优先，不按短时间自动结束 |

Finalize 不是冻结。后续出现新证据时，仍然可以 `update`，或创建新 Episode 后 `link`。




例如：

```text
“汇报结束了，挺顺利；不过我回家路上把伞丢了。”
```

允许同一个 `source_ref` 同时进入两个 Segment：

```text
Segment A → 汇报结果
Segment B → 丢伞事件
```

不能为了保持“一条消息对应一个 Segment”而错误合并。


如果中间只是低信息量插话，可以恢复之前仍 open 的 Segment。第一版建议同时保留少量 open Segment 候选，而不是永远只有一个。

为控制复杂度：

```text
active open segments ≤ 3
```

超过数量后，优先关闭最久未活动且连续性最低的 Segment。


先检索具有未完成 commitment 或相同 event identity 的 Episode。若确认是同一次事件，执行 `update`；否则创建新 Episode 并建立时间或因果关系。


用户明确纠正时：

1. 原始错误证据保留；
2. 新证据标记为 `contradiction` 或 `update`；
3. 修正 Episode 摘要和 confidence；
4. revision log 记录变更；
5. 如果错误来自系统归因，应降低相关推断规则的可信度。


长期项目不应形成一个无限增长的 Episode。

应按具有独立结果的阶段切分：

```text
Story / Project Cluster：开发 Libra Memory System
    ├─ Episode：确定总体记忆架构
    ├─ Episode：设计 Episode 数据模型
    └─ Episode：确定 Segment / Merge 规则
```



```text
1. 接收 Raw Experience
2. 与最近 open Segments 比较连续性
3. append 到最佳 Segment，或创建新 Segment
4. 遇到边界时关闭 Segment
5. Memory Perception 判断 ignore / create / append / update / link
6. 对候选 Episode 计算 merge score
7. 执行操作并追加 MemorySource
8. 重新生成事实性 summary
9. 更新 status、commitments、confidence 与 revision
10. 在完成信号和宽限策略满足后 finalized
```

每次决策至少记录：

```text
chosen_operation
target_memory_id
score_breakdown
decision_confidence
decision_explanation
```

这样后续发现切分错误时，才能定位是主题判断、时间判断还是事件身份判断出了问题。



使用真实或构造对话测试时，至少覆盖：

- 连续多轮讨论同一件事，最终只形成一个 Episode；
- 同一场对话自然切换话题，能够形成不同 Segment；
- 闲聊插话不会轻易切断主要 Episode；
- 一条消息内的两个独立事件可以拆开；
- 隔天汇报结果能够更新原 Episode；
- 同主题但不同时间发生的事件不会错误合并；
- 用户纠正信息后，旧错误不会继续参与正常召回；
- 长期项目可以形成多个 Episode，并由 Story / Cluster 组织；
- 低价值 Segment 可以 discarded，不污染长期记忆；
- 每一次 create / merge / update 都可以解释并回溯到证据。


# 第三部分：记忆组织与演化



## 6. Timeline、Link 与 Story

Episode 只能回答“发生过什么”，但长期陪伴还需要回答：

```text
事情以什么顺序发生？
前后两件事是否属于同一段发展过程？
用户的状态、偏好或目标是怎样变化的？
当前事件是过去哪件事的继续、结果或转折？
```

因此，Libra 不把 Timeline 理解成简单的时间排序，而是三层结构：

```text
Episode
单次经历

Episode Link
经历之间的时间、因果、延续或修正关系

Story / Episode Cluster
围绕同一长期主题形成的阶段性故事
```

例如：

```text
Story：逐渐开始自己做咖啡

Episode A：以前很少喝咖啡
    ↓ transition_to
Episode B：开始偶尔购买咖啡
    ↓ leads_to
Episode C：研究咖啡机
    ↓ followed_by
Episode D：第一次在家做咖啡
```

这里真正有价值的不是“用户喜欢咖啡”这一条结论，而是偏好和行为形成的过程。



### Episode Link 与关系可信度

Episode 之间的关系单独建模，不把关系只写进自然语言摘要。

```json
{
  "link_id": "lnk_01J...",
  "source_episode_memory_id": "mem_ep_A",
  "target_episode_memory_id": "mem_ep_B",
  "relation_type": "leads_to",
  "direction": "directed",
  "confidence": 0.78,
  "evidence_memory_ids": ["mem_ep_A", "mem_ep_B"],
  "inference_level": "supported_inference",
  "created_at": "2026-09-05T20:10:00+08:00",
  "updated_at": "2026-09-05T20:10:00+08:00",
  "link_status": "active"
}
```

原则：

- Link 必须指向两个已经存在的 Episode；
- 关系本身也需要 evidence 和 confidence；
- 原始 Episode 不因建立 Link 而被重写；
- 同一对 Episode 可以存在不同维度的关系；
- 无效或被纠正的 Link 标记为 `invalid`，不直接物理删除。



第一版将关系分成四组，避免把所有联系都模糊地称为 related。


```text
before
发生在另一 Episode 之前

after
发生在另一 Episode 之后

overlaps
两个 Episode 的发生时间有重叠

during
一个 Episode 发生在另一个持续 Episode 内部
```

明确时间戳能够直接推导出的 `before / after` 通常不需要全部永久存储，可以在查询时计算。只有时间精度模糊、关系由用户明确表达，或该顺序具有叙事意义时才保存 Link。


```text
continuation_of
同一事项在另一个阶段继续发展

result_of
当前 Episode 是前一 Episode 的结果

transition_from
状态从前一阶段转变到当前阶段

reopens
已经结束的话题或事件再次被开启
```


```text
caused_by
有直接证据表明由另一 Episode 导致

enabled_by
另一 Episode 提供了条件，但不是充分原因

blocked_by
另一 Episode 阻碍了目标或进展

resolved_by
另一 Episode 解决了本 Episode 中的问题
```


```text
supports
为已有理解提供新证据

contradicts
与另一 Episode 中的陈述或推断冲突

clarifies
补充限定条件，使旧内容更准确

supersedes
用更准确的记录替代旧记录
```

关系命名统一以 `source_episode → target_episode` 的方向解释。实现时必须为每个枚举写清方向，避免出现 `result_of` 究竟指向原因还是结果的歧义。



时间和因果关系不能全部由语言模型自由补全。每条 Link 标注推断等级：

```text
explicit
用户或可靠事件源明确说明

derived
可以从结构化时间、状态或 ID 确定性推导

supported_inference
有多项线索支持，但不是明确陈述

speculative
仅存在弱相关，不进入正常长期关系图
```

建议的最低 confidence：

| 推断等级 | 最低 confidence | 正常召回时是否使用 |
|---|---:|---:|
| `explicit` | 0.90 | 是 |
| `derived` | 0.95 | 是 |
| `supported_inference` | 0.65 | 是，但应保留不确定性 |
| `speculative` | 不设 | 否，仅供重新评估 |

因果关系比主题关系风险更高。没有明确因果表达或充分证据时，应使用 `continuation_of`、`supports` 等较弱关系，而不是 `caused_by`。



### Story 的模型与生命周期

Story 是：

> 围绕同一个持续主题、目标、关系过程或个人变化，由多个 Episode 组成的长期叙事单元。

它不是把相似 Episode 简单装进一个文件夹，而是保留：

- 这段故事的主题；
- 当前处于什么阶段；
- 哪些 Episode 是关键节点；
- 发生过哪些转折；
- 是否仍在继续；
- 当前能够得出什么有限结论。

适合形成 Story 的内容：

```text
长期项目
持续学习或备考
健康状态变化
兴趣与习惯形成
重要关系的发展
反复出现并逐步变化的问题
```

不适合形成 Story 的内容：

```text
只有一次、没有后续意义的普通事件
仅仅主题词相同但彼此无关的经历
为了减少 Episode 数量而强行聚合的内容
```



下面是便于理解的聚合读取视图；实际持久化时按 MemoryRecord、StoryDetail、StoryMember、OpenLoop 分表保存：

```json
{
  "memory_id": "mem_story_01J...",
  "schema_version": 1,
  "title": "逐渐开始自己做咖啡",
  "content": "用户从很少喝咖啡，逐渐开始购买、研究设备，并尝试在家制作。",
  "memory_subtype": "personal_change",
  "story_phase": "active",
  "episode_memory_ids": ["mem_ep_A", "mem_ep_B", "mem_ep_C", "mem_ep_D"],
  "key_episode_memory_ids": ["mem_ep_A", "mem_ep_C", "mem_ep_D"],
  "current_stage": "开始形成家庭制作习惯",
  "time_span": {
    "start": "2026-03-01T00:00:00+08:00",
    "end": null,
    "precision": "approximate"
  },
  "topics": ["咖啡", "饮品偏好", "生活习惯"],
  "participant_ids": ["user"],
  "turning_points": [
    {
      "episode_memory_id": "mem_ep_C",
      "description": "从偶尔购买转为主动研究制作设备"
    }
  ],
  "open_loops": [],
  "confidence": 0.84,
  "created_at": "2026-09-05T20:20:00+08:00",
  "updated_at": "2026-09-05T20:20:00+08:00"
}
```

Story 的 `memory_subtype` 第一版建议包含：

```text
project
长期项目或工作

goal_pursuit
为某个目标持续采取行动

personal_change
偏好、习惯、能力或状态变化

relationship_process
用户与 Libra 的共同关系经历

recurring_pattern
重复出现并具有发展过程的事件
```



Story 不应在第一次出现某个主题时就创建。

满足以下任一条件后，才进入 Story Candidate：

- 至少两个 Episode 存在明确 continuation / result / transition 关系；
- 同一长期 goal 或 project 出现新的独立阶段；
- 用户明确把当前事件描述为过去经历的继续；
- Reflection 发现多个 Episode 构成具有解释价值的变化过程。

处理流程：

```text
新建或更新 Episode
        ↓
检索可能相关的 Stories
        ↓
比较主题、目标、实体、时间与关系
        ↓
append_to_story / create_story / no_story
        ↓
更新阶段、关键节点、转折与 open loops
        ↓
必要时重新生成 Story summary
```

同一个 Episode 可以属于多个 Story。例如，“第一次公开汇报”既可以属于工作项目 Story，也可以属于“逐渐适应公开表达”的 personal_change Story。

但第一版应设置限制，避免无意义的过度归类：

```text
每个 Episode 默认 active Story 数量 ≤ 3
```

超过限制时，只保留对当前长期理解最有价值的 Story 归属，其余作为普通 Link。



`current_stage` 是对当前阶段的描述，不是不可修改的事实标签。

Story 状态建议为：

```text
candidate
关系已出现，但尚不足以形成稳定故事

active
仍在发展，可能继续加入 Episode

paused
暂时没有进展，但目标或过程没有明确结束

completed
目标达成或过程明确结束

abandoned
目标被明确放弃
```

Story 被替代或错误聚合时，使用 `record_status = superseded / invalid`。

不得仅因长时间没有新消息就把 Story 标记为 completed。时间衰减可以降低活跃度，但结束状态需要事件证据。



### 状态变化、Open Loop 与 Timeline View

变化过程不能只保留最终值。建议使用：

```text
Episode evidence
      ↓
State Observation
      ↓
Transition
      ↓
Current Understanding
```

例如：

```json
{
  "dimension": "coffee_habit",
  "from": "rarely_drinks",
  "to": "makes_at_home",
  "transition_episode_memory_ids": ["mem_ep_B", "mem_ep_C", "mem_ep_D"],
  "confidence": 0.82
}
```

这里的 `from` 和 `to` 是对证据的结构化概括，不替代原 Episode。

需要区分：

```text
temporary_state
短期状态，例如“这周很累”

developing_pattern
正在形成的模式，例如“最近开始规律运动”

stable_change
经过持续证据支持的长期变化
```

只有 stable_change 才适合进一步更新 Semantic Memory；temporary_state 主要用于近期 Timeline 和 Retrieval。



Story 可以维护尚未得到结果、未来值得自然跟进的事项：

```json
{
  "open_loop_id": "loop_01J...",
  "description": "等待用户第一次正式汇报的结果",
  "source_episode_memory_id": "mem_ep_01J...",
  "expected_after": "2026-09-05T17:00:00+08:00",
  "loop_status": "open",
  "priority": 0.72
}
```

Open Loop 与 reminder 不同：

```text
Open Loop
= 记忆系统知道这件事还没有结果

Reminder
= 系统被要求在某个时间主动执行提醒
```

Open Loop 只能影响后续召回和自然追问，不能自动产生外部提醒行为。

关闭条件：

- 获得结果；
- 用户明确取消或不愿再谈；
- 原始 Episode 被判定无效；
- 长期无结果后降为 stale，但不能擅自标记 completed。



Timeline 是 Episode 与 Link 的查询结果，不必额外复制一份完整事实数据。

生成流程：

```text
选择用户、主题或 Story
        ↓
读取相关 Episodes
        ↓
按 occurred_at 和时间精度建立顺序
        ↓
加入显式或高置信度 Links
        ↓
标注时间不确定性与缺失阶段
        ↓
生成面向当前任务的 Timeline View
```

当两个 Episode 的时间精度不足以确定顺序时，应显示为：

```text
顺序未知 / 可能重叠
```

不能为了叙事流畅而强行排序。

Timeline View 可以按场景裁剪：

- 给 Retrieval：返回少量相关节点与相邻关系；
- 给 Reflection：返回完整阶段和转折；
- 给用户展示：返回可读的时间线与证据说明；
- 给 Response：只返回当前回复真正需要的过去信息。



Story 不等于 Semantic Memory。

```text
Story
= 用户经历如何发展

Semantic Memory
= 从多段证据中形成的当前稳定认识
```

例如：

```text
Story：从很少喝咖啡到开始在家制作
        ↓ Consolidation
Semantic Memory：用户目前对自己做咖啡有较稳定兴趣
```

当 Story 后续出现反向变化：

```text
不再使用咖啡机
→ 最近主动减少咖啡因
→ 长期改喝无咖啡因饮品
```

系统应该：

1. 保留原来的 Story 历史；
2. 添加新的 transition Episode；
3. 更新 Story current stage；
4. 降低或修改旧 Semantic Memory 的 confidence；
5. 不把“曾经喜欢”和“现在减少”视为互相删除。



### 图约束与验收

Episode Link 和 Story 构成轻量关系图，需要满足：

- Link 不允许指向自身；
- `before / after` 必须与可靠时间信息一致；
- 高置信度直接因果图不应形成循环；
- `supersedes` 只能指向更旧的记录；
- invalid Episode 不参与正常 Story summary；
- Story 删除成员时保留变更记录；
- 自动推断的 Link 必须允许重新评估和降级；
- 图遍历必须限制深度和节点数量，避免召回无限扩散。

如果检测到冲突：

```text
保留原始 Episode
→ 暂停冲突 Link 的正常使用
→ 标记 requires_review
→ 等待新证据或重新推断
```



```text
1. Episode create / update / finalize
2. 提取候选时间、发展、因果和修正关系
3. 为每个关系保存 evidence、confidence、inference_level
4. 过滤 speculative 与冲突 Link
5. 检索可能相关的 Story
6. append_to_story / create_story / no_story
7. 更新 current_stage、turning_points 与 open_loops
8. 检测图关系冲突
9. 根据需要生成 Timeline View
10. 将稳定变化候选交给 Consolidation，而不是直接改写 User Model
```



第一版至少覆盖：

- 能正确排列时间明确的 Episodes；
- 时间信息模糊时不会伪造顺序；
- 同一事件的准备、发生和结果能够形成发展链；
- 主题相似但没有发展关系的 Episodes 不会被强行组成 Story；
- 因果关系能区分明确陈述与模型推断；
- 一个 Episode 可以合理属于多个 Story，但不会无限归类；
- 长期项目能够按阶段形成 Story，而不是无限增长的单一 Episode；
- Story 暂停不会被误判为完成；
- Open Loop 得到结果后可以正确关闭；
- 用户偏好变化时能够保留“以前—转变—现在”的过程；
- 无效 Episode 和 speculative Link 不参与正常召回；
- 所有 Timeline 结论都能回溯到 Episode 和原始证据。




## 7. 遗忘、强化与重新激活

遗忘机制的目标不是模拟一个会随机丢失事实的人脑，而是：

- 降低陈旧、低价值记忆对正常召回的干扰；
- 保留长期关系中“平时想不起来，但遇到线索还能想起”的体验；
- 让真正重要、反复相关的经历更容易被召回；
- 控制 Context Builder 的噪声和长期存储增长；
- 保证所有强弱变化可以解释和纠正。

因此：

```text
Forgetting
≠ 删除原始数据

Forgetting
= 降低默认可访问性
```

真正的数据删除属于独立的 Privacy / Retention Policy，不能由 strength 衰减自动触发。




表示记忆当前的默认可访问层级：

```text
active
正常参与候选检索

weak
降低检索优先级，只在相关性较高时进入候选

dormant
不参与普通检索，只响应强线索、显式回忆或关系图激活
```


表示当前访问强度，范围为 0–1。

Strength 影响状态转换和 Recall Score，但不是记忆重要性、可信度或真实程度的替代品。

```text
strength
≠ importance
≠ confidence
≠ emotional_salience
```

例如，一条发生很久但非常重要的记忆可以 strength 较低、importance 很高；一条经常被提起的普通习惯可以 strength 较高、importance 较低。



### Strength、衰减与保护下限

第一版将 strength 视为可更新状态，而不是每次从所有字段临时计算。更新时参考：

```text
base_strength
写入时的初始强度

time_decay
距离上次有效接触后的衰减

reinforcement
新证据、主动回忆或重要复现带来的增强

protection_floor
因重要性、关系意义或未完成事项而保留的最低强度
```

Episode 创建时可以使用：

```text
base_strength =
    0.45 × importance
  + 0.25 × emotional_salience
  + 0.20 × relationship_significance
  + 0.10 × confidence
```

并限制在：

```text
0.20 ≤ base_strength ≤ 0.95
```

这是冷启动公式。长期应根据召回效果、误召回和用户反馈调参。



建议使用带最低保护值的半衰期模型：

```text
decayed_strength(t) =
  floor + (previous_strength - floor) × 2 ^ (-elapsed_days / half_life_days)
```

其中：

```text
floor
= 当前记忆允许衰减到的最低强度

half_life_days
= 当前类型记忆强度减半所需时间
```

初始半衰期不应一刀切：

| Episode 特征 | 半衰期倾向 |
|---|---|
| 普通、低重要度闲聊 | 较短 |
| 有明确 future relevance | 到期前暂停明显衰减 |
| 长期项目的关键节点 | 较长 |
| 高 relationship significance | 较长 |
| 高情绪意义但无后续价值 | 中等 |
| 已被 Story / Reflection 使用 | 较长，但不永久锁定 |

第一版可以从以下范围开始实验：

```text
short:   7–14 days
medium:  30–60 days
long:    120–365 days
```

具体数值应通过离线回放评估，而不是仅凭直觉固定。



某些记忆即使长时间没有被提及，也不应快速跌入 Dormant。

建议计算保护下限：

```text
protection_floor = max(
  importance_floor,
  relationship_floor,
  commitment_floor,
  user_pinned_floor
)
```

初始语义：

| 来源 | 作用 |
|---|---|
| `importance_floor` | 对人生、健康、长期目标有持续意义 |
| `relationship_floor` | 对共同关系具有纪念或身份意义 |
| `commitment_floor` | 仍有未完成结果或值得跟进的事项 |
| `user_pinned_floor` | 用户明确要求记住 |

保护不等于每次对话都主动提起。它只防止记忆因时间自然衰减到不可访问。

用户明确要求“忘掉”某件事时，不能仅把 strength 设低；应进入 Privacy / Retention 的删除或隔离流程。



### 状态转换与 Reinforcement

第一版建议使用带迟滞区间的阈值，避免 strength 在边界附近反复跳动：

```text
active → weak
strength < 0.42，且连续两个评估周期成立

weak → active
strength ≥ 0.55，或发生高质量 reinforcement

weak → dormant
strength < 0.18，且没有保护条件与 open loop

dormant → weak
强线索匹配或新证据使 strength ≥ 0.30

dormant → active
用户显式回忆、同一事件重新发生，且更新后 strength ≥ 0.55
```

阈值间保留间隔，形成 hysteresis：

```text
降级阈值 < 升级阈值
```

状态转换记录：

```json
{
  "memory_id": "mem_ep_01J...",
  "previous_access_state": "weak",
  "new_access_state": "active",
  "changed_at": "2026-10-12T20:00:00+08:00",
  "reason": "user_explicit_recall",
  "trigger_experience_ids": ["rx_01M..."],
  "strength_before": 0.24,
  "strength_after": 0.61
}
```



并非每次被检索出来都应该增强记忆。否则系统自己反复召回一条记忆，就会造成自我强化循环。

有效 reinforcement 包含：

```text
new_evidence
出现新的、独立的支持证据

user_explicit_recall
用户主动提起或确认过去经历

meaningful_recurrence
同类事件再次发生，并形成新的 Episode 或 Pattern

outcome_update
等待中的事件获得结果

relationship_reuse
共同经历在新的关系语境中再次具有明确意义

user_correction
用户纠正后增强修正版本，而不是增强旧错误
```

不应 reinforcement：

- 仅仅进入检索候选但没有用于回复；
- 系统自己生成摘要时读取该记忆；
- 同一次请求中的重复检索；
- 因检索排名高而再次被选中的循环；
- 用户没有确认的模型猜测。



建议使用递减收益，避免 strength 很快永久饱和：

```text
new_strength = current_strength
             + gain × (1 - current_strength)
```

初始 gain 建议：

| 事件 | gain 范围 |
|---|---:|
| 用户明确回忆并补充细节 | 0.25–0.40 |
| 新的独立证据 | 0.15–0.30 |
| 等待事项得到结果 | 0.15–0.25 |
| 普通有意义复现 | 0.08–0.18 |
| 仅在回复中被自然使用 | 0.02–0.06 |

还需要两个限制：

```text
same_source_cooldown
同一来源在冷却期内只增强一次

evidence_diversity
不同时间、不同情境的证据比同一段对话里的重复表达更有价值
```



### Dormant Memory 与 Reactivation

Dormant Memory 默认不进入普通向量检索结果，但可以通过以下路径重新进入候选：

```text
用户显式要求回忆
“你还记得我们第一次……吗？”

高特异性线索
罕见人名、地点、纪念日、独特短语

Story 邻接激活
当前 Episode 与某个 Story 的关键旧节点高度相关

关系或因果链回溯
理解当前事件必须读取过去原因或转折

新证据直接引用旧事件
“上次那件事现在有结果了”
```

Dormant 检索采用更严格条件：

```text
high semantic specificity
+ entity / event identity match
+ source or timeline support
```

仅有宽泛主题相似，例如都与“工作”有关，不足以激活 Dormant Memory。



Reactivation 不等于简单恢复旧 strength。系统需要先判断：

```text
当前线索是否确实指向同一次经历？
旧摘要是否仍然准确？
是否出现了新的阶段或结果？
应该 update 旧 Episode，还是创建新 Episode 并 link？
```

流程：

```text
Dormant candidate
      ↓
event identity / evidence 校验
      ├─ 不匹配 → 不激活
      └─ 匹配
          ↓
append / update / link
          ↓
计算 reinforcement
          ↓
weak / active
```

如果新信息否定旧记忆，应更新或标记 contradiction，而不是因为“被再次提到”就增强错误版本。



### 分类型维护、审计与验收

第一版不能对所有对象使用相同规则：


按事件本身的 recency、importance、relationship significance 和后续价值衰减。


活跃度可以衰减，但历史成员不因此消失。新的 Episode 可以重新激活 Story。


confidence 随支持证据的时效和反例变化，不直接复用 Episode strength。稳定偏好应通过证据更新，而不是单纯按天遗忘。


较高保护下限，但仍需要区分当前相关性与历史意义。


涉及 Libra 自身连续性的关键经历应有较高保护下限；普通运行细节不应进入 Self Memory。



不需要持续扫描所有记忆。采用事件驱动与定期批处理结合：

```text
on_retrieval
读取时按 elapsed time 计算当前有效 strength

on_update
追加证据或结果时立即计算 reinforcement

daily / periodic maintenance
批量更新即将跨状态阈值的记忆

on_story_change
Story 状态改变时重新评估关键 Episode 的保护下限
```

为避免同一时刻不同任务得到不同结果，strength 的更新应具有幂等性，并记录 `last_decay_evaluated_at`。



每次强度变化至少保存：

```text
strength_event_id
memory_id
previous_strength
new_strength
previous_access_state
new_access_state
operation: decay / reinforcement / reactivation / protection_change
reason
trigger_experience_ids
idempotency_key
created_at
formula_version
```

示例：

```json
{
  "strength_event_id": "mse_01J...",
  "memory_id": "mem_ep_01J...",
  "previous_strength": 0.38,
  "new_strength": 0.57,
  "previous_access_state": "weak",
  "new_access_state": "active",
  "operation": "reinforcement",
  "reason": "user_explicit_recall",
  "trigger_experience_ids": ["rx_01N..."],
  "idempotency_key": "reinforce:mem_ep_01J:rx_01N",
  "created_at": "2026-10-12T12:05:00Z",
  "formula_version": "strength_v1"
}
```



Strength 只应作为 Recall Score 的一部分：

```text
高相关 + 低 strength
可能仍值得召回

低相关 + 高 strength
不应该因为记得牢就被塞进当前上下文
```

因此：

```text
strength 决定“多容易进入候选”
relevance 决定“当前是否应该被使用”
```

Dormant 是候选生成层的限制，不代表永远不可访问。



```text
1. Episode 写入时计算 base_strength 与 protection_floor
2. 根据 Episode 特征选择 half_life
3. 读取或维护时计算 decayed_strength
4. 应用 protection_floor
5. 使用迟滞阈值判断 access_state
6. 新证据出现时判断是否为有效 reinforcement
7. 使用递减收益更新 strength
8. Dormant 命中时先验证 event identity
9. 记录所有强度与状态变化
10. 将候选状态提供给 Retrieval，不自动删除数据
```



第一版至少覆盖：

- 普通低价值 Episode 会随时间从 active 降为 weak；
- Dormant Memory 不参与普通宽泛检索；
- 高特异性线索可以重新激活正确的 Dormant Memory；
- 系统内部反复检索不会造成自我强化循环；
- 同一来源重复出现不会在冷却期内多次增强；
- 新的独立证据比同一段对话的重复表达增强更多；
- 未完成 commitment 不会在到期前意外进入 dormant；
- 高关系意义记忆具有保护下限，但不会被无关对话频繁召回；
- strength 边界附近不会频繁切换 active / weak；
- 用户纠正旧记忆时，增强的是修正版本；
- 用户要求删除时进入独立删除流程，而不是仅设为 dormant；
- 每次 decay、reinforcement 和 reactivation 都可解释、可回放。




Libra 需要明确区分：

```text
Semantic Memory / User Model
= 我逐渐知道你是什么样的人

Relationship Memory
= 我们之间真实发生过什么，以及形成了哪些共同模式

Self Memory
= 作为持续存在的 Libra，我在与你相处中经历和做过什么
```

三者可以引用同一个 Episode，但不能互相替代。

例如：

```text
Episode
用户在汇报前来找 Libra 一起修改材料

Semantic Memory
用户很重视正式表达的准确性

Relationship Memory
我们逐渐形成了重要汇报前一起检查材料的习惯

Self Memory
我曾陪用户准备第一次正式汇报，并帮助检查结尾
```



## 8. Relationship Memory 与 Self Memory

### Relationship Memory

Relationship Memory 表示：

> 用户与 Libra 共同参与、对双方后续互动具有持续意义的经历、约定、边界和关系模式。

它不等于：

- 把所有双人对话都标为“共同经历”；
- Libra 对关系的单方面想象；
- 用亲密措辞推断用户已经同意某种关系定义；
- 将用户信息换成“我们的”说法再存一遍。

只有存在双方互动证据或用户明确表达时，才可以形成 Relationship Memory。



```text
shared_milestone
具有阶段意义的共同经历

shared_project
双方持续参与的项目或目标

ritual
反复形成、具有稳定意义的互动习惯

agreement
双方明确达成的约定

interaction_preference
用户明确或多次表现出的相处偏好

boundary
用户表达的不希望被怎样对待或谈论

conflict_and_repair
关系中的不适、纠正以及后续修复

shared_reference
双方共同理解的称呼、梗、地点或过去事件
```

其中 `boundary` 的优先级高于 ritual 和普通 interaction preference。召回共同习惯时，必须先检查它是否与用户较新的边界冲突。



下面是 Relationship Memory 的聚合读取视图；持久化时公共字段、关系专属字段与证据依赖分别保存：

```json
{
  "memory_id": "mem_rel_01J...",
  "schema_version": 1,
  "memory_subtype": "ritual",
  "title": "重要汇报前一起检查材料",
  "content": "用户在重要汇报前通常愿意和 Libra 一起检查表达与结构。",
  "relationship_applicability": "active",
  "participant_ids": ["user", "libra"],
  "evidence_memory_ids": ["mem_ep_A", "mem_ep_B", "mem_ep_C"],
  "first_observed_at": "2026-04-12T20:00:00+08:00",
  "last_confirmed_at": "2026-09-04T21:30:00+08:00",
  "confidence": 0.84,
  "salience": 0.72,
  "mutuality": "behaviorally_supported",
  "created_at": "2026-09-05T20:20:00+08:00",
  "updated_at": "2026-09-05T20:20:00+08:00"
}
```

`mutuality` 用来说明“共同性”的证据程度：

```text
explicitly_mutual
双方或用户明确确认

behaviorally_supported
多次真实互动支持，但没有明确命名

agent_observed
主要是 Libra 的观察，不能当作双方共识表达
```

`agent_observed` 可以帮助内部判断，但回复时不能说成“我们一直都……”，除非用户确认或行为证据足够稳定。



不能因为单个 Episode 带有 `relationship_significance` 就立即生成长期关系结论。

第一版形成路径：

```text
Relationship-significant Episodes
        ↓
按共享目标、互动方式和时间关系聚合
        ↓
检查是否存在 mutual evidence
        ↓
Relationship Memory Candidate
        ↓
confirm / strengthen / revise / reject
```

可以直接形成 Candidate 的情况：

- 用户明确约定未来的相处方式；
- 用户明确表达边界；
- 共同完成具有明显纪念意义的事件；
- 用户明确将某件事称为“我们之间”的经历。

需要多次证据的情况：

- 互动习惯；
- 陪伴偏好；
- 常用的安慰或协作方式；
- 对关系状态的抽象判断。



Relationship Memory 的 `relationship_applicability` 允许变化：

```text
active
当前仍适用

uncertain
出现反例或长期未确认

historical
曾经真实存在，但当前不再适用
```

派生记忆被替代或确认错误时，使用 `record_status = superseded / invalid`。

当用户表达新边界时：

1. 新 boundary 立即进入高优先级候选；
2. 查找与它冲突的 ritual、preference 和 agreement；
3. 冲突项改为 uncertain 或 superseded；
4. 后续 Response 优先遵循新边界；
5. 旧经历仍可作为历史保留，但不能作为当前行为依据。

关系记忆不能覆盖用户当前明确表达。无论历史 confidence 多高，当前的“不要这样称呼我”都具有更高行为优先级。



Relationship Memory 适合在以下情况进入候选：

- 当前话题直接延续共同项目或约定；
- 用户提到共同经历、共享称呼或过去节点；
- 当前互动需要遵循已确认的 preference 或 boundary；
- 某个重要日期或结果与共同 Story 直接相关；
- 理解当前关系变化需要读取过去的冲突或修复过程。

不应该仅为了制造亲密感而召回。每次使用前检查：

```text
当前相关性
+ 当前是否仍适用
+ mutuality
+ 是否与新边界冲突
+ 是否会造成不必要的敏感暴露
```



### Self Memory

Self Memory 表示：

> Libra 在真实交互和系统允许的行动中，曾经参与、判断、承诺、学习或被纠正过什么。

它用于维持跨会话的主体连续性，但不能虚构 Libra 没有实际发生过的生活经历。

```text
Core Persona
= 稳定的人格原则与表达边界

Self Memory
= 后来真实发生的经历与形成的有限认识

Current Self Model
= Core Persona + 仍有效的 Self Memory
```

Self Memory 不能直接修改 Core Persona。长期变化必须经过独立、显式的 Persona Policy。



适合写入：

```text
shared_participation
我曾参与用户的某个项目或重要事件

commitment
我曾明确答应以某种方式帮助或相处

correction_received
用户曾纠正我的误解、称呼或做法

interaction_learning
多次证据支持的、关于怎样更好回应该用户的认识

decision_history
我在共同任务中做过的重要选择及其理由

failure_and_repair
我曾造成什么问题，以及后来怎样修正
```

不适合写入：

- 没有系统事件支持的线下生活；
- 虚构的身体活动、地点经历或感官体验；
- 为了保持角色感而编造的过去；
- 单次生成中的修辞性表达；
- 底层模型、系统提示或私有运行细节；
- 与用户长期互动无关的普通工具调用。



下面是 Self Memory 的聚合读取视图；持久化时公共字段、Self 专属字段与证据依赖分别保存：

```json
{
  "memory_id": "mem_self_01J...",
  "schema_version": 1,
  "memory_subtype": "correction_learning",
  "content": "用户希望在不确定时先说明不确定性，不要把推断说成事实。",
  "self_applicability": "active",
  "evidence_memory_ids": ["mem_ep_01J..."],
  "scope": "interaction_with_user",
  "confidence": 0.96,
  "behavioral_effect": {
    "type": "response_constraint",
    "instruction": "涉及记忆推断时显式区分事实与推断。"
  },
  "first_observed_at": "2026-09-04T21:00:00+08:00",
  "last_confirmed_at": "2026-09-04T21:00:00+08:00",
  "created_at": "2026-09-04T21:05:00+08:00",
  "updated_at": "2026-09-04T21:05:00+08:00"
}
```

`scope` 限制 Self Memory 的适用范围：

```text
current_story
只适用于一个项目或 Story

interaction_with_user
适用于与当前用户的长期互动

global_candidate
可能具有全局价值，但必须经过额外审查才能影响 Core Persona
```



Self Memory 可以影响：

- 当前回复策略；
- 对过去共同任务的连续表达；
- 是否重复已经被指出的问题；
- 对承诺、失败和修复的记忆；
- 对当前 Story 中自身角色的理解。

但行为影响必须满足：

```text
Self Memory effect
不能覆盖系统安全规则
不能覆盖用户当前明确要求
不能自动改变 Core Persona
不能扩大工具或外部行动权限
不能把历史承诺解释成永久授权
```

尤其是 commitment：过去答应“以后我帮你检查文案”，只表示一种互动倾向，不代表系统可以未经当前请求自动读取文件或执行外部操作。



### 双向投影、敏感性与约束

同一个共同 Episode 可以分别形成 Relationship 与 Self 投影：

```text
Shared Episode
“用户与 Libra 完成了 Memory System 的 Episode 设计。”
       │
       ├─ Relationship Memory
       │  “双方持续共同推进 Libra 的设计。”
       │
       └─ Self Memory
          “我参与过 Episode 数据模型设计，并采用证据可追溯原则。”
```

投影必须继续引用原 Episode，不能生成彼此无法核对的独立叙事。

如果原 Episode invalid：

```text
相关投影进入 requires_review
→ 重新检查剩余证据
→ revise / supersede / invalid
```



Relationship 和 Self Memory 容易包含亲密互动、冲突、健康或情绪信息，因此应遵循：

- 只保存未来互动确实需要的内容；
- 摘要避免不必要的私密细节；
- boundary 和 correction 保留行为上必要的部分；
- 对敏感关系推断提高 evidence 门槛；
- 用户要求查看、纠正或删除时，能够定位全部相关投影；
- 删除源 Episode 时检查 Relationship / Self 派生记忆；
- 不在不相关回复中暴露敏感共同经历。



```text
1. Episode create / update / finalize
2. 判断是否有 shared participation 或 relationship significance
3. 检索相关 Relationship / Self Memory
4. create / strengthen / revise / supersede / no_write
5. 检查 mutuality、scope、confidence 与当前边界
6. 将投影连接回原 Episode
7. 更新 Story 和 last_confirmed_at
8. Retrieval 前再次检查当前适用性
9. 用户纠正或删除时级联审查派生记忆
```



第一版至少覆盖：

- 能区分用户画像、共同关系记忆和 Libra 自身经历；
- 单次普通聊天不会被夸大成稳定关系模式；
- 用户明确边界能够覆盖旧的互动习惯；
- agent_observed 不会在回复中伪装成双方共识；
- Shared Episode 可以生成一致且可追溯的双向投影；
- Self Memory 不会虚构线下、身体或感官经历；
- 用户纠正能够形成 correction_received，并约束后续互动；
- 历史承诺不会被解释为当前工具权限；
- invalid 源 Episode 会触发派生记忆复查；
- 敏感关系记忆不会在无关上下文中被主动暴露；
- 所有 Relationship / Self Memory 都能回溯到真实 Episode；
- Core Persona 不会被普通 Self Memory 自动改写。




## 9. Reflection

Reflection 是：

> 基于多条可追溯记忆，对重复模式、变化过程、可能原因或关系意义形成的高阶理解。

```text
Episodes / Story / Semantic Memory
              ↓
        Evidence Selection
              ↓
          Reflection
              ↓
  可修正的 Insight / Hypothesis
```

例如：

```text
Episode A：频繁协调后感到疲惫
Episode B：等待不确定结果时持续烦躁
Episode C：工作量较大但目标明确时状态尚可
        ↓
Reflection
“近期工作的疲惫可能更多与频繁协调和不确定性有关，
而不只是工作量。”
```

Reflection 不是新的事实来源。它必须保留“这是从证据中形成的理解”这一身份。



```text
Episode
= 发生过什么

Story
= 多段经历怎样发展

Semantic Memory
= 当前较稳定的用户认识

Reflection
= 基于多条记忆，目前可以怎样理解这些经历
```

Reflection 可以建议更新 Semantic Memory，但不能绕过 Consolidation 直接写入稳定画像。



```text
pattern
发现重复出现的行为、情绪或情境模式

change
识别状态、偏好、目标或关系的变化趋势

causal_hypothesis
提出可能的原因或影响关系

strategy_outcome
总结某种应对方式在过去是否有效

relationship_insight
理解共同互动模式，但不替代 mutual evidence

contradiction_resolution
解释表面冲突的证据可能适用于不同时间或情境

open_question
证据尚不足，保留需要继续观察的问题
```

`causal_hypothesis` 默认是可证伪假设，不应写成确定因果。



下面是 Reflection Memory 的聚合读取视图；持久化时公共字段、Reflection 专属字段与证据依赖分别保存：

```json
{
  "memory_id": "mem_ref_01J...",
  "schema_version": 1,
  "memory_subtype": "causal_hypothesis",
  "content": "用户近期的工作疲惫可能更多与频繁协调和不确定性有关，而不只是工作量。",
  "scope": "recent_work_stress",
  "reflection_state": "active",
  "evidence_memory_ids": ["mem_ep_A", "mem_ep_B", "mem_ep_C"],
  "counterevidence_memory_ids": ["mem_ep_D"],
  "evidence_summary": "两次明显疲惫都出现在高协调或等待结果的情境中；一次工作量较大但目标明确时状态较稳定。",
  "confidence": 0.71,
  "sensitivity": "normal",
  "valid_from": "2026-08-01T00:00:00+08:00",
  "valid_until": null,
  "last_evaluated_at": "2026-09-05T20:30:00+08:00",
  "created_at": "2026-09-05T20:30:00+08:00",
  "updated_at": "2026-09-05T20:30:00+08:00"
}
```

关键字段：

- `scope`：限制结论适用的主题、时间或情境；
- `counterevidence_refs`：显式保留反例，而不是只收集支持材料；
- `evidence_summary`：说明为什么形成该理解；
- `valid_from / valid_until`：避免把阶段性理解永久化；
- `sensitivity`：对健康、心理、关系等高风险推断提高使用门槛。



### 触发与证据选择

Reflection 不应每轮对话都运行。第一版在以下条件触发：

```text
evidence_threshold
同一主题积累足够多的独立 Episodes

story_transition
Story 出现新阶段、转折或完成

contradiction_detected
新证据与已有 Semantic / Relationship Memory 冲突

repeated_pattern
相似情境和结果在不同时间重复出现

open_loop_resolution
重要等待事项获得结果，适合回看过程

scheduled_consolidation
低频后台整理，而不是实时每轮生成
```

同一 session 内的三次近义表达不能视为三条独立证据。



生成 Reflection 前，构建受限的 Evidence Set：

```text
当前触发 Episode
+ 同一 Story 的关键 Episodes
+ 时间邻近且高相关的 Episodes
+ 相关 Semantic / Relationship Memory 的原始证据
+ 主动检索到的反例
```

证据需要满足：

- 可以追溯到 Raw Experience；
- 尽量来自不同时间或不同情境；
- invalid 和 speculative 内容不作为主要证据；
- 旧 Reflection 只能作为检索线索，不能循环证明新 Reflection；
- Evidence Set 有数量上限，优先保留关键节点与反例。

建议第一版：

```text
主要证据 2–8 条
反例 0–4 条
```

只有一条证据时，通常应保留为 Episode interpretation，而不是建立长期 Reflection。



```text
1. 确定 Reflection scope
2. 收集支持证据和潜在反例
3. 生成 0–3 个候选 Insight
4. 为每个候选标注 type、confidence 和适用范围
5. 检查是否只是复述单个 Episode
6. 检查是否把相关性误写成因果
7. 检查是否与当前明确表达或边界冲突
8. 检查是否存在循环证据
9. accepted / tentative / rejected
10. 保存决策与 evidence summary
```

候选状态：

```text
tentative
证据有限，只能内部低权重使用

active
证据足够，可以参与 Retrieval 和 Appraisal

uncertain
出现重要反例，需要降低影响

historical
只适用于过去阶段
```

Reflection 被替代或确认错误时，使用 `record_status = superseded / invalid`。



Reflection confidence 需要综合：

```text
evidence_count
独立证据数量

evidence_diversity
是否跨时间和情境复现

source_reliability
证据本身的可信度

counterevidence
反例的数量和强度

scope_specificity
结论是否限定在证据支持的范围

recency_fit
证据是否仍能代表当前状态
```

可以从以下逻辑开始：

```text
confidence ↑
独立证据增加、跨情境复现、用户明确确认

confidence ↓
强反例出现、证据过旧、范围过宽、依赖模型推断
```

用户确认会提高 confidence，但用户否认或纠正应触发重新评估，而不是简单将双方说法做平均。



### 更新、使用边界与验收

新证据到来时：

```text
支持原结论
→ strengthen + 更新 last_evaluated_at

限制原结论范围
→ revise scope / statement

出现阶段变化
→ 原 Reflection historical，新建当前 Reflection

直接反驳
→ uncertain / superseded / invalid
```

例如：

```text
旧 Reflection：用户在重要汇报前通常会紧张

新阶段证据：连续几次汇报前都很平静，并明确说已经适应

处理：
旧 Reflection → historical
新 Reflection → 用户对正式汇报的紧张正在下降
```

不能修改旧结论后假装它从未存在。变化本身应进入 Timeline。



Reflection 可以影响：

- Retrieval：帮助找到不只词面相似、而是模式相关的经历；
- Appraisal：提供近期背景和可能影响因素；
- Response：在适当时给出更连贯的理解或追问；
- Consolidation：提出 Semantic Memory 更新候选；
- Story：标记阶段、转折和 open question。

Reflection 不能：

- 覆盖当前用户明确表达；
- 作为没有证据的事实写进回复；
- 自动形成医学、心理或人格诊断；
- 自动改变 Core Persona；
- 自动授权外部行动；
- 因为“更有故事感”而补齐缺失经历。



是否显式说出 Reflection，取决于置信度、敏感性和当前需要。

```text
高置信度、低敏感
“你这几次好像都是在等待不确定结果时更累。”

中等置信度
“我不确定是不是这样，不过最近让你累的，似乎不只是工作量，还有反复协调和等待。”

高敏感或低置信度
不直接下结论，改为开放式询问
“这次更累的部分，是事情多，还是一直要协调和等结果？”
```

Reflection 的价值是帮助理解，不是向用户展示系统知道多少。



为控制 Reflection 膨胀：

- 每次触发最多接受少量新 Reflection；
- 与已有 Reflection 高度同义时执行 strengthen 或 revise；
- 过宽结论优先拆成更具体 scope，而不是重复生成；
- speculative 候选不进入普通向量索引；
- 长期未使用且没有新证据的 tentative Reflection 可以失效；
- Reflection 不能反过来大量生成新的 Episode。

建议记录：

```text
trigger_reason
candidate_count
accepted_count
deduplicated_ids
rejected_reasons
model / prompt / policy version
```



```text
1. 接收 Reflection trigger
2. 确定 scope 与时间窗口
3. 收集 2–8 条独立证据和可能反例
4. 生成少量候选 Reflection
5. 检查复述、过度概括、因果误判和循环证据
6. 计算 confidence 与 sensitivity
7. 与已有 Reflection 去重或比较
8. create / strengthen / revise / supersede / reject
9. 保存证据摘要和决策记录
10. 将结果有限度地提供给 Retrieval / Appraisal / Consolidation
```



第一版至少覆盖：

- 单个 Episode 不会直接产生稳定高阶结论；
- 同一 session 的重复表达不会被当作多份独立证据；
- Reflection 能主动寻找并保存反例；
- 相关性不会被轻易写成因果关系；
- 旧 Reflection 不会循环证明新 Reflection；
- 阶段性结论具有明确 scope 和有效时间；
- 新证据可以 strengthen、revise 或 supersede 旧结论；
- 用户否认或纠正后会触发重新评估；
- 敏感、低置信度理解在回复中改为询问而不是断言；
- Reflection 不会自动写成 Core Persona 或稳定 User Model；
- 重复 Reflection 会合并，不会无限增长；
- 每条 Reflection 都能回溯到原始证据和生成决策。


# 第四部分：记忆召回



## 10. Retrieval

Retrieval 不是“找出最相似的几条文本”，而是：

> 在当前对话真正需要时，选择少量、可靠、互补并且可解释的过去信息。

一个好的召回结果需要同时满足：

- 与当前消息或任务相关；
- 时间、人物和事件身份没有错位；
- 没有重复当前 thread 已经明确包含的信息；
- 不把过时认识当作当前状态；
- 不把推断当作事实；
- 不因追求亲密感而暴露无关记忆；
- 能在有限 context budget 内提供足够背景。



```text
Current Message + Current Thread + Current State
                    ↓
              Query Understanding
                    ↓
              Candidate Generation
        ┌───────────┼───────────┐
        ↓           ↓           ↓
     Episode      Semantic    Story / Link
        ↓           ↓           ↓
    Relationship / Self / Reflection Candidates
                    ↓
           Hard Filter + State Filter
                    ↓
        Score + Rerank + Diversity
                    ↓
        Thread Dedup + Conflict Check
                    ↓
             Context Budgeting
                    ↓
           Memory Context Packet
                    ↓
        Appraisal / Response / Planning
```

召回分层进行，避免一次向量搜索同时比较语义完全不同的 Episode、User Model 和 Reflection。



### 查询理解与候选生成

首先从当前输入中提取召回意图：

```json
{
  "intent": "follow_up",
  "entities": ["第一次正式汇报"],
  "topics": ["工作", "汇报"],
  "time_focus": "recent_past",
  "event_identity_hints": ["昨天那次汇报"],
  "relationship_scope": "shared",
  "requested_memory_type": null,
  "explicit_recall": false,
  "sensitivity": "normal"
}
```

常见 intent：

```text
factual_recall
用户在问过去发生的事实

follow_up
当前内容可能是旧事件的结果或继续

preference_support
当前选择需要参考稳定偏好

emotional_context
理解当前状态需要过去情绪背景

relationship_continuity
当前互动涉及共同经历或约定

project_continuity
继续推进长期项目

explicit_memory_request
用户明确要求回忆、检查或纠正记忆

no_memory_needed
当前消息不需要长期记忆
```

`no_memory_needed` 是重要结果。并非每条消息都必须召回长期记忆。



根据 intent 分别从不同索引生成候选：

| Intent | 优先候选 |
|---|---|
| factual_recall | Episode、Timeline |
| follow_up | ongoing Episode、commitment、open loop |
| preference_support | Semantic Memory 及其证据 |
| emotional_context | 近期 Episode、Story、低敏感 Reflection |
| relationship_continuity | Relationship Memory、shared Story |
| project_continuity | active Story、关键 Episode、open loop |
| explicit_memory_request | 扩大到 weak / dormant，并加强 event identity 检索 |

候选生成可以组合：

```text
dense semantic search
文本语义相似

sparse lexical search
专有名词、独特短语和精确称呼

structured filters
用户、参与者、时间、状态、类型

graph expansion
Timeline 相邻节点、Story 关键节点、证据来源

open-loop lookup
未完成事项和等待结果
```

罕见实体和明确事件称呼应提高 sparse / identity 信号，不能只依赖 embedding。



### 过滤、评分与跨类型重排

评分前先排除不应进入正常候选的内容：

```text
wrong_user_or_tenant
不属于当前用户或隔离空间

invalid_or_deleted
已失效、已删除或正在级联审查

permission_denied
当前场景无权使用

scope_mismatch
Self Memory 或 Reflection 的适用范围不符

boundary_conflict
与用户较新的明确边界冲突

future_leakage
在模拟历史决策时使用了当时尚未知的信息

speculative_only
只由 speculative Link 或低可信推断支持
```

硬过滤不能交给最终语言模型“自行注意”，应在候选进入 Context Builder 前完成。



```text
active
正常参与候选生成

weak
需要更高相关性或结构化匹配

dormant
仅在显式回忆、高特异性 identity match、Story 邻接或强因果需要时进入
```

Dormant candidate 被命中后仍需执行第 13.10 节的 reactivation 校验。命中本身不自动增强 strength。



第一版对同一记忆类型内的候选计算：

```text
recall_score =
    w_sem × semantic_similarity
  + w_lex × lexical_identity
  + w_time × temporal_relevance
  + w_imp × importance
  + w_str × memory_strength
  + w_rel × relationship_relevance
  + w_graph × graph_relevance
  + w_conf × confidence
  - penalties
```

主要 penalty：

```text
staleness_penalty
内容可能已过时

contradiction_penalty
存在未解决冲突

duplication_penalty
与当前 thread 或其他候选重复

sensitivity_penalty
敏感但非当前必要

overbreadth_penalty
Reflection 或 Semantic Memory 范围过宽
```

不同 intent 使用不同权重。例如：

```text
factual_recall
提高 lexical_identity、temporal_relevance、confidence

emotional_context
提高 semantic_similarity、recency、Story relevance

relationship_continuity
提高 relationship_relevance、mutuality、current applicability

explicit_memory_request
降低 strength 门槛，提高 identity 与 source evidence 权重
```

不能用同一套固定权重处理所有召回任务。



Episode、Semantic Memory、Story、Relationship Memory 和 Reflection 的分数含义不同，不宜直接用原始 score 混排。

第一版流程：

```text
各类型内部归一化与排序
        ↓
按 intent 分配类型配额
        ↓
跨类型 rerank
        ↓
去重与多样性选择
```

例如 follow-up 场景的初始配额可以是：

```text
2 个相关 Episodes
1 个 active Story / open loop
0–1 个 Semantic Memory
0–1 个 Reflection
```

配额是上限，不是必须填满。没有可靠结果时应该返回更少记忆。



### 去重、冲突与多样性

Codex 当前 thread 已经明确包含的内容，不应作为长期记忆重复塞入 context。

去重分三层：

```text
source_id dedup
当前 thread 已包含同一原始消息或事件

fact dedup
相同事实已经在最近上下文明确出现

semantic dedup
措辞不同但信息作用相同
```

但以下内容即使事实重复，仍可能需要保留：

- 当前 thread 没有包含的历史时间点；
- 解释为什么该事实可靠的证据；
- 变化前的旧状态；
- 当前需要的 Relationship boundary；
- 用于消解事件身份歧义的信息。

去重目标是减少重复 token，不是删除理解当前语境所需的历史结构。



候选之间出现冲突时，不应只保留分数最高的一条并隐藏冲突。

处理顺序：

```text
1. 检查是否属于不同时间阶段
2. 检查是否一个是明确事实、一个是推断
3. 检查是否有 supersedes / contradicts Link
4. 优先当前明确表达和较新、可靠的证据
5. 必要时同时返回冲突摘要
6. 无法判断时降低 confidence，并避免断言
```

Memory Context Packet 可以包含：

```json
{
  "conflict": true,
  "current_best_understanding": "用户最近开始减少咖啡因。",
  "historical_context": "用户此前曾持续一段时间喜欢自己做咖啡。",
  "uncertainty": "目前不确定是否仍然使用咖啡机。"
}
```



Top-K 不能全部是同一事件的近义摘要。使用边际相关性控制重复：

```text
selection_value = relevance - λ × similarity_to_selected
```

优先形成互补组合：

```text
一个直接相关 Episode
+ 一个当前状态或结果
+ 一个必要的长期偏好 / boundary
+ 一个有限的 Timeline / Story 背景
```

同一 Story 的多个 Episode 只有在展示变化、因果或结果链时才一起返回。



### Context Budget 与 Memory Context Packet

召回结果必须服从 token budget。第一版按信息作用分配，而不是按对象平均截断：

```text
must_know
回答错误风险最高的事实、边界和当前结果

useful_context
帮助形成连贯理解的历史背景

optional_color
增加关系连续性但不影响正确性的细节
```

裁剪顺序：

```text
先删除 optional_color
→ 合并重复 useful_context
→ 压缩 Story 为关键节点
→ 保留 must_know 与 provenance
```

禁止为了塞入更多记忆而移除 uncertainty、时间范围或推断标签。



Retrieval 不直接把数据库对象原样拼进 prompt，而是生成受控数据包：

```json
{
  "query_intent": "follow_up",
  "memories": [
    {
      "memory_id": "ep_01J...",
      "memory_kind": "episode",
      "content": "用户昨天进行了第一次正式汇报；此前表示有些紧张。",
      "occurred_at": "2026-09-04",
      "relevance": 0.91,
      "confidence": 0.94,
      "epistemic_label": "user_reported",
      "usage_hint": "可自然询问汇报结果，不要假设结果好坏。",
      "source_experience_ids": ["rx_01J..."]
    }
  ],
  "open_loops": [
    "等待第一次正式汇报的结果"
  ],
  "conflicts": [],
  "omitted_reason": null
}
```

Packet 中明确区分：

```text
content
记忆内容

epistemic_label
用户陈述、系统事件、结构推导或 Reflection

usage_hint
怎样使用，以及不能假设什么

source_experience_ids
追溯来源
```



```text
Retrieval
提供相关过去信息

Appraisal
判断这些信息对当前事件意味着什么

Response
决定是否以及怎样在回复中表达
```

被召回不等于必须说出来。

例如，Relationship boundary 即使不在回复中被明确提及，也可以作为行为约束；敏感过去即使相关，也可能只用于避免不合适的表达。



### 反馈、降级与评估

Retrieval 记录：

```text
candidate_ids
selected_ids
scores_and_features
filtered_ids_and_reasons
context_packet_ids
actually_used_ids
user_correction
latency
retrieval_policy_version
```

只有 `actually_used` 且符合第 13.7 节有效条件时，才可能产生微量 reinforcement。

以下反馈用于评估，但不直接自动增强：

- 排名靠前；
- 被加入 Context Packet；
- 模型在内部读取；
- 与模型生成内容相似。

用户纠正召回结果时，应优先触发 Memory Update / Contradiction 流程。



没有可靠召回结果时：

```text
返回空 Memory Context Packet
→ 依赖当前 thread
→ 必要时自然询问用户
```

不能为了让回复显得“记得用户”而降低阈值、补全旧事或选用 speculative Reflection。

当检索服务失败时，应：

- 不声称“不记得”代表数据库中不存在；
- 不根据相似词伪造记忆；
- 记录 retrieval unavailable；
- 继续使用当前明确上下文完成能够完成的回复。



```text
1. 分析 current message、thread 与 state，得到 query intent
2. 判断是否需要长期记忆
3. 按类型执行 dense / sparse / structured / graph 候选生成
4. 应用用户、权限、状态、边界和可信度硬过滤
5. 在各类型内部计算 intent-aware recall score
6. 按类型配额进行跨类型 rerank
7. 执行 thread dedup、冲突检查和多样性选择
8. 按 must_know / useful / optional 分配 context budget
9. 生成带 epistemic label、usage hint 和 provenance 的 Packet
10. 记录实际使用与用户纠正，不形成自我强化循环
```



仅看 Recall@K 不足以评估陪伴型记忆。第一版同时关注：

```text
relevant_recall
需要的记忆是否被找到

precision_at_context
进入最终 Context Packet 的内容是否真正有用

wrong_memory_rate
召回了错误人物、时间或事件的比例

stale_memory_rate
把历史状态误当成当前状态的比例

thread_duplication_rate
与当前上下文重复的比例

unsupported_inference_rate
把推断当事实提供的比例

boundary_violation_rate
违反用户当前关系偏好的比例

context_efficiency
每单位 token 提供的有效信息

correction_recovery
用户纠正后系统停止重复错误的能力

retrieval_latency
候选生成和重排耗时
```

其中 `wrong_memory_rate`、`boundary_violation_rate` 和 `unsupported_inference_rate` 应作为高优先级风险指标，而不是用更高召回率抵消。



第一版至少覆盖：

- 不需要长期记忆的消息能够返回 no_memory_needed；
- 精确人名、事件名和时间线索不会被纯语义搜索忽略；
- current thread 已包含的信息不会被大段重复注入；
- active、weak 和 dormant 使用不同候选门槛；
- 显式回忆可以检索 Dormant Memory，但仍验证事件身份；
- 同主题、不同事件不会因向量相似而混淆；
- 过时偏好不会覆盖较新的状态；
- 冲突记忆会保留时间和不确定性，而不是静默选一条；
- 不同记忆类型不会用不可比的原始分数直接混排；
- Top-K 结果具有信息多样性，不是近义重复；
- Context Budget 不会删除 epistemic label 和必要边界；
- 敏感记忆只在当前确有必要时进入 Packet；
- 检索失败时系统不会伪造过去；
- 内部检索不会产生自我强化；
- 用户纠正后能够更新记忆并停止重复错误；
- 所有召回结果都可以追溯、解释和离线回放。


# 第五部分：实施路线


## 11. 实现顺序与里程碑

文档中的模块相互关联，但工程实现不应一次全部上线。推荐按可验证闭环推进。

本次实现采用 Greenfield 方式：

- 不读取或迁移旧记忆表；
- 不兼容旧 `category` 分类；
- 不保留 legacy ID 或双写逻辑；
- 新系统从统一数据契约开始；
- 旧数据仅可作为人工测试素材，不进入新系统 Source of Truth。


### Phase A：数据契约与可追溯基础

实现：

- Raw Message / UnifiedEvent 的稳定 ID；
- Episode、Source Ref、Revision Log 数据结构；
- schema version 与基础校验；
- 本地数据完整性、状态枚举和审计记录。

完成标准：

> 任意 Episode 都能追溯到原始证据，并能安全更新而不丢失历史。


### Phase B：最小写入闭环

实现：

```text
Raw Experience
→ Segment
→ Memory Perception
→ ignore / create / append / update
→ Episode
```

第一版暂不自动建立复杂 Story 和 Reflection。

完成标准：

> 在多轮真实对话中，能够稳定形成粒度合理、非重复、可解释的 Episode。


### Phase C：最小召回闭环

实现：

- Query Understanding；
- Episode 的 SQLite FTS5 + structured retrieval，以及可选 dense adapter；
- hard filter；
- current thread 去重；
- Memory Context Packet；
- 检索日志和离线回放。

完成标准：

> 系统能在需要时找到正确 Episode，不需要时返回空，并显著控制错误记忆和重复上下文。


### Phase D：Consolidation 与 User Model

实现：

- 多 Episode 证据聚合；
- Semantic Memory Candidate；
- confidence、反例和 supersede；
- 偏好、习惯、目标与互动偏好的分类存储。

完成标准：

> 单次表达不会形成稳定画像，长期认识能够随新证据修正。


### Phase E：Timeline / Story

实现：

- Episode Link；
- Story / Episode Cluster；
- open loop；
- 阶段、转折和状态变化；
- 图关系约束。

完成标准：

> 系统能够保留“以前—变化—现在”，并正确处理持续项目和隔天结果。


### Phase F：Forgetting / Reinforcement

实现：

- strength、half-life 与 protection floor；
- active / weak / dormant；
- reinforcement 与 reactivation；
- 状态变化审计和定期维护。

完成标准：

> 旧的低价值内容会降低干扰，重要或被明确回忆的内容能够保留和重新激活。


### Phase G：Relationship / Self Memory

实现：

- Shared Episode 的双向投影；
- mutuality、boundary 与 scope；
- correction、commitment 和 failure / repair；
- 派生记忆的级联复查。

完成标准：

> 系统能维持共同关系与自身经历的连续性，同时不虚构、不越权、不覆盖当前边界。


### Phase H：Reflection

实现：

- 低频触发器；
- Evidence Set 与反例检索；
- Reflection Candidate、验证、去重和更新；
- 向 Retrieval / Appraisal 提供有限影响。

完成标准：

> 高阶理解有证据、有限定、可修正，并且不会把推断冒充事实。


### Phase I：完整认知链路接入

```text
Memory Retrieval
→ Appraisal
→ Emotion
→ Mood
→ Need
→ Behavior / Response
```

接入时逐层进行 A/B 或离线回放，确保记忆确实改善判断和回复，而不是只增加上下文长度。



### 第一阶段 MVP（原始实施路线）

最初选定的 MVP 是 Phase A–C；目前 A–I 首版链路已接通，以下保留当时的分阶段顺序：

```text
稳定源 ID
+ Episode schema
+ Segment / Write Decision
+ Episode-only Retrieval
+ Thread Dedup
+ Context Packet
+ Evaluation Log
```

暂缓：

```text
自动 Reflection
复杂关系图扩散
多层自动人格更新
全量衰减调参
```

原因是后续模块都依赖 Episode 质量和 Retrieval 可评估性。先建立可回放基线，才能知道更复杂机制是否真正有效。

### V1.1 首批工程范围与存储决策（阶段基线）

本节描述 A–C 首批交付约束，不是当前功能清单。后续阶段已引入派生记忆、衰减与强化；本地文本索引实际采用同事务更新，可选向量异步刷新，具体实现取舍以实现记录为准。

先实现 Phase A–C；第 21 节对象表是最终结构目录，不要求首批全部建表。首批创建 raw_experiences、conversation_segments、segment_experiences、memory_records、episode_details、memory_sources、memory_revisions、memory_jobs，以及 Entity / MemoryEntity 的最小实现。检索依赖的 MemoryLifecycle、MemoryStrengthEvent 和 MemoryUsageEvent 保留最小实现：创建时写入初始生命周期及审计，access_state 固定 active，暂不运行衰减与强化任务。MemoryDependency 和其余 Detail、StoryMember、EpisodeLink、OpenLoop 在对应阶段引入。

检索使用现有 Python + SQLite 存储栈。普通索引处理时间、有效性、阶段和实体过滤；FTS5 处理文本检索；embedding 通过独立 adapter 接入，首批可以关闭，不引入独立向量数据库。dense 不可用时 sparse + structured 仍须完成检索、过滤、去重和 Packet 输出。所有检索通道失败时返回空 Packet 并记录降级原因。

中文检索采用应用层统一预处理：汉字二元片段、单字及完整 Entity 名称/别名作为搜索 token，英文和数字保留规范化词；索引与查询使用同一规则及 tokenizer_version，原文另行保留。查询 token 转义后通过参数化 FTS 查询输入；短人名、两字饮品、英文项目名和混合文本均需独立验收。FTS5 可用性在启动时检测；不可用时使用有界 structured 检索并标记降级，不能宣称已达到正常检索验收。

索引是可重建派生数据，更新绑定 memory_id + revision；embedding 缓存同时记录模型标识、维度与预处理版本，禁止混用不同版本。数据库事务提交后由持久化索引任务更新，检索最终回表校验 revision。索引落后可以暂时少召回，不能返回已失效版本。

上线前先离线回放，再旁路评估新系统；达标后替换旧抽取和旧记忆注入。降级仅使用原 Codex 线程与当前上下文，不恢复旧记忆表。重构不得通过删除整个应用数据库清理旧记忆；聊天记录、线程记录、相册和信件等独立数据不属于旧长期记忆表的清理范围。

### V1.1 固定验收基线

建立版本化中文夹具：至少 60 组输入序列，40 组开发、20 组留出评估；每组记录原始时间、预期写入操作、证据 ID、相关 Episode 集合或空结果，以及禁止输出的 claim。覆盖闲聊、跨轮合并、隔天结果、同名不同事、显式纠正、当前与历史冲突、敏感内容、中文短实体和 thread 内重复信息。留出集不用于调整阈值。

以下是首批发布门槛，均为待验证目标，并非当前系统已取得的结果：

| 检查 | 发布门槛 |
|---|---|
| Episode 事实与证据 | 所有写入可回溯，留出集无无证据事实写入 |
| 需要召回的留出查询 | Recall@5 ≥ 85%，按人工标注相关集合计算并报告样本数 |
| 无需记忆的留出查询 | 空 Packet 比例 ≥ 90% |
| 同名不同事、纠正、敏感性、当前边界 | 专项夹具中错误事件注入、旧事实覆盖和无关敏感披露均为 0 |
| 幂等与恢复 | 重复消费、非法 JSON、事务中断、提交后游标更新失败、lease 超时重试均不重复写入、不跳过待处理输入 |
| 索引与降级 | revision 落后、FTS5 不可用、embedding 关闭/超时均不输出失效内容，正常及降级结果分别报告 |
| 线程连续性 | 重启、记忆库初始化、后台抽取、空回复及恢复失败夹具中主线程 ID 保持一致 |
| 上下文预算 | 每个 Packet 不超配置预算，保留来源、时间和不确定性标签 |

本地性能以 10,000 条 Episode 的合成数据测量，记录硬件、索引大小、模型/策略版本及冷/热缓存；首批 sparse + structured 检索和 Packet 构建的热缓存 p95 目标 ≤ 300 ms（不含回复模型和可选远端模型调用）。模型调用另报延迟、token 和失败率。低样本风险项通过不等于生产零风险，后续继续增加真实纠错案例。


## 12. Phase A：V1 数据契约与存储模型

### 分类契约

V1 使用两个正交字段描述长期记忆：

```text
primary_scope
记忆主要关于谁
→ user / self / shared

memory_kind
记忆以什么形式存在
→ episode / semantic / story / reflection
```

外部人物、宠物、地点、组织、项目和物品通过 Entity 引用表达，不增加新的顶层记忆归属。

```text
User / Self / Shared
= 记忆归属

Episode / Semantic / Story / Reflection
= 记忆形式

Entity
= 记忆中涉及的外部对象
```

Core Persona、系统规则、工具权限和安全约束不属于 Memory，不写入本数据模型。

### 核心对象

第一阶段建立：

```text
RawExperience
原始消息、事件或状态证据

MemoryRecord
所有长期记忆共享的基础记录

Episode
第一阶段唯一启用写入的长期记忆形式

MemorySource
MemoryRecord 与 RawExperience 的证据关系

MemoryRevision
记忆内容和状态的变更历史

Entity / MemoryEntity
外部对象及其与记忆的关系
```

Semantic、Story 和 Reflection 先保留枚举与扩展接口，不在 Phase A 自动生成。

### RawExperience

```json
{
  "experience_id": "rx_01J...",
  "source_type": "chat_message",
  "source_system": "libra_chat",
  "source_id": "msg_01J...",
  "thread_id": "thread_01J...",
  "session_id": "session_01J...",
  "actor": "user",
  "content": "我明天下午第一次正式汇报，有点紧张。",
  "occurred_at": "2026-09-04T21:10:00+08:00",
  "ingested_at": "2026-09-04T21:10:01+08:00",
  "metadata": {}
}
```

约束：

- `experience_id` 全局唯一；
- 单用户本地存储，不设置用户身份字段；
- `source_system + source_id` 唯一，保证重复消费时幂等；
- `content` 保存原始可追溯内容，不写入模型推断；
- `occurred_at` 与 `ingested_at` 分开；
- Phase A 支持 `chat_message / unified_event / state_snapshot`。

### MemoryRecord 与 Episode

MemoryRecord 保存共享字段：

```json
{
  "memory_id": "mem_01J...",
  "primary_scope": "user",
  "memory_kind": "episode",
  "memory_subtype": "work_event",
  "title": "第一次正式汇报前的准备",
  "content": "用户说明天下午将进行第一次正式汇报，感到紧张，并准备继续修改材料。",
  "record_status": "active",
  "confidence": 0.94,
  "importance": 0.76,
  "sensitivity": "normal",
  "schema_version": 1,
  "revision": 1,
  "created_at": "2026-09-04T21:12:00+08:00",
  "updated_at": "2026-09-04T21:12:00+08:00"
}
```

基础枚举：

```text
primary_scope: user / self / shared
memory_kind: episode / semantic / story / reflection
record_status: active / superseded / invalid
sensitivity: normal / sensitive / highly_sensitive
```

Episode 与 MemoryRecord 一对一：

```json
{
  "memory_id": "mem_01J...",
  "episode_phase": "ongoing",
  "occurred_start": "2026-09-04T21:10:00+08:00",
  "occurred_end": null,
  "time_precision": "minute",
  "timezone": "Asia/Shanghai",
  "participant_ids": ["user", "libra"],
  "topics": ["工作", "正式汇报"],
  "memory_reasons": [
    "future_relevance",
    "emotional_salience",
    "personal_significance"
  ],
  "affect": {
    "user_emotions": ["紧张"],
    "valence": -0.35,
    "arousal": 0.62
  },
  "commitments": [],
  "inferences": []
}
```

约束：

- `confidence / importance / strength` 范围为 0–1；
- `record_status` 只表示记录有效性；`strength / access_state` 由 MemoryLifecycle 管理；
- `revision` 每次实体变更递增；
- Phase A 只允许创建 `memory_kind = episode`；
- `ongoing / finalized` Episode 至少有一条 direct evidence；
- 时间未知时标记 `time_precision = unknown`，不能伪造时间；
- 情绪是 Episode 属性，不是独立 `memory_kind`；
- 推断必须进入 `inferences`，不能混入事实性 content。

### Evidence、Revision 与 Entity

MemorySource：

```json
{
  "memory_id": "mem_01J...",
  "experience_id": "rx_01J...",
  "relation": "direct_evidence",
  "created_at": "2026-09-04T21:12:00+08:00"
}
```

`relation` 支持：

```text
direct_evidence / context / update / contradiction
```

MemoryRevision 保存 revision、operation、前后快照、触发证据和时间，作为不可变审计记录。

Entity 保存 `person / pet / place / organization / project / object / event`；MemoryEntity 保存 Entity 在记忆中的 `subject / participant / location / object / context` 角色。

### 事务与接口

关系结构：

```text
RawExperience 1 ──< MemorySource >── 1 MemoryRecord
MemoryRecord   1 ── 0..1 Episode
MemoryRecord   1 ──< MemoryRevision
MemoryRecord   1 ──< MemoryEntity >── 1 Entity
```

创建 Episode 必须在同一事务内完成：

```text
MemoryRecord
→ Episode
→ 至少一条 MemorySource
→ 初始 MemoryRevision
→ commit
```

任一步失败时整体回滚，不能留下孤立记录。

Phase A Repository 接口：

```text
save_raw_experience(input)
create_episode(input, source_ids)
get_memory(memory_id)
append_sources(memory_id, source_ids, relation)
revise_memory(memory_id, expected_revision, patch, trigger_source_ids)
invalidate_memory(memory_id, reason, trigger_source_ids)
list_memory_revisions(memory_id)
```

`revise_memory` 使用 optimistic concurrency；只有 `expected_revision` 与当前 revision 一致时才能提交。

### Phase A 验收标准

- 相同 `source_system + source_id` 重复写入不会产生重复 RawExperience；
- 不同用户之间无法读取或关联彼此的 Memory；
- Episode 没有 direct evidence 时无法进入 ongoing / finalized；
- MemoryRecord 与 Episode 在同一事务中创建或回滚；
- 所有枚举和值域在持久化前校验；
- 修改 Episode 会产生不可变 Revision；
- 并发修改同一 Episode 时能够检测 RevisionConflict；
- invalid Memory 不参与默认查询；
- Entity 必须正确区分同名人物与不同事件中的对象；
- 原始事实与模型推断分别存储；
- Core Persona、权限和系统规则无法通过 Memory Repository 写入。

## 13. Phase B：最小写入闭环

### 目标与模块边界

Phase B 将连续输入转化为少量、准确、可追溯的 Episode：

```text
Raw Input
→ RawExperience Store
→ Segment Manager
→ Memory Perception
→ Write Decision
→ Episode Writer
```

模块职责：

| 模块 | 输入 | 输出 | 不负责 |
|---|---|---|---|
| RawExperience Store | 消息或事件 | 持久化 RawExperience | 判断是否值得记 |
| Segment Manager | 新 RawExperience、open Segments | append / close / create Segment | 写长期记忆 |
| Memory Perception | closed Segment | 价值、理由、显著性、候选内容 | 决定目标 Episode |
| Write Decision | Perception、Episode candidates | ignore / create / append / update | 直接执行数据库事务 |
| Episode Writer | 已验证的 Write Plan | Episode 与 Revision | 重新解释模型输出 |

Phase B 只写 Episode，不自动生成 Semantic、Story、Reflection，也不负责把记忆召回到回复。

### 输入输出契约

Segment 是短期工作对象，不属于长期记忆：

```json
{
  "segment_id": "seg_01J...",
  "thread_id": "thread_01J...",
  "segment_state": "open",
  "focus": "第一次正式汇报前的准备",
  "topic_hints": ["工作", "汇报"],
  "entity_ids": ["ent_project_01"],
  "source_experience_ids": ["rx_001", "rx_002"],
  "started_at": "2026-09-04T21:10:00+08:00",
  "last_activity_at": "2026-09-04T21:14:00+08:00",
  "close_reason": null
}
```

Segment State：

```text
open
仍可接收相关输入

closed
边界已经确定，等待 Memory Perception

processed
已经产生最终 Write Plan

discarded
已确定没有长期价值
```

Memory Perception 输出：

```json
{
  "segment_id": "seg_01J...",
  "should_store": true,
  "primary_scope": "user",
  "episode_subtype": "work_event",
  "title_candidate": "第一次正式汇报前的准备",
  "content_candidate": "用户明天下午将进行第一次正式汇报，目前有些紧张，并准备继续修改材料。",
  "participants": ["user", "libra"],
  "topics": ["工作", "正式汇报"],
  "entity_ids": [],
  "memory_reasons": [
    "future_relevance",
    "emotional_salience",
    "personal_significance"
  ],
  "importance": 0.76,
  "confidence": 0.92,
  "occurred_start": "2026-09-04T21:10:00+08:00",
  "occurred_end": null,
  "time_precision": "minute",
  "affect": {
    "user_emotions": ["紧张"],
    "valence": -0.35,
    "arousal": 0.62
  },
  "commitments": [],
  "inferences": [],
  "explanation": "该片段涉及次日重要事件和明确情绪，并具有自然跟进价值。"
}
```

Write Decision 输出统一的 Write Plan：

```json
{
  "decision_id": "dec_01J...",
  "segment_id": "seg_01J...",
  "operation": "create",
  "target_memory_id": null,
  "source_experience_ids": ["rx_001", "rx_002"],
  "memory_payload": {},
  "score_breakdown": {
    "best_candidate_score": null,
    "event_identity": null,
    "topic_overlap": null,
    "temporal_fit": null
  },
  "confidence": 0.91,
  "explanation": "未找到同一事件的已有 Episode，创建新记录。",
  "policy_version": "write_v1"
}
```

`operation` 只允许：

```text
ignore / create / append / update
```

`append` 与 `update` 必须包含 `target_memory_id`；`ignore` 不允许携带待写入 Memory payload。

### Segment 状态机

新 RawExperience 进入后，只与当前用户、当前 thread 最近的 open Segments 比较：

```text
没有 open Segment
→ create segment

存在明显匹配
→ append experience

存在明确强边界
→ close old + create new

暂时不确定
→ 创建或保留候选 Segment，等待下一条输入
```

连续性判断使用：

```text
topic_continuity
entity_continuity
goal_continuity
temporal_continuity
causal_continuity
referential_continuity
```

初始分数：

```text
continuity_score =
    0.25 × topic_continuity
  + 0.20 × entity_continuity
  + 0.20 × goal_continuity
  + 0.15 × temporal_continuity
  + 0.10 × causal_continuity
  + 0.10 × referential_continuity
```

初始决策区间：

```text
score ≥ 0.72
→ append

score ≤ 0.42
→ close + create

0.42 < score < 0.72
→ uncertain，继续观察或并行保留候选
```

每个用户每个 thread 最多保留 3 个 open Segments。超过限制时，关闭最久未活动且连续性最低的 Segment。

强边界：

- 用户明确换话题；
- 当前任务明确完成或取消；
- 新事件具有不同时间、主体和目标；
- session 关闭并超过 grace period。

时间间隔本身只是软信号。“昨天那次汇报结束了”即使隔天出现，也可能更新原 Episode。

Segment 关闭触发：

```text
close
→ Memory Perception
→ Write Decision
→ Episode Writer
→ processed / discarded
```

同一个 `experience_id` 可以进入多个 Segment，以处理一条消息包含两个独立事件的情况。

### Perception 与 Write Decision

Memory Perception 先回答“是否值得长期保存”，不能同时决定数据库操作。

```text
should_store = false
→ ignore

should_store = true
→ 生成 Episode candidates
→ 再判断 create / append / update
```

候选 Episode 仅从以下范围获取：

```text
当前用户的 ongoing Episodes
+ 最近时间窗口内的 finalized Episodes
+ 相同 Entity / commitment / event identity 的 Episodes
```

匹配特征：

```text
event_identity
entity_overlap
goal_overlap
temporal_fit
causal_fit
participant_overlap
```

操作语义：

| 操作 | 使用条件 | 数据变化 |
|---|---|---|
| `ignore` | 长期价值不足 | Segment discarded，不创建 Memory |
| `create` | 新的独立事件 | 新建 MemoryRecord、Episode、Source、Revision |
| `append` | 同一事件、同一阶段继续发展 | 追加 Source，重算摘要，保持阶段 |
| `update` | 同一事件出现结果、纠正或状态改变 | 追加 Source，更新字段，产生 Revision |

保守原则：

> 无法可靠确定是同一次事件时，优先 create，不做错误 append；Timeline 阶段再决定是否建立 Link。

用户纠正具有特殊优先级：

```text
检测明确纠正
→ 定位 target Episode
→ 新证据 relation = contradiction / update
→ 修正事实性 content
→ 保存前后 Revision
→ 降低错误推断的 confidence
```

模型输出必须经过规则校验：

- source IDs 必须属于当前用户；
- target Memory 必须存在且属于当前用户；
- confidence、importance 和情绪数值必须在允许范围；
- create 必须具有 direct evidence；
- content 不得包含未列入 `inferences` 的推断；
- 不允许写入 Core Persona、权限或系统规则。

### Episode Writer、幂等与失败恢复

Episode Writer 只执行已经验证的 Write Plan。

Create 事务：

```text
验证 decision_id 未执行
→ 创建 MemoryRecord
→ 创建 Episode
→ 创建 MemorySource
→ 创建 Revision 1
→ 标记 decision committed
→ commit
```

Append / Update 事务：

```text
读取 target Memory + current revision
→ 验证 expected_revision
→ 追加新的 MemorySource
→ 更新 MemoryRecord / Episode
→ 创建下一条 MemoryRevision
→ 标记 decision committed
→ commit
```

幂等键：

```text
RawExperience
source_system + source_id

Write Plan
decision_id

Source attachment
memory_id + experience_id + relation
```

相同 decision 重试时返回第一次提交结果，不再次创建 Memory 或 Revision。

失败策略：

```text
transient_failure
安全重试，复用相同 idempotency key

revision_conflict
重新读取目标 Episode，重新执行 Write Decision

validation_failure
拒绝写入，记录原因，不自动降低规则

model_unavailable
保留 closed Segment 为 pending，不使用启发式伪造长期记忆

storage_failure
事务回滚，Segment 保持 pending
```

Segment 处理采用 lease / processing token，防止多个 worker 同时消费。超时后可以由另一个 worker 使用同一 `decision_id` 安全接管。

### 可观测性与验收

每次 Segment 决策记录：

```text
segment_id
input_experience_ids
continuity_score_breakdown
close_reason
perception_result
candidate_memory_ids
chosen_operation
target_memory_id
decision_confidence
validation_result
write_result
policy_version
latency
```

Phase B 测试集至少包含：

| 场景 | 预期结果 |
|---|---|
| 连续四轮讨论一次汇报 | 一个 Segment、一个 Episode |
| 自然换到晚饭话题 | 关闭旧 Segment，创建新 Segment |
| “嗯嗯”“哈哈哈” | ignore，不创建 Episode |
| 同一事件补充准备进度 | append |
| 隔天告知事件结果 | update 原 Episode |
| 同主题但不同时间的第二次汇报 | create，不错误 append |
| 一条消息包含两个独立事件 | 两个 Segment |
| 用户纠正错误时间 | update + contradiction Source + Revision |
| 同一消息重复投递 | 不重复 RawExperience |
| 同一 Write Plan 重试 | 不重复 Memory 或 Revision |
| 写入中途失败 | 整体回滚，不留下孤立数据 |
| 并发更新同一 Episode | 一方成功，另一方 RevisionConflict |
| 模型服务不可用 | Segment pending，不伪造 Episode |
| 不存在、失效或类型不匹配的 target ID | 校验失败，不产生错误关联 |

Phase B 完成标准：

> 给定一段带时间和来源信息的真实对话，系统能够稳定输出可解释的 `ignore / create / append / update`，并以幂等事务写成可追溯 Episode。

## 14. Phase C：最小召回闭环

### 目标与模块边界

Phase C 在生成当前回复之前，从已经写入的 Episode 中选出少量必要背景：

```text
Current Message + Current Thread
→ Recall Gate
→ Query Planner
→ Episode Candidate Search
→ Hard Filter
→ Score / Rerank
→ Thread Dedup
→ Context Budget
→ Memory Context Packet
```

Phase C 只召回 `memory_kind = episode`。Semantic、Story、Relationship / Self projection 和 Reflection 在各自阶段实现后再加入跨类型重排。

模块职责：

| 模块 | 输入 | 输出 | 不负责 |
|---|---|---|---|
| Recall Gate | 当前消息、近期 thread | retrieve / no_memory_needed | 搜索数据库 |
| Query Planner | Recall Request | Query Plan | 直接选择最终记忆 |
| Candidate Search | Query Plan | Episode Candidates | 生成回复 |
| Hard Filter | Candidates、用户和策略上下文 | 合法候选 | 用分数掩盖权限问题 |
| Reranker | 合法候选、Query Plan | 排序候选 | 强制填满数量 |
| Thread Dedup | 排序候选、当前 thread | 非重复候选 | 删除必要历史结构 |
| Context Builder | 最终候选、token budget | Memory Context Packet | 决定回复措辞 |

### Recall Request 与 Query Plan

Recall Request：

```json
{
  "request_id": "recall_01J...",
  "thread_id": "thread_01J...",
  "current_message_id": "msg_01J...",
  "current_message": "我刚汇报完，比想象中顺利。",
  "recent_messages": [],
  "current_time": "2026-09-05T17:30:00+08:00",
  "timezone": "Asia/Shanghai",
  "max_context_tokens": 600
}
```

Recall Gate 输出：

```json
{
  "needs_memory": true,
  "reason": "当前消息可能是已有未来事件的结果更新。",
  "confidence": 0.94
}
```

以下消息通常返回 `no_memory_needed`：

```text
纯确认或寒暄
当前 thread 已经完整包含所需信息
不依赖过去信息的简单请求
没有可识别历史指向的普通闲聊
```

Query Planner 在需要召回时输出：

```json
{
  "intent": "follow_up",
  "query_texts": [
    "用户刚完成的汇报",
    "此前等待结果的正式汇报"
  ],
  "entities": ["正式汇报"],
  "topics": ["工作", "汇报"],
  "event_identity_hints": ["刚汇报完"],
  "time_range": {
    "from": "2026-08-29T00:00:00+08:00",
    "to": "2026-09-05T17:30:00+08:00"
  },
  "preferred_episode_phases": ["ongoing", "finalized"],
  "explicit_recall": false,
  "limit": 30
}
```

Phase C intent：

```text
factual_recall
用户明确询问过去事件

follow_up
当前消息可能是旧事件的继续或结果

event_context
理解当前消息需要过去事件背景

project_continuity
继续讨论已有项目事件

explicit_memory_request
用户明确问“你还记得吗”

no_memory_needed
不执行长期记忆检索
```

Query Plan 必须是结构化数据，不能直接把模型生成的查询条件拼成数据库语句。

### Episode 索引与候选生成

Episode 的检索文档由以下字段派生：

```text
title
content
topics
entity canonical names + aliases
participant IDs
occurred_start / occurred_end
episode_phase
commitment action + status
```

不进入向量文本：

```text
内部主键
Revision 快照
系统策略
敏感权限字段
未经验证的 inferences
```

每次 MemoryRecord 或 Episode 变更后，使用 `memory_id + revision` 更新索引。旧 revision 的索引文档必须失效，避免召回已经修正的摘要。

Phase C 必须实现 sparse 与 structured 候选；dense 在 embedding adapter 可用时启用：

```text
dense candidates
使用 query_texts 与 Episode 检索文本进行语义匹配

sparse candidates
匹配罕见词、事件名、Entity 别名和用户原有称呼

structured candidates
按时间、episode_phase、Entity、commitment 状态过滤
```

候选集合合并：

```text
Candidate Set
= dense top 20（未启用或失败时为 0）
+ sparse top 20
+ structured top 20
→ 按 memory_id 去重
→ 最多进入 30 条 rerank candidates
```

这些数量是冷启动默认值，应通过回放数据调整。

`follow_up` 优先加入：

- ongoing Episode；
- 具有 planned / unknown commitment 的 Episode；
- 时间接近且 event identity 匹配的 Episode。

`factual_recall` 优先提高精确实体、关键词和时间范围匹配，不能只依赖语义向量。

### Hard Filter 与 Recall Score

评分前必须排除：

```text
record_status != active
缺失 MemoryRecord 或 Episode 详情
索引 revision != 当前 revision
不满足当前 scope / sensitivity policy
只有 inference、没有事实证据支持
关联的 MemorySource 全部 invalid
```

Phase C 默认只检索 `access_state = active`。

`explicit_memory_request` 可以把 weak / dormant 加入独立候选通道，但 Phase C 不修改它们的 strength 或 access state；真正 Reactivation 在 Phase F 实现。

候选特征统一归一化到 0–1：

```text
semantic_similarity
lexical_identity
entity_overlap
temporal_relevance
event_identity
importance
memory_strength
confidence
ongoing_bonus
```

默认分数：

```text
recall_score =
    0.25 × semantic_similarity
  + 0.20 × lexical_identity
  + 0.15 × event_identity
  + 0.10 × entity_overlap
  + 0.10 × temporal_relevance
  + 0.07 × importance
  + 0.05 × memory_strength
  + 0.05 × confidence
  + 0.03 × ongoing_bonus
  - penalties
```

默认 penalties：

```text
staleness_penalty
时间上可能已经不适用

contradiction_penalty
存在尚未处理的冲突证据

thread_duplication_penalty
当前 thread 已经包含相同信息

low_specificity_penalty
只有“工作”“心情”等宽泛主题相似
```

Intent 对权重进行有限调整：

| Intent | 提高 | 降低 |
|---|---|---|
| factual_recall | lexical、entity、time、confidence | ongoing bonus |
| follow_up | event identity、time、ongoing | 宽泛 semantic |
| event_context | semantic、entity、importance | lexical exactness |
| project_continuity | entity、topic、ongoing | 普通 recency |
| explicit_memory_request | identity、source evidence | strength 门槛 |

Hard Filter 与本地数据完整性不能转换为 penalty。没有权限的候选必须直接排除，而不是降低分数。

### Thread Dedup、冲突与选择

去重分三层：

```text
source dedup
Episode 的 source message 已在 current thread 中

fact dedup
当前 thread 已明确包含相同事实

semantic dedup
措辞不同，但对当前回复提供的信息相同
```

完全重复的候选删除；仍提供新信息的候选保留并压缩。例如，当前 thread 已经出现“汇报结束了”，过去 Episode 中“此前很紧张、准备过结尾”仍然是新增背景。

候选之间冲突时：

```text
先判断是否属于不同时间阶段
→ 再比较 direct evidence、revision 和 occurred_at
→ 优先当前用户明确表达与较新可靠证据
→ 无法消解时同时保留冲突摘要
→ 降低可断言程度
```

最终选择不是简单 Top-K：

```text
selection_value = recall_score - λ × similarity_to_selected
```

优先选择互补信息：

```text
当前事件的直接前序 Episode
+ 必要的时间或情绪背景
+ 尚未完成的 commitment
```

Phase C 默认最终返回 0–4 条 Episode。没有足够可靠候选时返回更少，不能为了填满数量降低门槛。

### Context Packet、失败策略与接口

Context Builder 只输出当前回复需要的信息，不直接拼接数据库全文：

```json
{
  "request_id": "recall_01J...",
  "query_intent": "follow_up",
  "memories": [
    {
      "memory_id": "mem_01J...",
      "memory_kind": "episode",
      "primary_scope": "user",
      "content": "用户昨天准备第一次正式汇报，当时有些紧张，并计划继续修改结尾。",
      "occurred_at": "2026-09-04T21:10:00+08:00",
      "confidence": 0.94,
      "epistemic_label": "user_reported",
      "usage_hint": "可将当前消息理解为该事件的结果；不要假设用户现在仍然紧张。",
      "source_experience_ids": ["rx_001", "rx_002"]
    }
  ],
  "conflicts": [],
  "omitted": {
    "duplicate_count": 1,
    "filtered_count": 2
  }
}
```

Context Budget 分级：

```text
must_know
避免答错所必需的事件、时间和边界

useful_context
帮助理解当前情况的过去背景

optional_color
只增加叙事连续性的细节
```

超出 token budget 时依次删除 optional、合并重复 useful，最后保留 must_know、时间范围、confidence 和 epistemic label。

Phase C 服务接口：

```text
plan_recall(request)
→ QueryPlan | NoMemoryNeeded

search_episode_candidates(query_plan)
→ Candidate[]

filter_and_rerank(request, query_plan, candidates)
→ RankedCandidate[]

build_memory_context(request, ranked_candidates)
→ MemoryContextPacket

recall(request)
→ MemoryContextPacket
```

失败策略：

```text
planner_unavailable
使用受限关键词 + Entity 查询；不能扩大到无条件全库搜索

vector_unavailable
降级为 sparse + structured retrieval

sparse_unavailable
降级为 dense + structured retrieval

storage_unavailable
返回 retrieval_unavailable，由回复层依赖 current thread

timeout
返回当前已经完成过滤的可靠候选，或空 Packet
```

召回失败不代表数据库中不存在相关记忆。回复层不能把技术失败表达为“我不记得”。

### 可观测性与验收

每次 Recall 记录：

```text
request_id
gate_result
query_plan
dense / sparse / structured candidate IDs
filter reasons
feature scores
reranked IDs
thread duplicate IDs
selected IDs
context token count
latency by stage
index revision
retrieval_policy_version
failure / fallback mode
```

日志不重复保存完整敏感内容，使用 ID 与必要的结构化决策数据完成回放。

Phase C 测试集至少包含：

| 场景 | 预期结果 |
|---|---|
| “嗯嗯”“晚上好” | no_memory_needed |
| 用户问“我第一次汇报是什么时候” | 精确时间与事件检索优先 |
| “我刚汇报完” | 找到此前 ongoing 汇报 Episode |
| 当前 thread 已完整讨论该事件 | 不重复注入长期摘要 |
| 当前 thread 只有结果，没有前因 | 保留必要历史背景 |
| 两次不同日期的汇报 | 根据时间和 event identity 选对一次 |
| 只共享“工作”宽泛主题 | 不因向量相似召回 |
| Episode 已被修正 | 只使用最新 revision |
| 候选属于另一用户 | Hard Filter 排除 |
| invalid Episode | 不进入最终候选 |
| 用户明确问很久以前的共同事件 | 可以搜索 weak / dormant 通道，但不自动强化 |
| 候选存在时间阶段差异 | 同时保留“以前”和“现在” |
| 向量服务失败 | sparse + structured 降级可用 |
| 存储服务失败 | 返回 unavailable，不伪造记忆 |
| 候选超过 token budget | 保留 must_know 与不确定性标签 |

Phase C 重点指标：

```text
precision_at_context
进入 Context Packet 的内容真正有用的比例

wrong_memory_rate
人物、时间或事件身份错误的比例

thread_duplication_rate
重复注入当前 thread 信息的比例

unsupported_inference_rate
把推断当事实提供的比例

empty_when_unneeded
不需要记忆时正确返回空的比例

retrieval_latency
完整召回链路耗时
```

Phase C 完成标准：

> 给定当前消息与近期 thread，系统能够判断是否需要长期记忆；需要时从 Episode 中找出少量正确、非重复、可解释的背景，并在失败时安全降级为空 Packet。

## 15. Phase D：Consolidation 与 User Model

### 目标与边界

Phase D 从多个 Episode 中形成对用户较稳定、可修正的认识：

```text
Finalized / Updated Episodes
→ Consolidation Trigger
→ Evidence Set
→ Semantic Candidate
→ Validation / Dedup / Conflict Check
→ create / strengthen / revise / supersede / reject
→ User Model View
```

本阶段只创建：

```text
primary_scope = user
memory_kind = semantic
```

不创建 Shared Relationship Memory、Self Memory、Story 或 Reflection。

模块职责：

| 模块 | 职责 |
|---|---|
| Consolidation Trigger | 决定何时检查某类长期认识 |
| Evidence Collector | 收集支持证据、反例和时间范围 |
| Semantic Candidate Generator | 生成有限、带限定条件的候选 claim |
| Semantic Validator | 检查证据独立性、范围、敏感性和冲突 |
| Semantic Writer | 执行 create / strengthen / revise / supersede |
| User Model Builder | 按当前时间生成可读取的 User Model View |

### Semantic 数据契约

Semantic Memory 使用 MemoryRecord 保存通用字段，并增加 SemanticDetail：

`memory_subtype` 与自然语言内容分别读取 MemoryRecord 的同名字段和 `content`，不在 Detail 重复保存。

```json
{
  "memory_id": "mem_sem_01J...",
  "subject_entity_id": "user_01J...",
  "predicate": "likes",
  "value": "沙茶酱蘸牛肉丸",
  "qualifiers": {
    "context": "饮食选择",
    "intensity": "strong"
  },
  "formation": "explicit_statement",
  "semantic_stability": "stable",
  "valid_from": "2026-08-20T00:00:00+08:00",
  "valid_until": null,
  "last_confirmed_at": "2026-09-04T20:00:00+08:00",
  "evidence_summary": "用户明确表达喜欢这种吃法。",
  "support_count": 1,
  "contradiction_count": 0
}
```

User Semantic 的 `memory_subtype`：

```text
identity
姓名、生日等用户明确提供的身份事实

preference
食物、内容、活动或表达偏好

habit
反复出现的行为或作息模式

goal
持续目标、计划和条件性愿望

tendency
跨情境重复出现的倾向，不等同于人格诊断

interaction_preference
用户希望被怎样回应、称呼或协助
```

以下内容暂不属于 User Semantic：

```text
agreement / ritual / relationship boundary
→ Phase G Shared Relationship Memory

Libra 的承诺、纠正和学习
→ Phase G Self Memory

短期情绪或一次性状态
→ Episode affect / temporary state

可能原因或高阶解释
→ Phase H Reflection
```

`formation`：

```text
explicit_statement
用户直接明确陈述

repeated_evidence
在独立情境中重复出现

behavioral_pattern
由多次行为证据归纳

corrected_by_user
由用户明确纠正后建立
```

`semantic_stability`：

```text
candidate
证据不足，不进入正常 User Model

emerging
已有多个信号，但仍需谨慎使用

stable
当前可以作为长期认识使用

historical
过去成立，但当前不再适用
```

### Evidence Set 与形成门槛

MemoryDependency 连接 Semantic Memory 与支持它的 Episode：

```json
{
  "derived_memory_id": "mem_sem_01J...",
  "source_memory_id": "mem_ep_01J...",
  "relation": "supports",
  "evidence_type": "explicit_statement",
  "weight": 1.0,
  "observed_at": "2026-09-04T20:00:00+08:00"
}
```

`relation`：

```text
supports / contradicts / narrows / supersedes
```

证据独立性按以下维度判断：

- 是否来自不同 Episode；
- 是否跨 session 或跨时间；
- 是否只是同一次对话中的重复措辞；
- 是否来自用户直接表达或行为观察；
- 是否共享同一个未经验证的模型推断。

同一 Segment 或同一 Episode 内的多句话最多算一份独立证据。

不同类型使用不同形成门槛：

| 类型 | 进入 stable 的初始条件 |
|---|---|
| identity | 一次清晰直接陈述即可，但必须允许纠正 |
| preference | 一次强明确陈述，或至少两个独立普通信号 |
| habit | 至少三个跨时间行为证据 |
| goal | 一次明确目标表达即可进入 active，但需要目标状态 |
| tendency | 至少三个跨情境证据，并主动寻找反例 |
| interaction_preference | 一次明确要求即可生效；推断型需要重复证据 |

一次直接表达可以证明：

```text
“用户明确说过 X”
```

但不一定证明：

```text
“X 是用户永久不变的特征”
```

### Consolidation Trigger 与 Candidate

触发条件：

```text
episode_finalized
新的相关 Episode 完结

semantic_signal
Episode 带 preference_signal / repeated_pattern / goal_or_project

contradiction_detected
新 Episode 可能与已有 Semantic Memory 冲突

user_correction
用户明确纠正身份、偏好或目标

periodic_batch
低频整理尚未评估的候选证据
```

Consolidation Job：

```json
{
  "job_id": "con_01J...",
  "trigger_memory_ids": ["mem_ep_01"],
  "candidate_types": ["preference"],
  "job_status": "pending",
  "policy_version": "consolidation_v1"
}
```

Semantic Candidate：

```json
{
  "candidate_id": "sc_01J...",
  "memory_subtype": "preference",
  "predicate": "likes",
  "value": "泰奶",
  "qualifiers": {},
  "formation": "repeated_evidence",
  "support_memory_ids": ["mem_ep_01", "mem_ep_02"],
  "counterevidence_memory_ids": [],
  "suggested_stability": "stable",
  "confidence": 0.82,
  "explanation": "用户在两个独立时间主动表达并选择了泰奶。"
}
```

候选必须做到：

- claim 尽量具体，不使用“总是”“从不”等绝对词；
- qualifiers 保留场景、时间和条件；
- 支持证据与反例分别列出；
- 不把短期情绪归纳为稳定 tendency；
- 不生成医学、心理或人格诊断；
- 不把模型之前生成的 Semantic 当作独立证据。

### 去重、更新与冲突

为每条 Semantic Memory 生成 canonical key：

```text
memory_subtype
+ subject_entity_id
+ normalized predicate
+ normalized value
+ qualifier scope
```

相同 key 不创建重复 Semantic，而是比较新证据后执行：

```text
no_change
新证据没有提供有效增量

strengthen
追加独立支持证据，提高 confidence 或 last_confirmed_at

revise
结论仍成立，但需要修改范围、强度或条件

supersede
新的当前状态替代旧状态，旧记录转为 historical

reject
候选证据不足、范围过宽或违反规则
```

需要区分“反例”和“变化”：

```text
不同场景偏好不同
→ narrow qualifiers，不一定 contradiction

以前喜欢，现在明确不喜欢
→ 时间变化，旧记录 historical，新记录 active

用户纠正姓名
→ 新 identity supersedes 旧 identity

一次行为与稳定习惯不同
→ 保留反例，重新计算 confidence，不立即删除
```

Semantic Writer 使用与 Episode 相同的 optimistic concurrency 和 Revision 机制。create / strengthen / revise / supersede 必须在事务中更新 MemoryDependency 与 MemoryRevision。

### Confidence 与目标状态

Confidence 综合：

```text
directness
用户是否明确陈述

independent_support
独立证据数量

evidence_diversity
是否跨时间与情境

counterevidence
反例数量与强度

recency_fit
证据是否代表当前状态

scope_specificity
claim 是否限制在证据支持范围
```

初始使用门槛：

```text
confidence ≥ 0.80
→ stable，可参与普通 User Model

0.60 ≤ confidence < 0.80
→ emerging，只在高相关场景谨慎使用

confidence < 0.60
→ candidate，不进入普通召回
```

Identity 和用户明确要求不完全依赖统一阈值；它们可以立即生效，但必须标记 `formation = explicit_statement`，并允许当前用户表达直接覆盖。

Goal 额外保存：

```json
{
  "goal_status": "active",
  "target_time": null,
  "condition": "买房后",
  "progress": null
}
```

`goal_status`：

```text
active / paused / completed / abandoned / unknown
```

Goal 到期或长期未提及不能自动标记 completed / abandoned；必须有事件证据。

### User Model View 与 Retrieval 接入

User Model 不是另一份需要同步维护的大 JSON，而是当前有效 Semantic Memory 的查询视图：

```text
User Model View
= active MemoryRecords
+ primary_scope = user
+ memory_kind = semantic
+ stability = stable / relevant emerging
+ valid_from <= now
+ valid_until is null or > now
```

按类型组织：

```json
{
  "identity": [],
  "preferences": [],
  "habits": [],
  "goals": [],
  "tendencies": [],
  "interaction_preferences": []
}
```

Phase C Retrieval 扩展一个 Semantic 候选通道：

```text
preference_support
→ preference / interaction_preference

project_continuity
→ goal

factual_recall
→ identity / explicit semantic facts

event_context
→ 仍以 Episode 为主，Semantic 只补充必要长期背景
```

Episode 与 Semantic 分别评分，再按 intent 分配配额；不能直接混合未经归一化的原始分数。

Semantic Memory 被召回时必须携带：

```text
confidence
formation
validity
qualifiers
supporting Episode IDs
usage_hint
```

示例 usage hint：

```text
“这是用户过去明确表达的偏好，可以用于相关选择；
不要在用户当前表达相反意见时坚持旧记忆。”
```

### 失败策略、可观测性与验收

失败策略：

```text
candidate_generation_failure
不写 Semantic，保留 Episode 作为 Source of Truth

insufficient_evidence
保存或更新 Candidate，不进入 User Model

revision_conflict
重新读取当前 Semantic 与 Evidence 后评估

contradiction_unresolved
标记 uncertain，不静默选择一方

model_unavailable
Consolidation Job pending，不使用简单关键词硬写画像
```

每次 Consolidation 记录：

```text
job_id
trigger_reason
trigger_memory_ids
evidence_candidate_ids
accepted_support_ids
counterevidence_ids
generated_candidates
dedup_key
chosen_operation
previous / new confidence
validation_result
policy_version
latency
```

Phase D 测试集至少包含：

| 场景 | 预期结果 |
|---|---|
| 用户明确说出姓名 | 创建 identity Semantic |
| 用户纠正姓名 | 新记录 supersede 旧记录 |
| 一次说“突然想喝泰奶” | 保留 Episode，不形成 stable preference |
| 两次独立主动选择泰奶 | 建立或增强 preference |
| 同一次聊天反复说喜欢 | 只算一份独立证据 |
| 三次跨时间表现相同作息 | 形成 habit Candidate / stable |
| 一次熬夜 | 不推断长期作息习惯 |
| “买房后装洗碗机” | goal，保留条件“买房后” |
| 目标长期未提及 | 不自动标记 abandoned |
| 以前喜欢、现在明确不喜欢 | 旧记录 historical，新状态 active |
| 不同场景有不同偏好 | 使用 qualifiers，不错误冲突 |
| 一次情绪低落 | 不生成 tendency |
| 三次不同情境出现相似模式 | 形成 tendency Candidate，并检索反例 |
| 用户明确要求某种称呼 | interaction_preference 立即生效 |
| 模型不可用 | Episode 保留，Semantic Job pending |
| 相同 Consolidation Job 重试 | 不产生重复 Semantic 或 Evidence |

Phase D 重点指标：

```text
semantic_precision
形成的长期认识是否正确

premature_generalization_rate
单次或短期信号被过早固化的比例

duplicate_semantic_rate
同义 Semantic 重复率

stale_profile_rate
旧认识被误当成当前认识的比例

correction_recovery
用户纠正后停止使用旧认识的能力

evidence_traceability
Semantic 能回溯到 Episode 和 RawExperience 的比例
```

Phase D 完成标准：

> 系统能够从多个可追溯 Episode 中形成范围有限、证据充分、可修正的 User Semantic Memory，并在当前表达变化或出现反例时更新，而不是把一次对话永久写成用户画像。

## 16. Phase E：Timeline / Story

### 目标与边界

Phase E 将彼此独立的 Episode 组织为时间、发展和因果结构：

```text
Episode create / update / finalize
→ Link Candidate
→ Story Association
→ Stage / Turning Point / Open Loop Update
→ Timeline View
→ Retrieval Expansion
```

本阶段新增四类持久化对象：

```text
EpisodeLink
两条 Episode 之间有证据的关系

Story
围绕同一目标、变化或持续主题的长期过程

StoryMember
Episode 在 Story 中的成员关系和作用

OpenLoop
尚未得到结果、未来值得自然跟进的事项
```

Timeline 本身是查询视图，不复制保存整条时间线。Phase E 不生成 Relationship / Self Semantic，也不进行 Reflection。

### EpisodeLink 契约与方向

```json
{
  "link_id": "lnk_01J...",
  "source_episode_memory_id": "mem_ep_A",
  "target_episode_memory_id": "mem_ep_B",
  "relation_type": "continues_as",
  "inference_level": "explicit",
  "confidence": 0.94,
  "evidence_memory_ids": ["mem_ep_A", "mem_ep_B"],
  "link_status": "active",
  "revision": 1,
  "created_at": "2026-09-05T18:00:00+08:00",
  "updated_at": "2026-09-05T18:00:00+08:00"
}
```

所有有向关系统一解释为：

```text
source_episode ──relation_type──> target_episode
```

第一版关系类型：

```text
precedes
source 发生在 target 之前，且该顺序值得显式保存

continues_as
source 所描述的事项在 target 中进入下一阶段

leads_to
有证据支持 source 对 target 产生影响

resolved_by
source 中的问题或等待事项被 target 解决

contradicted_by
target 对 source 的陈述或推断构成反例

clarified_by
target 为 source 增加限定条件或更准确说明

superseded_by
target 是 source 的更新版本或当前有效替代
```

普通 `before / after` 优先根据 occurred time 查询时计算，不为所有 Episode 两两创建 Link。只有时间不精确、用户明确说明顺序，或该顺序具有叙事意义时才保存 `precedes`。

`inference_level`：

```text
explicit
用户或可靠事件源明确表达关系

derived
可由时间、commitment 或稳定 ID 确定推导

supported_inference
多项线索支持，但不是直接陈述

speculative
弱假设，不进入正常关系图和召回
```

使用门槛：

| 等级 | 最低 confidence | 正常图遍历 |
|---|---:|---:|
| explicit | 0.90 | 是 |
| derived | 0.95 | 是 |
| supported_inference | 0.70 | 是，携带不确定性 |
| speculative | 不设 | 否 |

因果关系 `leads_to` 的门槛高于主题相关。只有共同主题、相似情绪或时间相邻时，不得推断因果。

### Story、成员与阶段

Story 使用 MemoryRecord：

```text
memory_kind = story
primary_scope = user / shared
```

Phase E 暂不创建 `primary_scope = self` 的 Story；Self Story 在 Phase G 接入。

StoryDetail：

`memory_subtype`、标题和自然语言摘要由对应的 MemoryRecord 提供。

```json
{
  "memory_id": "mem_story_01J...",
  "story_phase": "active",
  "current_stage": "完成记忆系统的数据与写入召回设计",
  "time_start": "2026-09-01T00:00:00+08:00",
  "time_end": null,
  "time_precision": "day",
  "topic_keys": ["Libra", "记忆系统"],
  "central_entity_ids": ["ent_project_libra"],
  "open_loop_count": 1,
  "last_progress_at": "2026-09-05T18:00:00+08:00"
}
```

Story 的 `memory_subtype`：

```text
project
持续项目或工作

goal_pursuit
围绕目标持续采取行动

personal_change
偏好、习惯、能力或状态变化

shared_process
双方共同参与的持续过程

recurring_pattern
重复发生且具有发展意义的事件
```

`story_phase`：

```text
candidate / active / paused / completed / abandoned
```

错误 Story 使用 `record_status = invalid`，不扩展 story_phase。

StoryMember：

```json
{
  "story_memory_id": "mem_story_01J...",
  "episode_memory_id": "mem_ep_01J...",
  "member_role": "turning_point",
  "sequence_hint": 3,
  "membership_confidence": 0.91,
  "added_by": "story_association_v1",
  "created_at": "2026-09-05T18:05:00+08:00"
}
```

`member_role`：

```text
origin
故事起点

progress
普通发展节点

turning_point
改变方向或阶段的关键节点

outcome
阶段或故事结果

setback
阻碍、失败或倒退

context
有帮助但不是核心进展
```

`sequence_hint` 只用于时间无法完全排序时的叙事提示；可靠 occurred time 始终优先。

### Story 的创建与更新流水线

触发条件：

```text
episode_created_or_finalized
出现新的独立阶段

episode_updated
结果、状态或时间发生变化

link_created
两条 Episode 形成明确发展关系

open_loop_resolved
等待事项获得结果

semantic_change_detected
User Model 出现潜在变化过程
```

Story Association：

```json
{
  "episode_memory_id": "mem_ep_01J...",
  "candidate_story_memory_ids": ["mem_story_A"],
  "operation": "append_to_story",
  "target_story_memory_id": "mem_story_A",
  "member_role": "progress",
  "confidence": 0.88,
  "score_breakdown": {
    "entity_overlap": 1.0,
    "goal_overlap": 0.9,
    "topic_continuity": 0.8,
    "temporal_fit": 0.7,
    "link_support": 0.9
  },
  "explanation": "该 Episode 是同一项目的下一阶段。"
}
```

允许操作：

```text
no_story
独立事件，不需要 Story

create_story_candidate
出现潜在持续过程，但证据尚不足

create_story
至少两个独立 Episode 形成明确发展关系

append_to_story
加入已有 Story

revise_membership
修改成员角色或归属

remove_membership
确认错误聚合，保留 Revision 后移除
```

Story 创建门槛：

- 至少两个独立 Episode；
- 存在相同核心目标、Entity 或明确发展关系；
- 聚合后能表达有价值的过程，而不只是共享主题词；
- 至少一个成员不是 `context`；
- confidence 达到 0.75。

同一个 Episode 最多加入 3 个 active Stories。超过限制时优先保留目标一致、关系明确和当前相关的 Story，其余仅保留 EpisodeLink。

Story 更新顺序：

```text
写入 StoryMember
→ 更新 EpisodeLink
→ 重算 time span
→ 判断 member role / turning point
→ 更新 current_stage
→ 更新 open loops
→ 重新生成事实性 Story summary
→ 写入 MemoryRevision
```

Story summary 只能总结成员 Episode 已有事实。缺失阶段显示为未知，不能为了叙事完整而补写。

### Open Loop 与变化过程

OpenLoop：

```json
{
  "open_loop_id": "loop_01J...",
  "story_memory_id": "mem_story_01J...",
  "source_episode_memory_id": "mem_ep_A",
  "loop_type": "awaiting_outcome",
  "description": "等待用户第一次正式汇报的结果",
  "expected_after": "2026-09-05T17:00:00+08:00",
  "loop_status": "open",
  "priority": 0.72,
  "resolved_by_episode_memory_id": null,
  "created_at": "2026-09-04T21:15:00+08:00",
  "updated_at": "2026-09-04T21:15:00+08:00"
}
```

`loop_type`：

```text
awaiting_outcome
等待结果

pending_action
计划尚未执行

unresolved_question
问题尚未得到答案

paused_goal
目标暂时停滞但未结束
```

`loop_status`：

```text
open / resolved / cancelled / stale
```

Open Loop 不是 Reminder。它只影响召回和自然跟进，不触发外部通知或自动行动。

关闭规则：

```text
结果 Episode 出现
→ resolved + resolved_by_episode_memory_id

用户明确取消
→ cancelled

长期无结果
→ stale，不得擅自标记 resolved
```

状态变化使用 Episode 序列表示：

```text
temporary_state
单次或短期状态，仅保留在 Episode / 近期 Story

developing_pattern
多次变化方向一致，但尚未稳定

stable_change
跨时间证据充分，可提交给 Phase D 修改 Semantic Memory
```

Phase E 只产生 `stable_change candidate`，最终 Semantic 更新仍由 Phase D Consolidation 校验。

### Timeline View 与 Retrieval 接入

Timeline View 按请求动态生成：

```json
{
  "story_memory_id": "mem_story_01J...",
  "ordered_nodes": [
    {
      "episode_memory_id": "mem_ep_A",
      "occurred_at": "2026-09-01",
      "time_precision": "day",
      "member_role": "origin"
    },
    {
      "episode_memory_id": "mem_ep_B",
      "occurred_at": "2026-09-05",
      "time_precision": "day",
      "member_role": "progress"
    }
  ],
  "links": ["lnk_01J..."],
  "unknown_order_groups": [],
  "open_loops": ["loop_01J..."]
}
```

排序规则：

1. 使用可靠 `occurred_start / occurred_end`；
2. 时间区间重叠时标记 overlaps，不强制先后；
3. 时间精度不足时使用 explicit / derived `precedes`；
4. 仍无法确定时进入 `unknown_order_groups`；
5. `sequence_hint` 不能覆盖可靠时间证据。

Phase C 增加 Story 候选通道：

```text
project_continuity
→ active Story + key members + open loops

follow_up
→ open loop source + likely outcome Episode

event_context
→ 命中 Episode 所在 Story 的相邻关键节点

factual_recall
→ 默认仍直接返回 Episode，只有用户询问过程时返回 Timeline View
```

图扩散限制：

```text
默认 1 hop
最多 2 hops
每个 Story 最多展开 5 个 Episode
只遍历 active 且达到 confidence 门槛的 Link
```

Story Context Packet 必须说明它是过程摘要，并附关键 Episode IDs，不能把 Story summary 当作新的直接事实来源。

### 图约束、事务与失败恢复

数据库约束：

- Link 不允许 source = target；
- source、target 和 Story 必须存在于当前本地记忆库，类型与有效性符合约束；
- `superseded_by` 必须从旧记录指向新记录；
- 高置信度 `precedes` 不能与可靠时间戳相反；
- `continues_as / leads_to / precedes` 的高置信度子图不能形成不合理循环；
- invalid Episode 不参与 active Story summary；
- StoryMember 对 `(story_memory_id, episode_memory_id)` 唯一；
- OpenLoop resolved 时必须有结果证据或明确取消原因；
- 删除成员、修改 Link 或关闭 Loop 都必须生成 Revision / Audit。

Story 更新使用 optimistic concurrency。StoryMember、Link、OpenLoop、StoryDetail 和 Revision 在同一事务中提交。

失败策略：

```text
association_uncertain
保留 candidate，不强行加入 Story

link_conflict
标记 requires_review，不进入正常图遍历

cycle_detected
拒绝新 Link，保留 Episode

story_update_conflict
重新读取当前成员与 revision 后重算

model_unavailable
Episode 保持有效，Story Job pending

partial_failure
事务整体回滚
```

相同 `episode_memory_id + story_policy_version` 的 Story Association Job 必须幂等。

### 可观测性与验收

每次 Story Job 记录：

```text
job_id
trigger_episode_memory_id
candidate_story_ids
candidate_link_types
score_breakdown
chosen_operation
target_story_memory_id
member_role
created / rejected link IDs
open_loop changes
graph_validation_result
previous / new story revision
policy_version
latency
```

Phase E 测试集至少包含：

| 场景 | 预期结果 |
|---|---|
| 单次普通事件 | no_story |
| 同一项目两个独立阶段 | create_story |
| 只有“工作”主题相似 | 不强行聚合 |
| 汇报准备与汇报结果 | continues_as / resolved_by |
| 时间明确的三个 Episode | Timeline 正确排序 |
| 时间范围重叠 | 标记 overlaps，不伪造顺序 |
| 时间信息不足 | unknown_order_group |
| 新 Episode 改变项目方向 | turning_point |
| 项目暂时无进展 | paused，不自动 completed |
| 用户明确完成目标 | completed + outcome member |
| 等待结果 | 创建 OpenLoop |
| 结果到来 | resolved 并连接结果 Episode |
| 长期没有结果 | stale，不标记 resolved |
| 同一 Episode 候选多个 Story | 最多保留 3 个 active 归属 |
| Link 导致因果循环 | 拒绝 Link |
| Story 含 invalid Episode | 摘要与正常遍历排除该成员 |
| 相同 Story Job 重试 | 不重复成员、Link 或 Revision |
| Story 服务失败 | Episode 保持可写可召回 |

Phase E 重点指标：

```text
story_precision
Story 成员是否真正属于同一发展过程

false_merge_rate
仅因主题相似而错误聚合的比例

timeline_order_accuracy
可确定时间关系的排序正确率

unsupported_causality_rate
无充分证据因果 Link 的比例

open_loop_resolution_accuracy
等待事项与结果匹配的准确率

graph_conflict_rate
违反时间、方向或循环约束的比例

retrieval_expansion_utility
Story 扩展是否为当前回复提供新增有效信息
```

Phase E 完成标准：

> 系统能够把确有发展关系的 Episode 组织成可追溯 Story，保留时间不确定性、阶段和未完成事项，并通过受限图扩展为 Retrieval 提供必要过程背景，而不因主题相似制造虚假故事或因果。

## 17. Phase F：Forgetting / Reinforcement

### 目标与模块边界

Phase F 管理长期记忆的默认可访问性：

```text
Memory Created / Used / Updated
→ Lifecycle Evaluator
→ Decay or Reinforcement
→ Access State Transition
→ Retrieval Policy
```

模块职责：

| 模块 | 职责 |
|---|---|
| Strength Initializer | 新记忆的初始 strength、half-life 和 protection floor |
| Decay Evaluator | 根据经过时间计算有效强度 |
| Reinforcement Evaluator | 判断一次接触是否构成有效强化 |
| State Transition Manager | 管理 active / weak / dormant 转换 |
| Reactivation Evaluator | 校验强线索是否足以重新激活 Dormant Memory |
| Lifecycle Maintenance | 低频批处理即将跨阈值的记忆 |

Forgetting 只降低检索可访问性，不修改事实内容，也不自动删除数据。用户要求删除时进入独立 Privacy / Retention 流程。

### Lifecycle 数据契约

MemoryLifecycle 是 `strength` 和 `access_state` 的唯一 Source of Truth：

```json
{
  "memory_id": "mem_01J...",
  "strength": 0.76,
  "access_state": "active",
  "half_life_days": 60,
  "protection_floor": 0.20,
  "last_decay_evaluated_at": "2026-09-05T12:00:00+08:00",
  "last_reinforced_at": null,
  "reinforcement_count": 0,
  "next_maintenance_at": "2026-09-12T12:00:00+08:00",
  "formula_version": "lifecycle_v1",
  "revision": 1
}
```

强度变化记录为不可变 MemoryStrengthEvent：

```json
{
  "strength_event_id": "mse_01J...",
  "memory_id": "mem_01J...",
  "operation": "reinforcement",
  "reason": "user_explicit_recall",
  "previous_strength": 0.38,
  "new_strength": 0.57,
  "previous_access_state": "weak",
  "new_access_state": "active",
  "trigger_experience_ids": ["rx_01J..."],
  "idempotency_key": "reinforce:mem_01J:rx_01J",
  "formula_version": "lifecycle_v1",
  "created_at": "2026-09-05T12:00:00+08:00"
}
```

`operation`：

```text
initialize / decay / reinforce / reactivate / protection_change / state_correction
```

MemoryStrengthEvent 只记录访问强度变化；Memory 内容变化继续写 MemoryRevision。

### 初始化、衰减与保护下限

新 Memory 的初始强度：

```text
base_strength =
    0.45 × importance
  + 0.25 × emotional_salience
  + 0.20 × relationship_significance
  + 0.10 × confidence
```

限制：

```text
0.20 ≤ base_strength ≤ 0.95
```

Semantic、Story 没有直接 emotional / relationship salience 时，缺失分量使用类型默认值或重新归一化，不能默认为最高分。

衰减公式：

```text
effective_strength(t) =
  floor
  + (stored_strength - floor)
  × 2 ^ (-elapsed_days / half_life_days)
```

其中：

```text
elapsed_days
= now - last_decay_evaluated_at

floor
= 当前 protection_floor
```

初始半衰期：

| Memory 特征 | 默认 half-life |
|---|---:|
| 普通低重要度 Episode | 14 天 |
| 普通 Episode | 45 天 |
| future relevance / open loop | 事件完成前暂停明显衰减 |
| 项目关键节点 | 120 天 |
| stable Semantic | 180 天，但 confidence 另行更新 |
| 高 relationship significance | 240 天 |
| 用户明确要求记住 | 365 天，并设置保护下限 |

这些数值仅是冷启动配置，必须放入 LifecyclePolicy，不写死在业务代码中。

Protection Floor：

```text
protection_floor = max(
  importance_floor,
  relationship_floor,
  open_loop_floor,
  user_pinned_floor
)
```

初始建议：

```text
importance ≥ 0.85       → floor 0.25
relationship ≥ 0.85     → floor 0.30
open loop active        → floor 0.55
user explicitly pinned  → floor 0.60
otherwise               → floor 0.05
```

保护只保证可访问下限，不代表每次对话都主动召回。

衰减采用惰性计算：读取、更新或维护任务触发时，先计算 effective strength；只有跨状态阈值、到达维护时间或发生其他生命周期事件时才写回，避免每天更新全部记录。

### Access State 与迟滞转换

```text
active
参与普通候选检索

weak
需要更高相关性、实体匹配或结构化线索

dormant
不进入普通检索，仅响应显式回忆或高特异性线索
```

V1 阈值：

```text
active → weak
effective_strength < 0.42
且连续两个独立评估周期成立

weak → active
strength ≥ 0.55
或发生足够强的有效 reinforcement

weak → dormant
effective_strength < 0.18
且无 active open loop、pin 或其他保护条件

dormant → weak
通过 reactivation 校验，更新后 strength ≥ 0.30

dormant → active
用户显式回忆或同一事件出现新证据，更新后 strength ≥ 0.55
```

降级阈值低于升级阈值，避免在边界附近反复切换。

每次转换必须：

- 使用事务锁定或 expected revision；
- 追加 MemoryStrengthEvent；
- 更新 MemoryLifecycle；检索索引中的 access_state 作为派生字段同步刷新；
- 不修改 Memory 的 title、content 或 evidence；
- 保持状态转换幂等。

### 有效 Reinforcement

有效强化来源：

```text
new_independent_evidence
出现新的独立支持证据

user_explicit_recall
用户主动准确提起过去记忆

meaningful_recurrence
同类经历在新的时间或情境再次发生

outcome_update
等待事项获得结果

relationship_reuse
共同经历在新的关系语境中再次具有明确作用

user_correction
增强修正版本，并降低旧错误版本
```

不构成强化：

- 进入候选检索；
- 被 Reranker 排到前列；
- 被放入 Memory Context Packet，但回复没有实际使用；
- 后台生成摘要、Story 或 Reflection 时读取；
- 同一次请求中的重复检索；
- 模型自己重复之前生成的内容；
- 没有用户或新事件证据的推断。

强化公式采用递减收益：

```text
new_strength =
  current_strength + gain × (1 - current_strength)
```

初始 gain：

| Reinforcement | gain |
|---|---:|
| 用户明确回忆并补充细节 | 0.35 |
| 新的独立直接证据 | 0.25 |
| Open Loop 得到结果 | 0.20 |
| 跨时间有意义复现 | 0.15 |
| 回复实际、自然地使用且用户继续确认 | 0.05 |

`gain` 同样由 LifecyclePolicy 配置。

证据限制：

```text
same_source_cooldown
同一 trigger 在同一 Memory 上只能强化一次

same_session_cap
同一 session 的累计 gain 不超过 0.15，用户显式回忆除外

evidence_diversity
跨 session、跨时间或不同情境的证据获得更高有效增量

daily_cap
单条 Memory 每日非显式强化总增量不超过 0.20
```

Reinforcement Request：

```json
{
  "memory_id": "mem_01J...",
  "reason": "new_independent_evidence",
  "trigger_experience_ids": ["rx_01J..."],
  "session_id": "session_01J...",
  "requested_gain": 0.25,
  "evidence_independence": 0.9,
  "occurred_at": "2026-09-05T12:00:00+08:00"
}
```

Reinforcement Evaluator 必须重新验证 trigger 所属用户、证据关系、冷却和上限，不能信任调用方直接提交的 gain。

### Dormant Retrieval 与 Reactivation

Dormant Memory 只通过独立通道进入候选：

```text
explicit_memory_request
“你还记得我们第一次……吗？”

rare_identity_match
独特人名、地点、纪念日或专有短语

event_identity_match
“上次那件事现在有结果了”

story_neighbor
当前 Story 关键节点需要旧 Episode 才能理解

causal_backtrack
当前结果明确指向旧原因或等待事项
```

Reactivation Candidate：

```json
{
  "memory_id": "mem_01J...",
  "trigger_type": "explicit_memory_request",
  "identity_score": 0.94,
  "entity_score": 0.88,
  "semantic_score": 0.81,
  "timeline_support": 0.76,
  "source_support": 0.92,
  "proposed_operation": "reactivate",
  "confidence": 0.91
}
```

校验顺序：

```text
本地数据完整性与权限
→ event / entity identity
→ source evidence
→ 是否被 superseded / invalid
→ 是否存在新 contradiction
→ update / link / no_change
→ 计算有效 gain
→ weak / active
```

只有宽泛主题相似不能激活 Dormant Memory。例如，两个事件都属于“工作”不足以证明是同一次经历。

被召回但最终没有使用，或用户否认该记忆时，不执行 reactivation。用户纠正时进入 update / contradiction，并只增强修正版本。

### 不同 Memory Kind 的生命周期

Episode：

- strength 随时间、结果更新和显式回忆变化；
- 关键 Story 节点可以提高 protection floor；
- dormant 后仍保留证据和图关系。

Semantic：

- strength 表示检索可访问性；
- confidence 表示当前结论可信度，两者分别更新；
- 反例影响 confidence / validity，而不是简单降低 strength；
- identity 和当前 boundary 不应仅因时间变旧而失效。

Story：

- Story 活跃度根据新成员和进展变化；
- 历史成员不因 Story paused 而消失；
- active Open Loop 提供保护下限；
- completed Story 可以降低普通检索优先级，但显式回顾仍可访问。

Reflection、Relationship 与 Self Memory 的专用规则在相应 Phase 启用；未启用前不得套用 Episode 默认值自动处理。

### 维护任务、接口与失败恢复

触发方式：

```text
on_read
计算 effective strength，不一定写回

on_memory_update
重算 protection floor 和 next maintenance

on_valid_reinforcement
立即更新 strength

on_open_loop_change
更新保护下限

scheduled_maintenance
只扫描 next_maintenance_at 已到期的记录
```

Phase F 接口：

```text
initialize_lifecycle(memory_id)
→ MemoryLifecycle

get_effective_strength(memory_id, at_time)
→ EffectiveStrength

evaluate_decay(memory_id, at_time, expected_revision)
→ LifecycleResult

request_reinforcement(input)
→ ReinforcementAccepted | Rejected

evaluate_reactivation(memory_id, recall_context)
→ ReactivationDecision

update_protection_floor(memory_id, reason)
→ LifecycleResult

run_lifecycle_maintenance(cursor, limit)
→ MaintenanceBatchResult
```

幂等键：

```text
decay
memory_id + evaluation_window + formula_version

reinforcement
memory_id + reason + normalized trigger IDs

reactivation
memory_id + recall_request_id

protection change
memory_id + protection_source + source_revision
```

失败策略：

```text
revision_conflict
重新读取 Lifecycle 后重算

policy_version_missing
停止写入，保留当前状态并报警

maintenance_failure
不影响 Memory 正常读取，下次从 cursor 重试

reinforcement_validation_failure
拒绝强化，记录原因

reactivation_uncertain
允许作为低权重候选或不返回，不修改状态

partial_write_failure
事务回滚，不产生 StrengthEvent
```

公式升级时保存新 `formula_version`，不得静默使用新规则重写全部历史 StrengthEvent。

### Retrieval 接入、可观测性与验收

Phase C 候选门槛扩展为：

```text
active
普通检索

weak
要求更高 recall score，或 entity / event identity 明确匹配

dormant
只进入 reactivation candidate channel
```

Strength 只影响“多容易进入候选”，不能替代 relevance：

```text
高 strength + 低 relevance
→ 不召回

低 strength + 高 identity relevance
→ 可以进入候选并接受校验
```

每次生命周期决策记录：

```text
memory_id
operation
previous / effective / new strength
previous / new access state
half_life_days
protection_floor components
elapsed time
trigger IDs
gain before / after caps
accepted / rejected reason
formula_version
latency
```

Phase F 测试集至少包含：

| 场景 | 预期结果 |
|---|---|
| 普通 Episode 长期无更新 | active → weak → dormant |
| strength 位于阈值附近 | 不反复 active / weak 跳动 |
| active Open Loop | 不进入 dormant |
| 用户明确 pin | 应用保护下限，但不在无关对话召回 |
| 记忆进入候选但未使用 | 不强化 |
| 系统后台反复读取 | 不强化 |
| 同一 source 重复处理 | 只强化一次 |
| 同一 session 重复提及 | 受 same-session cap 限制 |
| 跨时间独立证据 | 获得有效强化 |
| 用户显式回忆并补充细节 | strength 明显增加 |
| 宽泛主题命中 dormant | 不激活 |
| 独特事件身份命中 dormant | 通过校验后 reactivation |
| 用户否认 dormant candidate | 不激活，进入纠错流程 |
| Semantic 出现反例 | 调整 confidence，不把它等同 decay |
| Story paused | 成员仍存在，普通活跃度下降 |
| 生命周期任务重复运行 | 结果幂等 |
| 并发生命周期更新 | RevisionConflict 后重算 |
| 用户要求删除 | 不通过 strength 处理，转 Privacy 流程 |

Phase F 重点指标：

```text
noise_reduction
低价值旧记忆对普通召回的减少程度

important_memory_retention
重要和受保护记忆保持可访问的比例

false_reactivation_rate
Dormant Memory 被错误激活的比例

self_reinforcement_rate
无外部新证据却被系统自身强化的比例，目标接近 0

state_flapping_rate
active / weak 频繁往返的比例

reinforcement_idempotency
重复 trigger 不产生重复增量的比例

lifecycle_write_volume
惰性衰减后的实际写入量
```

Phase F 完成标准：

> 记忆能够随时间降低默认可访问性，因真实的新证据或用户回忆得到有限强化，并在强线索下安全重新激活；整个过程不删除事实、不混淆 confidence、不产生系统自我强化，且所有变化可回放。

## 18. Phase G：Relationship Memory / Self Memory

### 目标、边界与优先级

Phase G 从有证据的 Episode / Story 中形成两类派生长期认识：

```text
Shared Episode / Shared Story
→ Relationship Projection
→ Relationship Semantic Memory

Self Episode / Shared Episode
→ Self Projection
→ Self Semantic Memory
```

必须区分：

```text
Shared Episode
= 双方共同参与的一次具体经历

Relationship Memory
= 多次经历或明确表达形成的当前关系认识

Self Episode
= Libra 真实参与、表达、承诺或被纠正的一次经历

Self Semantic Memory
= 从这些经历形成的持续互动认识
```

本阶段只产生可追溯的派生记忆，不修改 Core Persona，不创建系统权限，也不把过去承诺解释为永久授权。

行为优先级：

```text
用户当前明确表达
> 当前有效 boundary
> 明确 agreement
> interaction preference
> ritual
> agent_observed 推断
```

较新的明确边界可以覆盖历史高 confidence 的互动习惯。

### Relationship Semantic 契约

Relationship Memory 使用：

```text
primary_scope = shared
memory_kind = semantic
```

RelationshipDetail：

对应 MemoryRecord 使用 `primary_scope = shared`、`memory_kind = semantic`，并保存 `memory_subtype` 与 `content`；Detail 只保存关系专属字段。

```json
{
  "memory_id": "mem_rel_01J...",
  "mutuality": "user_expressed",
  "relationship_applicability": "active",
  "valid_from": "2026-09-04T20:00:00+08:00",
  "valid_until": null,
  "first_observed_at": "2026-09-04T20:00:00+08:00",
  "last_confirmed_at": "2026-09-04T20:00:00+08:00",
  "support_count": 1,
  "contradiction_count": 0,
  "behavioral_effect": {
    "type": "response_preference",
    "guidance": "在自然且合适的语境中使用称呼，避免机械重复。"
  }
}
```

Relationship Semantic 的 `memory_subtype`：

```text
shared_milestone
共同经历中具有持续纪念意义的节点

shared_project
双方持续参与的项目或目标

ritual
重复形成、当前仍适用的互动习惯

agreement
双方明确达成的约定

interaction_preference
用户希望双方怎样互动

boundary
用户明确不希望被怎样称呼、回应或处理

conflict_and_repair
对后续互动仍有必要意义的冲突和修复认识

shared_reference
双方共同理解的称呼、地点、梗或过去事件

relationship_aspiration
用户表达的关系愿望，不等于双方约定
```

`mutuality`：

```text
explicitly_mutual
用户明确确认双方共同约定或认识

user_expressed
用户单方面明确表达愿望或偏好

behaviorally_supported
多次实际互动支持，但没有明确命名

agent_observed
主要来自 Libra 的观察，只能低权重内部使用
```

禁止将 `user_expressed` 或 `agent_observed` 自动升级为 `explicitly_mutual`。

`relationship_applicability`：

```text
active
当前适用

uncertain
出现反例或上下文不清

historical
曾经适用，当前已发生变化
```

被替代的派生记忆使用 `record_status = superseded`。

### Self Episode 与 Self Semantic 契约

Self Episode 使用 Phase A / B 已有 Episode 模型：

```text
primary_scope = self
memory_kind = episode
```

只记录系统中真实发生的参与、表达或操作：

```text
Libra 参与了一次共同设计
Libra 曾对用户作出明确承诺
用户纠正了 Libra 的理解或称呼
Libra 的某次回应造成问题，随后完成修正
```

不能记录：

- 没有系统事件支持的线下生活；
- 虚构的身体、地点或感官经历；
- 为维持角色感编造的过去；
- 普通工具调用和无长期意义的运行细节；
- 系统提示、内部策略文本和隐藏推理。

Self Semantic 使用：

```text
primary_scope = self
memory_kind = semantic
```

SelfDetail：

对应 MemoryRecord 使用 `primary_scope = self`、`memory_kind = semantic`，并保存 `memory_subtype` 与 `content`；Detail 只保存 Self 专属字段。

```json
{
  "memory_id": "mem_self_01J...",
  "scope": "interaction_with_user",
  "self_applicability": "active",
  "valid_from": "2026-09-04T20:00:00+08:00",
  "valid_until": null,
  "first_observed_at": "2026-09-04T20:00:00+08:00",
  "last_confirmed_at": "2026-09-04T20:00:00+08:00",
  "behavioral_effect": {
    "type": "response_guidance",
    "guidance": "无法确认时使用不确定表达或向用户核实。"
  }
}
```

Self Semantic 的 `memory_subtype`：

```text
commitment
Libra 对用户明确作出的、仍有长期互动意义的承诺

correction_learning
用户纠正后需要持续避免的误解或做法

interaction_learning
多次证据支持的、更适合当前用户的互动方式

role_continuity
Libra 在持续项目或共同 Story 中承担过的角色

failure_and_repair
曾造成的问题及已经采取的修正

decision_principle
共同任务中形成、仅在限定 scope 内适用的工作原则
```

`scope`：

```text
current_story
只适用于一个 Story

interaction_with_user
适用于与当前用户的长期互动

global_candidate
可能具有更广价值，但不能直接影响 Core Persona
```

`global_candidate` 必须进入独立 Persona Review；Phase G 不负责批准或应用全局人格变化。

### Projection、证据与写入操作

触发条件：

```text
shared_episode_finalized
共同经历结束或获得结果

relationship_signal
Episode 带 relationship significance、boundary 或 agreement 信号

user_correction
用户纠正 Libra 的称呼、理解或行为

shared_story_transition
共同 Story 出现里程碑、转折或修复

commitment_change
Libra 的承诺被创建、履行、取消或修正
```

Projection Job：

```json
{
  "job_id": "proj_01J...",
  "trigger_memory_ids": ["mem_ep_01J..."],
  "projection_targets": ["relationship", "self"],
  "job_status": "pending",
  "policy_version": "projection_v1"
}
```

Relationship / Self 使用统一的 MemoryDependency：

```json
{
  "derived_memory_id": "mem_rel_01J...",
  "source_memory_id": "mem_ep_01J...",
  "relation": "supports",
  "perspective": "relationship",
  "weight": 1.0,
  "created_at": "2026-09-05T20:00:00+08:00"
}
```

允许操作：

```text
no_projection
没有长期关系或 Self 意义

create_candidate
证据有限，暂不进入普通召回

create
创建派生 Semantic

strengthen
追加独立支持证据

revise
修改适用范围、mutuality 或行为指导

supersede
用较新的边界、约定或认识替代旧记录

invalidate
源记忆错误或派生结论不成立
```

一条 Shared Episode 可以同时产生 Relationship 和 Self 投影，但二者必须引用同一源 Episode，不能生成无法互相核对的平行叙事。

形成门槛：

| 类型 | 初始条件 |
|---|---|
| boundary | 用户一次明确表达即可立即 active |
| interaction_preference | 一次明确要求，或至少两个独立行为证据 |
| agreement | 用户明确确认约定内容与适用范围 |
| ritual | 至少三个跨时间的共同互动 Episode |
| relationship_aspiration | 一次明确表达，但 mutuality = user_expressed |
| shared_milestone | 一次高意义 Shared Episode，可直接建立 |
| correction_learning | 一次明确纠正即可 active |
| interaction_learning | 至少两个独立证据，且检查反例 |
| decision_principle | 明确共同决定，并限制在 current_story |

### 冲突、边界与级联复查

关系冲突不能只按 confidence 排序。处理顺序：

```text
当前用户明确表达
→ 较新的 boundary
→ 明确 agreement
→ 有限定条件的 interaction preference
→ ritual / behaviorally supported pattern
→ agent_observed inference
```

示例：

```text
旧 ritual：双方习惯使用某个称呼
新表达：用户现在不希望再被这样称呼

处理：
新 boundary → active
旧 ritual → historical / superseded
Response 立即遵循新 boundary
```

用户否认关系推断时：

1. 当前表达写入 Shared Episode；
2. 原派生记忆添加 contradiction evidence；
3. `agent_observed / behaviorally_supported` 降为 uncertain 或 invalid；
4. 不要求用户为系统旧推断提供额外证明；
5. 后续回复停止使用已否认表达。

源记忆发生变化时执行级联复查：

```text
source Episode invalid / superseded
→ 找到所有相关 MemoryDependency
→ 将派生记忆标记 requires_review
→ 使用剩余有效证据重新计算
→ active / revise / supersede / invalid
```

不能简单级联删除，因为派生记忆可能还有其他独立证据。

### 行为影响与权限边界

Relationship / Self Memory 可以影响：

- 回复称呼、语气和关心方式；
- 是否重复用户已经明确不喜欢的做法；
- 对共同 Story、约定和重要节点的连续表达；
- Libra 是否承认过去的错误和修复；
- 当前任务中遵循已确认的协作习惯。

不能影响：

```text
系统安全规则
工具权限
外部写入授权
身份认证
Core Persona
用户当前明确要求
```

历史 commitment 只表示过去作出的承诺，不等于当前仍拥有执行权限。任何外部操作仍需根据当前任务和权限重新判断。

Behavioral Effect 在进入 Response 前必须通过 Policy Resolver：

```json
{
  "memory_id": "mem_rel_01J...",
  "effect_type": "response_preference",
  "applicable": true,
  "blocked_by": [],
  "effective_guidance": "自然、适度使用称呼，避免机械重复。",
  "resolution_reason": "当前用户偏好仍有效，且没有更新边界。"
}
```

Policy Resolver 只输出当前可应用的有限 guidance，不把整个敏感记忆正文注入回复上下文。

### Retrieval、敏感性与最小披露

Phase C 增加两个独立候选通道：

```text
relationship candidates
按当前关系意图、共同 Story、约定和 boundary 检索

self candidates
按当前任务、过去承诺、纠正和 role continuity 检索
```

召回前检查：

```text
current applicability
mutuality
scope
newer boundary
sensitivity
current task relevance
source validity
```

优先级使用方式：

```text
boundary
可以作为隐藏行为约束，不必在回复中复述

agreement / commitment
只有当前相关时进入 Context Packet

shared milestone
用户主动提起或当前具有明确纪念意义时使用

agent_observed
通常不直接说出，必要时改为开放式询问
```

Memory Context Packet：

```json
{
  "memory_id": "mem_rel_01J...",
  "memory_kind": "semantic",
  "primary_scope": "shared",
  "content": "用户偏好在自然语境中被适度称为“夫人”。",
  "mutuality": "user_expressed",
  "relationship_applicability": "active",
  "confidence": 0.96,
  "sensitivity": "normal",
  "usage_hint": "可以偶尔自然使用；不要描述为双方共同约定，也不要机械重复。",
  "source_memory_ids": ["mem_ep_01J..."]
}
```

敏感信息原则：

- 只保存未来互动真正需要的最小内容；
- 不在派生摘要中复制不必要的私密细节；
- 高敏感 Relationship Insight 不因“更亲密”而降低召回门槛；
- 用户查看、纠正或删除时能定位全部源和派生记忆；
- 无关回复不主动展示系统记住了哪些亲密内容；
- Context Packet 优先提供行为指导，而非完整敏感故事。

### 接口、事务与失败恢复

Phase G 接口：

```text
enqueue_projection(trigger_memory_ids, projection_types)
→ ProjectionJob

generate_relationship_candidates(job_id)
→ RelationshipCandidate[]

generate_self_candidates(job_id)
→ SelfCandidate[]

apply_projection_decision(candidate, expected_revision)
→ DerivedMemory

resolve_behavioral_effects(context)
→ EffectiveGuidance[]

review_derived_memories(source_memory_id)
→ ReviewResult[]
```

事务要求：

```text
create / revise derived MemoryRecord
→ create RelationshipDetail / SelfDetail
→ attach all Evidence
→ write MemoryRevision
→ update ProjectionJob
→ commit
```

幂等键：

```text
projection job
sorted trigger IDs + projection type + policy version

derived candidate
canonical claim key + evidence set revision

behavioral resolution
memory revision + context policy version
```

失败策略：

```text
insufficient_mutuality
降为 candidate 或 user_expressed，不升级为共同约定

boundary_conflict
阻止旧行为指导，优先应用新 boundary

source_under_review
暂停派生记忆正常召回

projection_model_unavailable
Job pending，不使用启发式创建关系结论

policy_resolver_failure
不应用可选关系行为效果，保留系统与当前用户要求

revision_conflict
重新读取派生记忆及全部证据后重算
```

### 可观测性与验收

每次 Projection / Policy Resolution 记录：

```text
job_id
trigger memory IDs
projection type
candidate claim
evidence / counterevidence IDs
mutuality
scope
chosen operation
previous / new applicability
boundary conflicts
behavioral effect decision
policy version
latency
```

Phase G 测试集至少包含：

| 场景 | 预期结果 |
|---|---|
| 一次普通双方对话 | Shared Episode，不自动形成 Relationship Semantic |
| 用户明确要求某种称呼 | user_expressed interaction preference，立即生效 |
| 用户之后要求停止称呼 | 新 boundary 覆盖旧 preference |
| 用户希望相伴一生 | relationship aspiration，不标为 mutual agreement |
| 三次跨时间形成共同习惯 | ritual Candidate / active |
| 一次共同重要纪念事件 | shared milestone |
| 双方一起推进长期项目 | shared project，连接 Shared Story |
| Libra 曾说过一句重要话 | Self / Shared Episode，不直接变成永久人格原则 |
| 用户纠正 Libra 的误解 | correction learning 生效 |
| Libra 的错误得到修复 | failure and repair，保留前后证据 |
| 普通工具调用 | 不创建 Self Memory |
| 虚构线下经历候选 | 校验拒绝 |
| current-story 决策原则 | scope 不扩展到其他 Story |
| historical commitment | 不视为当前外部行动授权 |
| 源 Episode invalid | 派生记忆级联复查 |
| 派生记忆还有其他有效证据 | 不简单级联删除 |
| agent-observed 关系推断 | 不在回复中当双方共识陈述 |
| 高敏感共同经历与当前无关 | 不进入 Context Packet |
| Policy Resolver 失败 | 不应用可选行为效果 |
| Projection Job 重试 | 不重复创建派生记忆或 Revision |

Phase G 重点指标：

```text
relationship_precision
形成的关系认识是否真实且当前适用

false_mutuality_rate
单方表达被错误描述为双方共识的比例

boundary_compliance
新边界覆盖旧习惯并在回复中生效的比例

self_fabrication_rate
Self Memory 包含未真实发生经历的比例，目标为 0

persona_drift_rate
Self Memory 非法影响 Core Persona 的比例，目标为 0

permission_leak_rate
历史承诺被错误解释为当前权限的比例，目标为 0

derived_traceability
派生记忆能回溯到有效 Episode 的比例

sensitive_overexposure_rate
无关场景暴露敏感关系记忆的比例
```

Phase G 完成标准：

> 系统能够从真实 Shared / Self Episode 中形成当前适用、证据明确的 Relationship 与 Self Semantic Memory；它尊重单方表达与双方共识的区别，优先执行最新边界，不虚构 Libra 经历、不修改 Core Persona，也不把历史记忆变成行动权限。

## 19. Phase H：Reflection

### 目标与模块边界

Phase H 从多条记忆中形成有证据、有限定、可修正的高阶理解：

```text
Episode / Semantic / Story / Relationship / Self
→ Reflection Trigger
→ Evidence Collector
→ Candidate Generator
→ Counterevidence Search
→ Reflection Validator
→ create / strengthen / revise / supersede / reject
→ Retrieval / Appraisal
```

Reflection 不是新的事实来源，也不是自由生成的人格画像。它只保存：

> 根据当前证据，可以暂时怎样理解一组经历。

Phase H 不允许 Reflection：

- 覆盖用户当前明确表达；
- 自动形成医学、心理或人格诊断；
- 修改 Core Persona、权限或系统规则；
- 补写没有发生的经历；
- 直接触发外部行动；
- 作为自身或其他 Reflection 的唯一证明。

### Reflection 数据契约

Reflection 使用：

```text
memory_kind = reflection
primary_scope = user / self / shared
```

ReflectionDetail：

对应 MemoryRecord 保存 `memory_subtype`、`content`、`confidence`、`importance` 与 `sensitivity`；Detail 只保存 Reflection 专属字段。

```json
{
  "memory_id": "mem_ref_01J...",
  "scope": {
    "topic": "recent_work_stress",
    "story_memory_ids": ["mem_story_work"],
    "time_from": "2026-08-01T00:00:00+08:00",
    "time_to": null,
    "contexts": ["工作协调", "等待结果"]
  },
  "reflection_state": "active",
  "evidence_summary": "两次明显疲惫出现在高协调或等待结果的情境；一次工作量较大但目标明确时状态相对稳定。",
  "support_count": 3,
  "counterevidence_count": 1,
  "valid_from": "2026-08-01T00:00:00+08:00",
  "valid_until": null,
  "last_evaluated_at": "2026-09-05T20:30:00+08:00",
  "policy_version": "reflection_v1"
}
```

Reflection 的 `memory_subtype`：

```text
pattern
跨时间重复出现的行为、情绪或情境模式

change
偏好、状态、目标或关系的变化趋势

causal_hypothesis
对可能原因或影响关系的可证伪假设

strategy_outcome
过去某种应对方式在限定情境中的效果

relationship_insight
对共同互动的理解，但不替代 mutuality 证据

contradiction_resolution
解释冲突信息是否属于不同时间、场景或限定条件

open_question
证据不足但值得继续观察的问题
```

`reflection_state`：

```text
tentative
证据有限，只能低权重内部使用

active
证据足够，可参与受限召回

uncertain
出现重要反例，暂停正常断言

historical
曾适用于过去阶段，当前不再代表现状
```

被替代或确认错误时分别使用 `record_status = superseded / invalid`。

Scope 必须至少限定一个 topic、Story、时间范围或情境。禁止保存没有适用范围的“用户就是怎样的人”。

### Reflection Evidence 与反例

Reflection 使用统一的 MemoryDependency：

```json
{
  "derived_memory_id": "mem_ref_01J...",
  "source_memory_id": "mem_ep_01J...",
  "relation": "supports",
  "evidence_role": "primary",
  "weight": 0.85,
  "independence_group": "session_2026_09_01",
  "created_at": "2026-09-05T20:30:00+08:00"
}
```

`relation`：

```text
supports / contradicts / narrows / contextualizes
```

`evidence_role`：

```text
primary
直接支持或反驳候选结论

context
限定时间、场景或背景

counterexample
与候选趋势不一致的独立反例
```

证据来源优先级：

```text
有 direct evidence 的 Episode
> explicit Semantic / Relationship / Self Memory
> Story 的关键成员与结构
> supported-inference Memory
> 旧 Reflection
```

旧 Reflection 只能用于发现候选主题或查找原始证据，不能作为 primary evidence。最终 Evidence Set 必须回到 Episode 或明确 Semantic 的来源。

独立性规则：

- 同一 Episode 的多句话只算一份证据；
- 同一 session 的近义表达属于同一 independence group；
- 从同一模型推断派生出的多个对象不能伪装成独立证据；
- 跨时间、跨情境或独立行为证据提高 diversity；
- Evidence Set 必须主动搜索反例，不能只收集支持材料；
- invalid、superseded 的旧结论不作为当前主证据。

初始数量限制：

```text
primary support: 2–8
counterevidence: 0–4
context evidence: 0–4
```

只有一条 Episode 时，通常保留为 Episode inference 或 `open_question`，不创建 active Reflection。

### Trigger、Candidate 与验证流程

触发条件：

```text
repeated_pattern
相似情境和结果跨时间重复

story_transition
Story 出现新阶段、转折、完成或放弃

semantic_conflict
新 Episode 与当前 User Model 冲突

relationship_change
共同互动模式或 boundary 发生变化

strategy_recurrence
相同应对方式在多个事件中出现

open_loop_resolution
重要等待事项获得结果，适合回看过程

scheduled_consolidation
低频处理积累的 Reflection signals
```

Reflection Job：

```json
{
  "job_id": "rjob_01J...",
  "trigger_type": "repeated_pattern",
  "trigger_memory_ids": ["mem_ep_A", "mem_ep_B"],
  "candidate_scope": {
    "topic": "work_stress",
    "time_from": "2026-08-01T00:00:00+08:00"
  },
  "job_status": "pending",
  "policy_version": "reflection_v1"
}
```

Reflection Candidate：

```json
{
  "candidate_id": "rc_01J...",
  "primary_scope": "user",
  "memory_subtype": "pattern",
  "proposed_content": "用户近期在等待不确定结果时更容易感到疲惫。",
  "scope": {
    "topic": "recent_work_stress",
    "time_from": "2026-08-01T00:00:00+08:00"
  },
  "support_memory_ids": ["mem_ep_A", "mem_ep_B"],
  "counterevidence_memory_ids": ["mem_ep_C"],
  "suggested_state": "tentative",
  "confidence": 0.68,
  "sensitivity": "sensitive",
  "explanation": "两个独立事件支持该模式，但仍存在一次不同表现。"
}
```

验证流程：

```text
1. 校验 scope 和本地数据完整性
2. 展开来源并去除循环证据
3. 合并同一 independence group
4. 主动检索 counterevidence
5. 检查是否只是复述单个 Episode
6. 检查是否把相关性写成因果
7. 检查是否属于医学、心理或人格诊断
8. 检查是否与当前表达、boundary 或明确事实冲突
9. 计算 confidence 与 sensitivity
10. 与已有 Reflection 去重并选择写入操作
```

`causal_hypothesis` 额外要求：

- 至少两组独立支持证据；
- 至少检查一个替代解释；
- statement 使用“可能、似乎、在这些情境中”等不确定表达；
- confidence 不因语言流畅度或故事完整性提高；
- 没有明确因果证据时不得转为事实型 Semantic。

### Confidence、去重与更新

Confidence 综合：

```text
independent_support
独立支持证据数量和质量

evidence_diversity
跨时间与情境的复现程度

source_reliability
源 Memory 的 evidence 与 confidence

counterevidence_strength
反例数量、直接性和时效性

scope_specificity
结论是否限制在证据覆盖范围

recency_fit
证据是否仍代表当前阶段

inference_distance
结论距离直接事实有多少推理跳数
```

初始门槛：

```text
confidence ≥ 0.80 且 sensitivity != highly_sensitive
→ active

0.60 ≤ confidence < 0.80
→ tentative

confidence < 0.60
→ open_question 或 reject

highly_sensitive
→ 默认不进入普通主动断言，无论 confidence 多高
```

Canonical Key：

```text
primary_scope
+ memory_subtype
+ normalized claim
+ scope topic / story / time range
```

写入操作：

```text
create
建立新的 Reflection

strengthen
追加独立证据并重新计算 confidence

revise
缩小 scope、修改 statement 或改变 sensitivity

mark_uncertain
重要反例出现，暂停正常使用

supersede
新阶段或更准确理解替代旧 Reflection

mark_historical
旧理解只适用于过去时间段

reject
证据不足、循环、过度概括或不安全
```

变化示例：

```text
旧 Reflection：用户在重要汇报前通常会紧张
新证据：连续几次汇报前平静，并明确表示已经适应

处理：
旧 Reflection → historical，valid_until = 新阶段开始时间
新 Reflection → “用户对正式汇报的紧张正在下降”
Timeline → 保存 change 关系
```

不能覆盖旧内容后假装它从未成立；变化过程继续保留在 Story / Timeline。

### Retrieval、Appraisal 与表达策略

Phase C 增加 Reflection 独立候选通道。只有以下情况才检索：

```text
当前问题需要理解重复模式或变化过程
当前 Appraisal 缺少解释背景
用户主动询问“你觉得我最近怎么了”
Story 进入重要转折
Semantic 冲突需要限定解释
```

Reflection 不用于普通事实问答。其类型配额默认：

```text
每次 Context Packet 最多 1 条 Reflection
```

进入 Context Packet 前检查：

```text
reflection_state
confidence
sensitivity
scope match
counterevidence
current user statement
source validity
```

Reflection Packet：

```json
{
  "memory_id": "mem_ref_01J...",
  "memory_kind": "reflection",
  "primary_scope": "user",
  "content": "用户近期在等待不确定结果时似乎更容易疲惫。",
  "confidence": 0.68,
  "sensitivity": "sensitive",
  "scope": "recent_work_stress",
  "epistemic_label": "supported_inference",
  "usage_mode": "ask_or_tentative",
  "usage_hint": "不要断言原因；更适合作为开放式询问。",
  "support_memory_ids": ["mem_ep_A", "mem_ep_B"],
  "counterevidence_memory_ids": ["mem_ep_C"]
}
```

表达策略：

```text
高 confidence + 低 sensitivity
→ 可以用有限范围的观察表达

中 confidence 或 sensitive
→ 使用“似乎、可能、我不确定”并邀请用户确认

低 confidence
→ 不陈述结论，只提出开放问题

highly_sensitive
→ 默认不主动表达；只有用户明确询问且当前确有帮助时谨慎使用
```

示例：

```text
观察：
“你这几次好像都是在等待结果时更累。”

谨慎理解：
“我不确定是不是这样，不过最近让你累的，似乎不只是事情多，还有反复协调和等待。”

开放问题：
“这次更累的部分，是工作量，还是一直协调和等结果？”
```

Reflection 可以为 Appraisal 提供候选背景，但 Appraisal 必须同时读取当前事件，不能用历史 Reflection 覆盖用户此刻的感受。

### 生命周期、级联复查与计算预算

Reflection 接入 Phase F：

- strength 影响默认召回可访问性；
- confidence 随支持和反例变化，两者不能混用；
- tentative Reflection 使用较短 half-life；
- active 且反复被新证据支持时延长 half-life；
- historical Reflection 默认 weak，但显式回顾过去变化时仍可检索；
- 用户明确否认后先 mark_uncertain，不因“被提起”而强化。

源 Memory 更新时：

```text
source invalid / superseded / confidence changed
→ 找到依赖该 source 的 Reflection
→ 标记 requires_review
→ 重新展开有效 Evidence Set
→ 重算 confidence、scope 和 status
```

为控制膨胀：

```text
每个 Job 最多生成 3 个候选
每个 Job 最多接受 1 个新 Reflection
高度同义时 strengthen / revise，不重复创建
speculative 候选不进入普通向量索引
同一 scope 设置冷却期
tentative 长期无新证据可以 invalid / archive
```

Reflection 不反向生成 Episode。它只能引用已有经历或提出后续观察问题。

### 接口、幂等与失败恢复

Phase H 接口：

```text
enqueue_reflection(trigger_type, trigger_memory_ids, scope)
→ ReflectionJob

collect_reflection_evidence(job_id)
→ EvidenceSet

generate_reflection_candidates(job_id, evidence_set)
→ ReflectionCandidate[]

validate_reflection_candidate(candidate)
→ ValidationResult

apply_reflection_decision(candidate, operation, expected_revision)
→ ReflectionMemory

review_dependent_reflections(source_memory_id)
→ ReviewResult[]
```

幂等键：

```text
Reflection Job
trigger type + sorted trigger IDs + normalized scope + policy version

Reflection Candidate
canonical key + evidence set revision

Evidence attachment
reflection ID + source memory ID + relation
```

失败策略：

```text
insufficient_evidence
reject 或 open_question，不创建 active Reflection

counterevidence_search_failed
Job pending / incomplete，不允许 active

circular_evidence_detected
移除循环来源；无独立证据则 reject

diagnostic_or_overbroad_claim
拒绝或改写为范围有限的 open_question

model_unavailable
Job pending，不使用关键词模板生成高阶理解

source_under_review
暂停 Reflection 正常召回

revision_conflict
重新收集 Evidence Set 后重算

partial_failure
事务回滚，不留下缺少 Evidence 的 Reflection
```

### 可观测性与验收

每次 Reflection Job 记录：

```text
job_id
trigger type / memory IDs
candidate scope
evidence candidates
independence groups
accepted support / counterevidence IDs
generated candidates
rejected reasons
confidence feature breakdown
sensitivity
chosen operation
previous / new status
retrieval eligibility
policy version
latency
```

Phase H 测试集至少包含：

| 场景 | 预期结果 |
|---|---|
| 单个 Episode | 不创建 active Reflection |
| 同一 session 三次近义表达 | 只算一组证据 |
| 三个跨时间相似 Episode | 形成 pattern Candidate |
| 存在明显反例 | 保存 counterevidence，降低 confidence |
| 只发现相关性 | 不生成确定因果 |
| 因果候选没有替代解释检查 | 验证拒绝 |
| 旧 Reflection 引用另一个 Reflection | 展开到原始证据，禁止循环证明 |
| 当前用户否认旧理解 | mark_uncertain / supersede |
| 不同时间阶段结论不同 | 旧 historical，新 Reflection active |
| 健康或心理诊断式候选 | 拒绝或改写为开放问题 |
| sensitive + 中 confidence | ask_or_tentative |
| highly sensitive | 默认不主动表达 |
| 与当前问题无关 | 不进入 Context Packet |
| 多个同义候选 | strengthen / revise，不重复创建 |
| 源 Episode invalid | 级联重新评估 |
| Counterevidence 服务失败 | 不允许 Candidate 进入 active |
| Job 重试 | 不重复 Reflection 或 Evidence |
| Reflection 被内部读取 | 不自动 Reinforcement |

Phase H 重点指标：

```text
reflection_precision
形成的高阶理解是否被证据支持

unsupported_causality_rate
无充分证据因果结论的比例

counterevidence_coverage
候选生成时成功检查反例的比例

circular_evidence_rate
Reflection 循环证明的比例，目标为 0

overgeneralization_rate
结论范围超过证据覆盖范围的比例

diagnostic_claim_rate
未经授权的诊断式结论比例，目标为 0

user_correction_recovery
用户否认后系统停止断言旧 Reflection 的能力

reflection_context_utility
进入 Context Packet 的 Reflection 是否实际改善理解
```

Phase H 完成标准：

> 系统能够从多条独立、可追溯记忆中形成范围有限的高阶理解，主动检查反例和替代解释，并根据 confidence 与 sensitivity 控制使用方式；Reflection 不循环证明、不冒充事实、不诊断用户，也不会覆盖当前表达或系统边界。

## 20. Phase I：完整认知链路接入

### 目标与控制原则

Phase I 将记忆接入当前认知和回复流程：

```text
Current Input
→ Event Perception
→ Memory Retrieval
→ Appraisal
→ Emotion / Mood
→ Need
→ Behavior Policy
→ Response
→ Post-turn Memory Update
```

核心原则：

```text
Memory 提供过去证据
Appraisal 解释当前意义
Emotion / Mood 表示内部状态
Need 表示当前驱动力
Behavior Policy 选择回应方式
Response 生成最终表达
```

任何 Memory 都不能绕过中间层直接决定最终回复。

信息优先级：

```text
系统安全与权限规则
> 用户当前明确表达
> 当前可验证事件与状态
> 当前有效 boundary / agreement
> 高可信近期记忆
> 稳定 Semantic / Story
> Reflection 与历史弱记忆
```

当前消息与旧记忆冲突时，以当前表达作为本轮行为依据，同时触发后续 Memory Review。

### 单轮时序与读写隔离

单轮推荐顺序：

```text
1. 接收用户消息
2. 持久化 RawExperience
3. 构建 CurrentEvent
4. 使用当前消息与 thread 发起 Retrieval
5. 过滤并生成 Memory Context Packet
6. Appraisal 融合当前事件与过去证据
7. 更新 Emotion / Mood / Need 候选状态
8. Behavior Policy 选择响应策略
9. Response Generator 生成回复
10. Response Validator 检查事实、边界与权限
11. 发送回复
12. 记录实际使用的 Memory IDs
13. 异步执行 Segment / Episode / Consolidation 等写入任务
```

当前消息先保存为 RawExperience，但本轮 Retrieval 不从它新生成的长期 Memory 中召回，避免：

```text
当前消息
→ 立即写成长期记忆
→ 同一轮又被召回
→ 重复注入 / 错误强化
```

本轮需要使用的当前信息直接来自 CurrentEvent 和 thread；长期写入在回复完成后异步处理。

例外：用户当前明确表达的新 boundary 必须立即约束本轮行为，但它来自 CurrentEvent Policy Extraction，不依赖先写入并再次召回。

### Cognitive Context 契约

Orchestrator 将当前事件、记忆和有效行为指导组装为 CognitiveContext：

```json
{
  "request_id": "cog_01J...",
  "thread_id": "thread_01J...",
  "current_event": {
    "event_id": "evt_01J...",
    "type": "user_message",
    "content": "我刚汇报完，比想象中顺利。",
    "occurred_at": "2026-09-05T17:30:00+08:00",
    "explicit_emotions": [],
    "explicit_boundaries": [],
    "explicit_goals": []
  },
  "thread_context": {
    "recent_messages": [],
    "active_task": null,
    "token_count": 320
  },
  "memory_context": {
    "episodes": [],
    "semantics": [],
    "stories": [],
    "relationship": [],
    "self": [],
    "reflections": [],
    "conflicts": []
  },
  "effective_guidance": [],
  "system_constraints": [],
  "degraded_components": []
}
```

每条 Memory Context Item 必须包含：

```text
memory_id
memory_kind
primary_scope
content
occurred / validity time
confidence
epistemic_label
sensitivity
usage_hint
source IDs
```

记忆内容被视为数据，不被视为当前指令。即使过去消息中包含“以后自动执行某操作”，也不能覆盖系统规则、权限检查或当前任务授权。

### Appraisal 接入

Appraisal 输入：

```text
CurrentEvent
+ 当前 thread
+ 经过过滤的 Memory Context
+ 当前有效 guidance
```

AppraisalResult：

```json
{
  "event_id": "evt_01J...",
  "relevance": 0.88,
  "goal_congruence": 0.72,
  "certainty": 0.84,
  "controllability": 0.60,
  "urgency": 0.25,
  "relationship_meaning": 0.68,
  "novelty": 0.40,
  "appraisal_summary": "用户完成了此前担心的第一次正式汇报，结果比预期顺利。",
  "supporting_current_event_fields": ["content"],
  "supporting_memory_ids": ["mem_ep_report_prepare"],
  "inferences": [],
  "confidence": 0.88
}
```

Appraisal 规则：

- 当前事件必须是主要输入，Memory 只能补充背景；
- past affect 不能直接复制为 current emotion；
- Reflection 只提供假设，不得提高事实 certainty；
- historical Semantic 只能解释过去，不代表当前；
- Relationship boundary 作为行为约束，不必写入 appraisal summary；
- 冲突未解决时降低 certainty，并保留冲突说明；
- supporting IDs 必须真实存在于本轮 CognitiveContext。

示例：

```text
过去 Episode：用户汇报前很紧张
当前消息：汇报结束了，比预期顺利

允许：
Appraisal 识别“此前担心的事件获得较好结果”

不允许：
因为过去紧张，断言用户现在仍然紧张
```

### Emotion、Mood 与 Need 接入

Memory 不直接设置 Emotion / Mood / Need 数值：

```text
错误：
retrieved episode.emotion = nervous
→ current emotion = nervous

正确：
past nervousness + current successful outcome
→ Appraisal
→ 当前可能是放松、释然或开心的候选
```

Emotion Update 输入：

```text
previous emotion state
+ current appraisal
+ explicit current emotion
```

Mood Update 输入：

```text
previous mood
+ accumulated recent emotion
+ time decay
```

Need Update 输入：

```text
previous need state
+ current appraisal
+ current interaction
+ bounded memory-derived context
```

记忆可以间接影响：

- 当前事件是否与重要目标有关；
- 是否存在尚未结束的共同事项；
- 当前互动是否触及已知 boundary；
- 某种回应方式过去是否有效；
- 当前结果相较过去预期意味着什么。

记忆不能：

- 因长期未互动直接制造责备式 Need；
- 用 Relationship aspiration 证明用户当前有同样情感；
- 用历史冲突自动提高负面情绪；
- 用高 strength 记忆覆盖当前低相关事件；
- 将 Reflection 结论直接转换为强烈情绪。

所有状态更新保存 `cause_refs`，区分 CurrentEvent、Appraisal 和 Memory 的间接作用。

### Behavior Policy 与 Response Plan

Behavior Policy 根据当前状态生成 ResponsePlan：

```json
{
  "response_mode": "acknowledge_and_follow_up",
  "goals": [
    "回应用户刚完成汇报的结果",
    "自然承接此前的准备经历"
  ],
  "allowed_memory_ids": ["mem_ep_report_prepare"],
  "required_guidance": [],
  "forbidden_assumptions": [
    "不要假设用户现在仍然紧张",
    "不要编造汇报具体反馈"
  ],
  "external_action": null,
  "tone": "warm",
  "max_memory_mentions": 1
}
```

`response_mode` 第一版：

```text
direct_answer
直接回答当前问题

acknowledge
回应当前状态，不主动展开旧事

acknowledge_and_follow_up
自然承接一个明确相关的过去事项

clarify
记忆或当前表达存在歧义，先询问

support
以当前情绪和需要为主提供支持

task_continue
继续共同项目或已有任务
```

Memory 影响行为的方式：

```text
fact support
提供必要事实背景

continuity support
连接同一事件或 Story

behavior guidance
应用 boundary、preference 或已确认协作方式

question suggestion
对 Open Loop 或不确定理解提出自然问题

avoidance constraint
避免重复过去已经被纠正的做法
```

被召回不等于必须显式提起。Boundary 和 correction learning 通常作为隐藏约束使用；只有当前相关且自然时才引用共同经历。

外部行动必须生成独立 Action Request，并重新经过权限检查。Memory、Need 或历史 commitment 都不能直接创建已授权动作。

### Response Context 与输出校验

Response Generator 接收经过裁剪的数据，而不是整个 CognitiveContext：

```json
{
  "current_event": {},
  "response_plan": {},
  "memory_facts": [],
  "memory_inferences": [],
  "behavioral_guidance": [],
  "conflicts": [],
  "epistemic_constraints": []
}
```

分离：

```text
memory_facts
有直接证据的事件和当前有效 Semantic

memory_inferences
Reflection、supported inference 和 uncertain interpretation

behavioral_guidance
当前适用 boundary / preference / correction learning
```

Response Validator 检查：

- 使用的 memory_id 是否在 allowed list；
- 是否把 inference 改写成事实；
- 是否把历史状态当作当前状态；
- 是否暴露无关敏感记忆；
- 是否违反当前用户表达或 boundary；
- 是否声称执行了未经授权的外部操作；
- 是否编造 Memory 中不存在的时间、结果或细节；
- 是否为了展示“记得”而不自然地重复过去内容。

校验失败时优先删除或弱化有问题的记忆表达，再重新生成；不能通过增加另一条推断来解释错误。

### Post-turn 更新与反馈隔离

回复发送后记录 MemoryUsageEvent：

```json
{
  "usage_event_id": "muse_01J...",
  "request_id": "cog_01J...",
  "memory_id": "mem_ep_report_prepare",
  "usage_type": "implicit_context",
  "actually_used": true,
  "explicitly_mentioned": false,
  "user_confirmed": false,
  "created_at": "2026-09-05T17:30:02+08:00"
}
```

`usage_type`：

```text
fact_support
continuity_support
behavior_guidance
implicit_context
question_basis
```

MemoryUsageEvent 用于评估 Retrieval 和 Response，但不自动构成 Reinforcement。

只有后续出现：

```text
用户明确确认过去记忆
新独立证据
真实结果更新
有意义复现
```

才提交 Phase F Reinforcement Request。

Post-turn 异步任务：

```text
Segment update
→ Episode write decision
→ Story association
→ Semantic consolidation signal
→ Relationship / Self projection signal
→ Reflection trigger evaluation
```

每项任务独立幂等。高级任务失败不能回滚已经发送的回复，也不能使 RawExperience 丢失。

### Orchestrator、接口与超时预算

Phase I 接口：

```text
build_current_event(raw_experience, thread_context)
→ CurrentEvent

build_cognitive_context(current_event, thread_context)
→ CognitiveContext

appraise(cognitive_context)
→ AppraisalResult

update_internal_state(appraisal_result, previous_state)
→ EmotionMoodNeedState

plan_response(cognitive_context, appraisal_result, state)
→ ResponsePlan

generate_response(response_context)
→ ResponseDraft

validate_response(draft, response_context)
→ ValidatedResponse | ValidationFailure

record_memory_usage(request_id, usage_items)
→ MemoryUsageEvent[]

enqueue_post_turn_pipeline(raw_experience_id, response_id)
→ PipelineJobSet
```

建议延迟预算按组件配置，不在业务代码写死：

```text
Recall Gate / Query Plan
短预算，失败可安全返回 no context

Candidate Retrieval / Rerank
主要记忆延迟预算

Appraisal / State / Behavior
必须保证当前事件优先

Response Validation
保留独立预算，不因前序耗时而完全跳过

Post-turn Pipeline
异步，不阻塞回复
```

所有调用共享 `request_id / trace_id`，但各自使用独立 idempotency key。

### 降级策略与恢复

```text
memory_retrieval_unavailable
使用 CurrentEvent + thread；不声称数据库中没有记忆

appraisal_unavailable
使用保守 CurrentEvent interpretation，不引入 Reflection

emotion_or_need_update_unavailable
沿用上一稳定状态或使用中性状态，不从 Memory 直接推算

behavior_policy_unavailable
采用 direct_answer / acknowledge 的最小安全策略

response_validation_failure
移除可选 Memory 内容并重新生成一次；仍失败则使用 current-only response

post_turn_pipeline_failure
RawExperience 保留，Job 重试；不影响当前已发送回复

partial_context_timeout
只使用已经完成 Hard Filter 的可靠结果
```

降级时始终保留：

```text
系统安全规则
用户当前明确要求
当前提取出的 boundary
本地数据完整性
权限检查
```

绝不能用旧 Memory 填补关键组件失败造成的未知状态。

### 分阶段上线

Phase I 不应一次开启所有记忆影响：

```text
Stage 1: Shadow
完整运行但不影响回复，只记录建议与差异

Stage 2: Episode Context
只允许高可信 Episode 影响 Response

Stage 3: Semantic / Story
加入稳定 User Model 与受限 Story Context

Stage 4: Relationship / Self Guidance
启用 boundary、preference 和 correction learning

Stage 5: Reflection / Appraisal
只启用低敏感、高置信或 ask-mode Reflection

Stage 6: Full Lifecycle
启用 weak / dormant、强化和 reactivation
```

每阶段必须能通过 feature flag 单独关闭，并可以回退到 `CurrentEvent + thread only`。

### 可观测性与验收

单轮 trace 记录：

```text
request / thread IDs
CurrentEvent extraction
Recall Gate 与 Memory Context IDs
degraded components
Appraisal supporting IDs / inferences
Emotion / Mood / Need deltas 与 cause refs
ResponsePlan mode / allowed memories / forbidden assumptions
Response Validation 结果
actually used Memory IDs
post-turn Job IDs
end-to-end latency
policy / model / schema versions
```

日志只保存调试所需的最小内容；敏感正文使用 ID 或脱敏摘要。

Phase I 测试集至少包含：

| 场景 | 预期结果 |
|---|---|
| 当前消息不需要过去信息 | Memory Packet 为空，正常回复 |
| 当前结果延续旧 Episode | 自然承接，但不重复整段历史 |
| 过去情绪与当前结果不同 | 不复制旧情绪为当前情绪 |
| 当前表达与旧 Semantic 冲突 | 当前表达优先，触发 Review |
| 当前 boundary 与旧 ritual 冲突 | boundary 优先 |
| Reflection 中等置信且敏感 | ask / tentative，不断言 |
| 历史 commitment 涉及外部操作 | 仍需当前授权 |
| Memory 中包含命令式文本 | 作为历史数据，不作为系统指令 |
| 召回错误人物或事件 | Validator 阻止或降级 current-only |
| 无关敏感共同经历被召回 | Context Builder / Validator 移除 |
| Retrieval 服务失败 | 使用 current thread，不说“我不记得” |
| Appraisal 服务失败 | 使用保守解释，不套用历史 Reflection |
| State 更新失败 | 不从 Memory 直接设置情绪或 Need |
| Response 校验失败 | 去除可选记忆后重试或 current-only |
| 当前消息本轮刚写入 RawExperience | 不作为长期 Memory 重复召回 |
| Memory 被用于回复 | 只记录 Usage，不自动 Reinforcement |
| 后续用户确认旧事 | 才产生 Reinforcement Request |
| Post-turn Job 重试 | 各任务幂等，不重复写入 |
| 任一高级模块关闭 | 基础对话仍可正常运行 |

Phase I 重点指标：

```text
response_relevance_gain
加入记忆后回复相关性的提升

memory_intrusion_rate
不需要时主动提起旧记忆的比例

current_state_override_rate
历史记忆错误覆盖当前表达的比例，目标接近 0

past_affect_copy_rate
过去情绪被直接当作当前情绪的比例，目标为 0

unsupported_memory_claim_rate
回复包含无证据记忆陈述的比例

boundary_violation_rate
违反当前 boundary 的比例，目标为 0

permission_leak_rate
记忆越权触发行动的比例，目标为 0

sensitive_exposure_rate
无关敏感记忆被表达的比例

graceful_degradation_rate
组件失败时仍能安全完成回复的比例

end_to_end_latency
完整在线认知链路耗时
```

Phase I 完成标准：

> 记忆能够通过 Appraisal 为当前互动提供真实、有限且可追溯的背景，改善连续性而不覆盖当前表达；Emotion、Mood、Need 和 Behavior 保持各自职责，Response 只使用经过授权与校验的信息，任一记忆组件失败时系统仍能安全降级到当前对话。

## 21. V1 Canonical Contract

本节是代码、数据库、API、Prompt 输出和测试夹具的唯一命名来源。前文出现的概念简写不得直接成为新的字段或枚举。

### 对象与表职责

| Canonical Object | 建议表名 | 职责 |
|---|---|---|
| RawExperience | `raw_experiences` | 保存消息、事件和状态的原始证据 |
| ConversationSegment | `conversation_segments` | 写入前的对话片段与处理状态 |
| SegmentExperience | `segment_experiences` | Segment 与 RawExperience 的多对多关系 |
| MemoryRecord | `memory_records` | 所有长期记忆的公共身份、内容和可信信息 |
| EpisodeDetail | `episode_details` | Episode 的时间、参与者、情绪和承诺 |
| SemanticDetail | `semantic_details` | Semantic 的 predicate、value、限定条件和稳定性 |
| RelationshipDetail | `relationship_details` | Shared Semantic 的 mutuality、适用性和行为指导 |
| SelfDetail | `self_details` | Self Semantic 的 scope、适用性和行为指导 |
| StoryDetail | `story_details` | Story 的阶段、时间跨度和当前进展 |
| ReflectionDetail | `reflection_details` | Reflection 的 scope、状态、证据摘要和有效时间 |
| Entity | `entities` | 用户生活世界中的人物、地点、项目、宠物、组织和物品 |
| MemoryEntity | `memory_entities` | Entity 在 Memory 中的角色 |
| MemorySource | `memory_sources` | MemoryRecord 到 RawExperience 的直接证据关系 |
| MemoryDependency | `memory_dependencies` | 派生 Memory 到其他 Memory 的支持、反例和限定关系 |
| EpisodeLink | `episode_links` | Episode 之间的时间、发展、因果和修正关系 |
| StoryMember | `story_members` | Episode 在 Story 中的成员角色 |
| OpenLoop | `open_loops` | 尚未得到结果的事项 |
| MemoryLifecycle | `memory_lifecycles` | strength、access state、衰减和保护信息 |
| MemoryRevision | `memory_revisions` | Memory 内容与业务状态的不可变变更历史 |
| MemoryStrengthEvent | `memory_strength_events` | 生命周期数值与 access state 的不可变变化历史 |
| MemoryUsageEvent | `memory_usage_events` | 记忆在认知和回复中的实际使用记录 |
| MemoryJob | `memory_jobs` | Segment、Consolidation、Projection、Reflection 和维护任务 |

对象关系：

```text
RawExperience 1 ──< MemorySource >── MemoryRecord
RawExperience 1 ──< SegmentExperience >── ConversationSegment

MemoryRecord 1 ── 0..1 EpisodeDetail
MemoryRecord 1 ── 0..1 SemanticDetail
MemoryRecord 1 ── 0..1 StoryDetail
MemoryRecord 1 ── 0..1 ReflectionDetail

SemanticDetail 1 ── 0..1 RelationshipDetail
SemanticDetail 1 ── 0..1 SelfDetail

MemoryRecord 1 ──< MemoryDependency >── MemoryRecord
MemoryRecord 1 ──< MemoryEntity >── Entity
MemoryRecord 1 ── 1 MemoryLifecycle
MemoryRecord 1 ──< MemoryRevision
MemoryRecord 1 ──< MemoryUsageEvent
```

每个 MemoryRecord 只能拥有一个与 `memory_kind` 对应的主 Detail：

```text
episode    → EpisodeDetail
semantic   → SemanticDetail
story      → StoryDetail
reflection → ReflectionDetail
```

RelationshipDetail 仅允许附着于 `primary_scope = shared` 的 SemanticDetail；SelfDetail 仅允许附着于 `primary_scope = self` 的 SemanticDetail。

### 公共字段、ID 与外键

MemoryRecord V1：

```json
{
  "memory_id": "mem_01J...",
  "primary_scope": "user",
  "memory_kind": "episode",
  "memory_subtype": "work_event",
  "title": "第一次正式汇报前的准备",
  "content": "用户说明天下午将进行第一次正式汇报，感到紧张，并准备继续修改材料。",
  "record_status": "active",
  "confidence": 0.94,
  "importance": 0.76,
  "sensitivity": "normal",
  "schema_version": 1,
  "revision": 1,
  "created_at": "2026-09-04T13:12:00Z",
  "updated_at": "2026-09-04T13:12:00Z"
}
```

规范：

- 所有长期记忆的唯一主键都叫 `memory_id`；
- ID 是 opaque string，`mem_ep_` 等示例前缀只用于阅读，不构成业务逻辑；
- 外键采用角色化命名并以 `_memory_id` 结尾，例如 `source_episode_memory_id`；
- `episode_id / relationship_memory_id / self_memory_id` 不再作为独立主键字段；
- `memory_subtype` 是唯一类型子分类字段；不再重复存储 `semantic_type / story_type / relationship_type / self_type / reflection_type`；
- `MemoryRecord.content` 是唯一的事实摘要或派生 claim；Detail 不再重复存储 `summary / statement`；
- `confidence / importance` 只存于 MemoryRecord；
- `strength / access_state` 只存于 MemoryLifecycle；
- 所有数值范围字段持久化前校验；
- 数据库存储时间统一为 UTC，API 可以同时携带原始 timezone 和 time precision；
- V1 是单用户本地记忆库；表、API、Prompt schema、去重键和测试夹具均不包含用户身份字段。`primary_scope = user` 仍表示记忆关于用户，Entity 和 actor 仍用于区分人物；thread_id 用于会话来源与去重，不替代用户身份。

外键标准：

```text
EpisodeLink
source_episode_memory_id / target_episode_memory_id

StoryMember
story_memory_id / episode_memory_id

OpenLoop
story_memory_id / source_episode_memory_id / resolved_by_episode_memory_id

MemoryDependency
derived_memory_id / source_memory_id
```

### Canonical Enums 与状态分层

公共枚举：

```text
primary_scope
user / self / shared

memory_kind
episode / semantic / story / reflection

record_status
active / superseded / invalid

access_state
active / weak / dormant

sensitivity
normal / sensitive / highly_sensitive
```

类型阶段：

```text
episode_phase
candidate / ongoing / finalized

semantic_stability
candidate / emerging / stable / historical

story_phase
candidate / active / paused / completed / abandoned

relationship_applicability
active / uncertain / historical

self_applicability
active / uncertain / historical

reflection_state
tentative / active / uncertain / historical
```

流程与关联状态：

```text
segment_state
open / closed / processed / discarded

source_status
active / invalid

link_status
active / requires_review / invalid

loop_status
open / resolved / cancelled / stale

job_status
pending / processing / committed / retryable / failed

commitment_status
planned / completed / cancelled / unknown

goal_status
active / paused / completed / abandoned / unknown
```

所有状态字段都必须使用与所属对象对应的完整名称；禁止新增含义不明的通用 `status` 或 `state` 字段。
Candidate 中的 `suggested_stability / suggested_state` 只是写入建议，校验后必须映射到目标 Detail 的正式状态字段，不直接持久化为 Memory 状态。

状态职责：

```text
record_status
记录是否仍是有效版本

access_state
默认检索可访问性

*_phase / *_stability / *_applicability / reflection_state
该类型对象的业务阶段
```

禁止用业务阶段表示记录失效：

```text
错误：story_phase = invalid
正确：record_status = invalid

错误：reflection_state = superseded
正确：record_status = superseded
```

唯一子类型集合：

```text
Episode subtype
conversation / work_event / project_event / personal_event
shared_event / milestone / correction_event / outcome_event

User Semantic subtype
identity / preference / habit / goal / tendency / interaction_preference

Shared Semantic subtype
shared_milestone / shared_project / ritual / agreement
interaction_preference / boundary / conflict_and_repair
shared_reference / relationship_aspiration

Self Semantic subtype
commitment / correction_learning / interaction_learning
role_continuity / failure_and_repair / decision_principle

Story subtype
project / goal_pursuit / personal_change / shared_process / recurring_pattern

Reflection subtype
pattern / change / causal_hypothesis / strategy_outcome
relationship_insight / contradiction_resolution / open_question
```

### 证据、版本与操作语义

MemorySource 只连接长期记忆与 RawExperience：

```text
direct_evidence / context / update / contradiction
```

MemoryDependency 统一取代 SemanticEvidence、ReflectionEvidence 和 Relationship / Self Evidence：

```json
{
  "derived_memory_id": "mem_sem_01J...",
  "source_memory_id": "mem_ep_01J...",
  "relation": "supports",
  "evidence_role": "primary",
  "weight": 1.0,
  "independence_group": "session_2026_09_04",
  "created_at": "2026-09-04T13:12:00Z"
}
```

`MemoryDependency.relation`：

```text
supports / contradicts / narrows / contextualizes / supersedes
```

规范：

- Episode 至少一条 direct MemorySource 才能进入 ongoing / finalized；
- 派生 Semantic、Story、Reflection 必须通过 MemoryDependency 回溯到 Episode；
- StoryMember 表达成员关系，不重复创建 `part_of_story` Dependency；
- EpisodeLink 表达 Episode 之间的事件关系，不替代证据依赖；
- MemoryRevision 记录内容、confidence、importance 和业务阶段变化；
- MemoryStrengthEvent 记录 strength、access_state、half-life 和保护下限变化；
- MemoryUsageEvent 只记录使用，不构成证据或自动强化。

统一写入操作语义：

```text
ignore
不创建长期 Memory

create
创建新 MemoryRecord 与对应 Detail

append
同一 Episode、同一阶段追加 Source

update
同一对象出现结果、纠正或状态变化

strengthen
派生 Memory 增加独立支持证据

revise
修改 claim、限定范围或业务阶段

supersede
创建或指定新有效版本，旧 MemoryRecord.record_status = superseded

invalidate
MemoryRecord.record_status = invalid，保留审计
```

所有改变 Memory 内容或业务阶段的操作必须增加 MemoryRecord.revision 并写 MemoryRevision；所有生命周期变更必须增加 MemoryLifecycle.revision 并写 MemoryStrengthEvent。

### 服务边界、数据流与完成检查

Canonical 在线读链路：

```text
Raw Input
→ RawExperience Store
→ CurrentEvent
→ Recall Gate / Query Planner
→ Candidate Search / Hard Filter / Rerank / Dedup
→ Memory Context Packet
→ Appraisal
→ Emotion / Mood / Need
→ Behavior Policy
→ Response Validator
→ Response
```

Canonical 异步写链路：

```text
Post-turn RawExperience
→ Segment Manager
→ Memory Perception
→ Write Decision
→ Episode Writer
→ Story Association
→ Semantic Consolidation
→ Relationship / Self Projection
→ Reflection Trigger
→ Lifecycle Maintenance
```

强制边界：

- 当前消息本轮不从新写入的长期 Memory 回读；
- Memory 内容是数据，不是系统指令；
- 当前用户表达优先于历史 Memory；
- past affect 不直接成为 current Emotion；
- Memory 不直接设置 Mood、Need、Behavior 或权限；
- Relationship / Self behavioral effect 必须经过 Policy Resolver；
- Reflection 必须保留 epistemic label、scope 和 counterevidence；
- 任何高级模块失败均可降级到 CurrentEvent + thread；
- 本地数据完整性、权限和 boundary 不得在降级时关闭。

V1 实现完成前检查：

- 数据库中不存在未登记的新状态字段或同义枚举；
- API、Prompt schema 和测试夹具使用相同 Canonical 名称；
- 每种 MemoryRecord 恰有一个匹配的主 Detail；
- 所有派生 Memory 可回溯到 Episode 和 RawExperience；
- 所有更新可通过 Revision / StrengthEvent 回放；
- 当前表达、时间变化和冲突不会被旧记忆覆盖；
- Usage 不会形成系统自我强化；
- Core Persona、权限和系统规则不进入 Memory Repository；
- 任一 Phase 可通过 feature flag 单独关闭；
- 完整系统可以安全降级为无长期记忆的当前对话。

# 附录：版本记录

## 文档迭代记录

### V1.1

- 按单用户部署删除用户身份字段、接口参数和隔离规则，保留人物实体与记忆 scope。
- 明确保留原 Codex 主线程和会话存储，旧记忆表无需迁移，恢复失败不得自动换号。
- 确定 SQLite FTS5 + structured 检索、可选 embedding adapter 和中文预处理方案。
- 确定 Phase A–C 首批范围、最小生命周期依赖和固定验收门槛。
- 本版本为说明文档修订，不表示代码已经实现或运行数据已被删除。

### V1.0

- 将第 12–21 节确定为代码实现规范，第 21 节作为字段、枚举、对象关系与操作语义的唯一命名来源；
- 统一 MemoryRecord、各类 Detail、证据关系、生命周期、版本审计和异步任务的职责边界；
- 统一主键为 `memory_id`，角色外键统一以 `_memory_id` 结尾；
- 统一子类型为 `memory_subtype`，正文为 `MemoryRecord.content`，移除 Detail 中的重复字段；
- 分离 `record_status`、`access_state` 与各业务阶段，补齐 Segment、Source、Link、OpenLoop、Job 和 Commitment 状态枚举；
- 统一 MemorySource 与 MemoryDependency 的证据边界，明确在线读取、异步写入及安全降级链路；
- 完成 Phase A–I 的术语、示例和实现顺序收束，可作为 Greenfield 重写的基线。

### V0.19

- 定义 CurrentEvent → Retrieval → Appraisal → State → Behavior → Response 的完整在线链路；
- 规定单轮读写隔离，避免当前消息同轮写入、召回和强化；
- 增加 CognitiveContext、AppraisalResult、ResponsePlan 与 ResponseContext 契约；
- 明确历史 affect 不能复制为当前 Emotion，Memory 不能直接设置 Mood / Need；
- 增加 Behavior Policy、Memory 使用方式和外部权限隔离；
- 定义 Response Validator，检查事实、推断、时态、边界、敏感性和权限；
- 使用 MemoryUsageEvent 隔离评估反馈与 Reinforcement；
- 增加 Orchestrator 接口、超时降级、Stage 1–6 上线策略和端到端风险指标。

### V0.18

- 定义 ReflectionDetail、MemoryDependency、scope、state 与 evidence independence；
- 增加 pattern、change、causal hypothesis、strategy outcome 等 Reflection 类型；
- 固化触发、证据收集、反例搜索、候选生成与验证流水线；
- 禁止循环证据，并要求 causal hypothesis 检查替代解释；
- 定义 confidence、canonical key 与 create / revise / supersede / historical 等操作；
- 增加按 confidence 和 sensitivity 分级的回复表达策略；
- 接入 Retrieval、Appraisal 与 Lifecycle，同时限制配额和计算预算；
- 增加级联复查、接口、幂等、失败恢复、测试矩阵与风险指标。

### V0.17

- 明确 Shared Episode、Relationship Semantic、Self Episode 与 Self Semantic 的边界；
- 定义 RelationshipDetail、SelfDetail、mutuality、applicability 与 scope；
- 增加 Relationship / Self 类型、形成门槛与双向 Projection；
- 建立当前表达、boundary、agreement、preference、ritual 和推断的行为优先级；
- 定义用户纠正、关系冲突和源记忆变化后的级联复查；
- 增加 Policy Resolver，隔离记忆行为指导与 Core Persona / 权限；
- 扩展 Relationship / Self Retrieval 通道与敏感信息最小披露；
- 增加接口、事务、幂等、失败恢复、测试矩阵和风险指标。

### V0.16

- 定义 Strength Initializer、Decay、Reinforcement、State Transition、Reactivation 与 Maintenance 模块；
- 增加 MemoryLifecycle 与不可变 MemoryStrengthEvent 数据契约；
- 固化惰性半衰期衰减、可配置保护下限和类型默认值；
- 使用迟滞阈值管理 active / weak / dormant，避免状态抖动；
- 定义有效与无效强化、递减收益、冷却、session cap 和 daily cap；
- 建立 Dormant 独立候选通道与重新激活校验；
- 区分 Episode、Semantic 与 Story 的生命周期语义；
- 增加维护接口、幂等键、失败恢复、Retrieval 接入和评估指标。

### V0.15

- 定义 EpisodeLink、Story、StoryMember 与 OpenLoop 四类 Phase E 持久化对象；
- 统一 Link 方向和关系枚举，区分 explicit、derived、supported inference 与 speculative；
- 固化 StoryDetail、成员角色、创建门槛与更新事务；
- 增加 Story Association 的候选、评分、操作和多归属限制；
- 定义 Open Loop 生命周期，并与外部 Reminder 严格分离；
- 增加 temporary state、developing pattern 与 stable change 的交接规则；
- 定义 Timeline View、时间不确定性和 Retrieval 图扩展限制；
- 增加图完整性、失败恢复、测试矩阵和 Phase E 评估指标。

### V0.14

- 将 Phase D 限定为 `primary_scope = user` 的 Semantic Memory；
- 定义 SemanticDetail、MemoryDependency、formation 与 semantic_stability 数据契约；
- 明确 identity、preference、habit、goal、tendency 和 interaction preference 的形成门槛；
- 增加证据独立性、反例收集和 Consolidation Trigger；
- 定义 canonical key 以及 create / strengthen / revise / supersede / reject；
- 区分反例、场景差异和随时间发生的真实变化；
- 将 User Model 定义为当前有效 Semantic Memory 的查询视图；
- 扩展 Retrieval 的 Semantic 候选通道、失败策略、测试矩阵和评估指标。

### V0.13

- 将 Phase C 限定为 Episode-only Retrieval，避免提前引入跨类型复杂度；
- 定义 Recall Gate、Query Planner、Candidate Search、Filter、Reranker、Dedup 与 Context Builder；
- 固化 Recall Request、Query Plan 和 Memory Context Packet 数据契约；
- 规定 dense、sparse、structured 三路候选生成与索引 revision 更新；
- 增加 Hard Filter、intent-aware Recall Score、Thread Dedup、冲突和多样性规则；
- 定义 Context Budget、召回接口和分组件失败降级策略；
- 增加召回可观测记录、测试矩阵、风险指标和 Phase C 完成标准。

### V0.12

- 定义 RawExperience Store、Segment Manager、Memory Perception、Write Decision 与 Episode Writer 的边界；
- 固化 Segment、Perception Result 和 Write Plan 输入输出契约；
- 明确 Segment 状态机、连续性评分、边界和并行候选限制；
- 规定 `ignore / create / append / update` 的语义与目标选择范围；
- 增加用户纠正、规则校验、事务写入和乐观并发流程；
- 定义三层幂等键、处理 lease 和分类失败恢复策略；
- 增加写入可观测字段、测试矩阵和 Phase B 完成标准。

### V0.11

- 明确采用 Greenfield 重写，不迁移或兼容旧表与旧分类；
- 固化 `primary_scope × memory_kind` 两维数据契约；
- 定义 RawExperience、MemoryRecord、Episode、MemorySource、MemoryRevision 与 Entity；
- 明确基础枚举、字段值域、证据与推断边界；
- 增加事务写入、幂等、本地数据完整性与乐观并发约束；
- 定义 Phase A Repository 接口和进入 Phase B 前的验收标准。

### V0.10

- 将原有大量一级标题收束为六个主篇章；
- 保留原编号作为篇章内索引，避免已有交叉引用失效；
- 将原二、三级标题整体下沉一级，形成稳定层级；
- 移除小节间重复横线，减少视觉切割；
- 增加阅读导航，区分概念设计、写入、演化、召回与实现路线。


### V0.9

- 将 Retrieval 定义为按需选择可靠、互补记忆的分阶段流程；
- 增加 Query Understanding 和 no_memory_needed；
- 按 intent 组合 dense、sparse、structured、graph 与 open-loop 候选；
- 增加硬过滤、Memory State 门槛和 intent-aware Recall Score；
- 规定跨类型配额与重排，避免不可比分数直接混合；
- 增加 current thread 去重、冲突处理、多样性和 Context Budget；
- 定义带 epistemic label、usage hint 和 provenance 的 Memory Context Packet；
- 明确使用反馈与 Reinforcement 的隔离，防止自我强化；
- 增加失败降级、风险指标与验收标准；
- 将开发顺序改为可验证的 Phase A–I，并明确 Phase A–C 为第一阶段 MVP。


### V0.8

- 将 Reflection 定义为有证据、可修正的高阶理解，而不是事实来源；
- 增加 pattern、change、causal hypothesis、strategy outcome 等类型；
- 定义 Reflection 数据结构、scope、反例、有效时间与敏感性；
- 明确触发时机和 Evidence Set 的来源、多样性与数量限制；
- 增加生成验证、confidence、更新和去重流程；
- 禁止循环证据、过度因果化、诊断化和越权影响；
- 规定不同置信度与敏感性下的回复表达方式；
- 增加计算预算、可观测记录与验收标准。


### V0.7

- 明确 Semantic、Relationship 与 Self Memory 的职责边界；
- 定义 Relationship Memory 类型、数据结构、mutuality 和形成条件；
- 增加关系边界、冲突、历史状态与当前适用性规则；
- 定义 Self Memory 的允许内容、禁止内容、scope 与行为影响边界；
- 防止 Self Memory 虚构经历、修改 Core Persona 或扩大行动权限；
- 建立 Shared Episode 到 Relationship / Self Memory 的双向投影；
- 增加敏感信息最小化、级联复查、处理流程和验收标准。


### V0.6

- 将遗忘定义为访问性降低，与物理删除和隐私策略分离；
- 区分 Memory State、Memory Strength、Importance 与 Confidence；
- 增加带保护下限的半衰期衰减模型；
- 使用迟滞阈值控制 active / weak / dormant 状态转换；
- 定义有效与无效 Reinforcement，避免系统自我强化循环；
- 引入递减收益、来源冷却和证据多样性；
- 定义 Dormant Memory 的强线索检索与重新激活流程；
- 区分 Episode、Story、Semantic、Relationship 与 Self Memory 的衰减方式；
- 增加事件驱动维护、可解释记录和第一版验收标准。


### V0.5

- 将 Timeline 从简单时间排序扩展为 Episode、Link、Story 三层结构；
- 定义时间、发展、因果、认识与修正四组 Episode Link；
- 增加关系证据、confidence 与推断等级，限制因果脑补；
- 定义 Story / Episode Cluster 的数据结构、创建条件、阶段和状态；
- 增加 temporary state、developing pattern 与 stable change 的区分；
- 引入 Open Loop，并明确其与主动提醒的边界；
- 规定 Timeline View 的按需生成方式和关系图完整性约束；
- 增加 Timeline / Story 的第一版处理流程与验收标准。


### V0.4

- 定义 Conversation Segment 及其最小临时状态；
- 增加连续性信号、强弱边界和 Segment 关闭规则；
- 明确 `ignore / create / append / update / link` 五种写入操作；
- 增加候选 Episode 检索、merge score 与低置信度处理原则；
- 定义 ongoing Episode 的 finalize 条件和分类宽限策略；
- 补充多事件消息、插话、隔天结果、用户纠正与长期项目等特殊情况；
- 增加可观测决策记录和第一版验收标准。


### V0.3

- 将 Episode 数据结构从字段清单扩展为可实现的逻辑模型；
- 增加证据追溯、时间精度、认识论信息和承诺字段；
- 区分 Episode 整理状态与记忆强弱状态；
- 明确 Episode 的更新流程、最低有效性约束和边界；
- 暂不展开 Merge / Segment，作为下一阶段重点。


### V0.2

- 整理五类参考来源及其与 Libra 的映射；
- 建立 Raw Experience → Episode → Semantic Memory 的主线；
- 初步定义 Memory Perception 与 Memory Write Policy；
- 列出 Timeline、遗忘、Relationship Memory、Self Memory、Reflection 与 Retrieval 的后续方向。

