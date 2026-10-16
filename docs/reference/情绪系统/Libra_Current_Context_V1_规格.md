# Libra Current Context V1 规格

本文档是 Libra V1 中 `CurrentContextSnapshot` 的字段、构建规则、时效规则和下游投影规则的唯一真值。

其他模块不得把临时字段直接加入 Current Context。需要扩展时，应先更新本文档，再同步修改构建器、JSON Schema 和对应模块的输入契约。

---

## 1. 目标

Current Context 用来回答：

> 当前 Event 发生时，现在是什么局面？

它把分散在活动状态、近期互动、时间、关系近况和现实约束中的短期信息，整理成一个统一、可追溯、具有时效性的情境快照。

Current Context 的目标是让下游模块能够：

1. 判断同一个 Event 在当前情境下意味着什么；
2. 判断过去获知的短期状态现在是否仍然有效；
3. 区分已知事实、规则推导和不确定推测；
4. 避免在用户忙碌、休息或不希望被打扰时采取不合适的主动行为；
5. 根据当前现场调整 Need 判断和表达方式；
6. 在发生误判时追溯 Context 来自哪里、何时生成、为何有效。

---

## 2. 系统位置

```text
Trigger Sources
↓
UnifiedEvent
↓
Persist Event
↓
Current Context Builder
├─ Current State Store
├─ Recent Interaction Aggregator
├─ Active Schedule / Constraint Store
├─ Relationship Short-term Signals
└─ Deterministic Derivations
↓
CurrentContextSnapshot
↓
Consumer-specific Projection
├─ AppraisalContext
├─ NeedContext
├─ InitiativeContext
└─ ExpressionContext
```

Current Context 必须在每个 UnifiedEvent 进入情绪系统后、Appraisal 之前构建。

---

## 3. 核心定义

Current Context 是：

> 在指定时间点，根据当时可用信息构建的、具有来源、置信度和有效期的短期情境快照。

它不是：

- Event 本身；
- 长期 Memory；
- Libra 的 EmotionState、MoodState 或 NeedState；
- 对用户内心状态的无依据判断；
- Initiative Decision；
- 最终回复内容。

各层回答的问题不同：

| 层 | 回答的问题 |
|---|---|
| UnifiedEvent | 刚刚发生了什么？ |
| Relevant Memory | 过去有哪些相关经历、事实和承诺？ |
| Current Context | 现在是什么局面？哪些短期信息仍然有效？ |
| Appraisal | 这件事对 Libra 的 Goals 和 Standards 意味着什么？ |
| Emotion / Mood / Need | Libra 因此产生了什么内部状态？ |
| Initiative / Expression | 现在是否行动，以及怎样表达？ |

---

## 4. V1 设计原则

### 4.1 Snapshot 与 Projection 分离

系统先构建统一的 `CurrentContextSnapshot`，再为不同消费者生成精简投影。

```text
CurrentContextSnapshot
≠ 直接完整传给所有 LLM
```

Appraisal、Need、Initiative 和 Expression 只能收到完成当前任务所需的字段。

### 4.2 短期状态必须有时效

可能变化的状态不得只有一个裸值。

错误示例：

```json
{
  "current_known_state": "studying"
}
```

正确示例：

```json
{
  "value": "studying",
  "observed_at": "2026-09-05T19:00:00+08:00",
  "source_type": "explicit_user_statement",
  "confidence": 0.95,
  "valid_until": "2026-09-05T21:00:00+08:00"
}
```

超过有效期后，该状态必须变为 `unknown`，不得继续当作当前事实使用。

### 4.3 事实、推导与推测分离

Context Builder 必须标记状态来源。

```text
explicit / authoritative
> observed
> derived
> inferred
```

该顺序只表示一般证据强度，不是无条件覆盖规则。字段归属主体、信息新旧程度和来源可靠性仍需共同判断。

### 4.4 Unknown 不等于 False

系统不知道用户是否忙碌时：

```text
availability = unknown
```

不得写成：

```text
availability = available
```

同样，过期状态应降为 `unknown`，而不是自动取反。

### 4.5 Current Context 不重复其他权威状态

Current Context 可以引用或投影其他状态，但不得创建第二份权威数据。

例如：

- EmotionState 的权威值仍由 Emotion System 保存；
- NeedState 的权威值仍由 Need System 保存；
- Initiative cooldown 仍由 Initiative 模块保存；
- 长期关系阶段仍属于 Relationship Memory / Relationship State；
- 待办详情仍属于 Todo / Schedule 系统。

### 4.6 最小必要原则

完整快照只保留对当前判断有稳定价值的短期字段。

传给 LLM 的投影视图还要进一步裁剪，不得把原始聊天全文、完整日程、完整记忆或无关状态全部塞入 Prompt。

---

## 5. 完整数据结构

V1 推荐结构：

```json
{
  "schema_version": "1.0",
  "context_id": "ctx_01JXYZ...",
  "generated_at": "2026-09-05T21:30:00+08:00",
  "trigger_event_id": "evt_01JXYZ...",
  "timezone": "Asia/Shanghai",

  "temporal": {
    "local_time": "2026-09-05T21:30:00+08:00",
    "day_phase": "evening",
    "is_workday": false,
    "special_period": null
  },

  "libra": {
    "activity": {
      "value": "working",
      "observed_at": "2026-09-05T20:10:00+08:00",
      "source_type": "authoritative_state",
      "source_ref": "libra_activity_state",
      "confidence": 1.0,
      "valid_until": null
    },
    "location_name": {
      "value": "忒弥斯律师事务所",
      "observed_at": "2026-09-05T20:10:00+08:00",
      "source_type": "authoritative_state",
      "source_ref": "libra_state_event:123",
      "confidence": 1.0,
      "valid_until": null
    },
    "location_type": {
      "value": "office",
      "observed_at": "2026-09-05T20:10:00+08:00",
      "source_type": "derived_rule",
      "source_ref": "location_type_rule_v1:libra_state_event:123",
      "confidence": 1.0,
      "valid_until": null
    },
    "availability": {
      "value": "interruptible",
      "observed_at": "2026-09-05T21:30:00+08:00",
      "source_type": "derived_rule",
      "source_ref": "availability_rule_v1",
      "confidence": 0.9,
      "valid_until": null
    },
    "fatigue": {
      "value": 0.42,
      "observed_at": "2026-09-05T21:30:00+08:00",
      "source_type": "authoritative_state",
      "source_ref": "libra_attribute_snapshot:456",
      "confidence": 1.0,
      "valid_until": "2026-09-05T22:00:00+08:00"
    }
  },

  "user": {
    "reported_status": {
      "value": "专注",
      "observed_at": "2026-09-05T21:05:00+08:00",
      "source_type": "explicit_user_statement",
      "source_ref": "user_home_status",
      "confidence": 1.0,
      "valid_until": null
    },
    "activity": {
      "value": "studying",
      "observed_at": "2026-09-05T21:05:00+08:00",
      "source_type": "derived_rule",
      "source_ref": "user_status_mapping_v1:user_home_status",
      "confidence": 0.9,
      "valid_until": "2026-09-05T23:05:00+08:00"
    },
    "location_type": {
      "value": "home",
      "observed_at": "2026-09-05T20:50:00+08:00",
      "source_type": "explicit_user_statement",
      "source_ref": "evt_user_message_000",
      "confidence": 0.95,
      "valid_until": "2026-09-06T02:50:00+08:00"
    },
    "availability": {
      "value": "probably_busy",
      "observed_at": "2026-09-05T21:30:00+08:00",
      "source_type": "derived_rule",
      "source_ref": "availability_rule_v1",
      "confidence": 0.72,
      "valid_until": "2026-09-05T23:05:00+08:00"
    },
    "condition_signals": [
      {
        "kind": "fatigue",
        "level": "moderate",
        "observed_at": "2026-09-05T20:50:00+08:00",
        "source_type": "explicit_user_statement",
        "source_ref": "evt_user_message_000",
        "confidence": 0.9,
        "valid_until": "2026-09-06T08:00:00+08:00"
      }
    ]
  },

  "interaction": {
    "conversation_status": "paused",
    "last_user_message_at": "2026-09-05T21:05:00+08:00",
    "last_libra_message_at": "2026-09-05T21:07:00+08:00",
    "last_effective_interaction_at": "2026-09-05T21:07:00+08:00",
    "minutes_since_last_interaction": 23,
    "awaiting_reply_from": "neither",
    "open_loop_count": 1,
    "open_loop_refs": ["loop_exam_followup_001"],
    "messages_last_60m": 8,
    "messages_today": 31
  },

  "relationship": {
    "recent_interaction_quality": {
      "value": 0.78,
      "window_minutes": 1440,
      "evidence_count": 6,
      "confidence": 0.82
    },
    "conflict_state": "none",
    "repair_state": "not_needed",
    "recent_distance_signal": false
  },

  "situational": {
    "active_focus": {
      "kind": "exam_preparation",
      "subject": "user",
      "source_ref": "memory_or_task_ref_001",
      "valid_until": "2026-09-06T09:00:00+08:00"
    },
    "upcoming_pressure": {
      "kind": "exam",
      "due_at": "2026-09-06T09:00:00+08:00",
      "importance": 0.9,
      "source_ref": "calendar_item_001"
    },
    "quiet_hours": false,
    "active_constraints": []
  },

  "data_quality": {
    "missing_critical_fields": [],
    "stale_fields": [],
    "conflicting_fields": []
  }
}
```

---

## 6. 公共观测值结构

所有可能过期、可能冲突或可能来自推断的单值状态，统一使用 `ObservedValue<T>`：

```json
{
  "value": "studying",
  "observed_at": "2026-09-05T21:05:00+08:00",
  "source_type": "explicit_user_statement",
  "source_ref": "evt_user_message_001",
  "confidence": 0.95,
  "valid_until": "2026-09-05T23:05:00+08:00"
}
```

字段定义：

| 字段 | 类型 | 必需 | 含义 |
|---|---:|---:|---|
| `value` | string / number / boolean / null | 是 | 当前采用的值；未知时使用对应枚举的 `unknown` 或 `null` |
| `observed_at` | ISO 8601 datetime | 是 | 该信息被观察、声明或推导的时间 |
| `source_type` | enum | 是 | 信息来源类别 |
| `source_ref` | string / null | 否 | 可追溯到的 Event、状态记录或规则 ID |
| `confidence` | number | 是 | `0–1`，表示当前值可靠程度 |
| `valid_until` | ISO 8601 datetime / null | 是 | 失效时间；持续到显式结束的权威状态可以为 `null` |

### 6.1 source_type 枚举

| source_type | 含义 |
|---|---|
| `authoritative_state` | 对应模块保存的权威当前状态 |
| `explicit_user_statement` | 用户明确陈述的当前状态 |
| `explicit_libra_action` | Libra 已明确执行或开始的行为 |
| `external_observation` | 获得授权的外部服务或传感来源 |
| `derived_rule` | 由确定性规则从其他状态推导 |
| `model_inference` | 模型基于有限线索做出的推测 |

`model_inference` 默认不得覆盖未过期的明确陈述或权威状态。

### 6.2 confidence 的含义

`confidence` 表示“该字段当前为真的可信程度”，不表示事件重要性，也不表示情绪强度。

建议解释：

| 范围 | 含义 |
|---|---|
| `0.90–1.00` | 明确、直接或权威 |
| `0.70–0.89` | 有较强依据，但包含推导 |
| `0.50–0.69` | 弱依据，只能谨慎使用 |
| `< 0.50` | 不应作为行动依据；通常投影为 `unknown` |

---

## 7. 字段定义

### 7.1 根字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | 当前固定为 `1.0` |
| `context_id` | string | 每次快照唯一 |
| `generated_at` | datetime | 快照生成时间 |
| `trigger_event_id` | string | 触发本次构建的 UnifiedEvent ID |
| `timezone` | IANA timezone | 时间解释所使用的时区 |

必须满足：

```text
generated_at >= UnifiedEvent.occurred_at
```

允许因消息延迟而存在少量误差，但必须记录并监控。

### 7.2 temporal

`temporal` 描述当前时间语境。

#### day_phase

固定枚举：

```text
late_night
morning
noon
afternoon
evening
night
```

具体分段由配置维护，不应散落在业务代码中。

#### special_period

用于表示会显著影响当前判断的特殊时段，例如：

```text
holiday
exam_period
travel_period
recovery_period
null
```

该字段只能来自明确日程、设置或可追溯规则，不得由 LLM 自由编造。

### 7.3 libra

`libra` 只描述 Libra 的现实短期状态，不包含 Emotion、Mood 和 Need。

#### activity.value

推荐枚举：

```text
working
studying
sleeping
resting
exercising
commuting
eating
socializing
leisure
household
personal_care
traveling
unavailable
other
unknown
```

#### location_type.value

Libra 的位置分为两个字段：

```text
location_name = 状态记录中的具体地点名称
location_type = 根据受控映射表得到的地点类别
```

`location_name` 直接来自 `libra_state_events.from_location / end_location`，例如：

```text
家-客厅
忒弥斯律师事务所
法院
健身房
```

`location_type` 保留粗粒度类别：

```text
home
office
school
transit
outdoor
public_place
medical_facility
other
unknown
```

分类规则：

```text
明确登记的家庭地点别名 → home
明确登记的律所、办公室等工作地点别名 → office
明确登记的学校地点别名 → school
活动状态为 commuting 且存在起终点 → transit
其他已知具体地点 → other
没有地点名称 → unknown
```

地点类别必须由可维护的别名映射表产生。不得仅因名称包含“公寓”“住宅”“大厦”等字样，就自行判断为家或办公室。

因此，`location_name` 的来源通常是 `authoritative_state`，而 `location_type` 的来源通常是 `derived_rule`。

V1 可以在内部 Current Context 保存业务已有的具体地点名称，但不保存精确门牌、经纬度或移动轨迹。投影给 LLM 时仍应按最小必要原则决定传 `location_name` 还是只传 `location_type`。

#### availability.value

```text
available
interruptible
busy
do_not_disturb
asleep
unknown
```

#### fatigue

`fatigue` 使用 `ObservedValue<number>`，仅表示 Libra 自身系统中的当前疲劳负荷，不表示用户疲劳，也不是 Emotion。

数据库 `libra_attribute_snapshots.fatigue` 的权威值范围为 `0–100`。Context Builder 输出时统一归一化到 `0–1`：

```text
fatigue.value = clamp(database_fatigue / 100, 0, 1)
```

示例：

```json
{
  "value": 0.42,
  "observed_at": "2026-09-05T21:30:00+08:00",
  "source_type": "authoritative_state",
  "source_ref": "libra_attribute_snapshot:456",
  "confidence": 1.0,
  "valid_until": "2026-09-05T22:00:00+08:00"
}
```

其中 `observed_at` 使用属性快照的 `snapshot_at`，`source_ref` 指向对应快照，`valid_until` 默认指向下一次半小时快照边界。

`value` 的解释为：

```text
0 = 无明显疲劳
1 = 极度疲劳
```

该值由属性系统根据 Libra 的活动时长和恢复调整计算，不由 Appraisal LLM 输出。消费者投影可以只传归一化后的 `value`，但完整 Snapshot 必须保留来源和时间信息。

### 7.4 user

`user` 表示系统当前能够合理知道的用户短期状态。

用户状态必须比 Libra 自身状态更加保守：

- 没有直接依据时使用 `unknown`；
- 不因“通常此时在工作”就写成 `working`；
- 不因用户暂时没回复就推断为 `busy`、`angry` 或 `asleep`；
- 不得把模型猜测包装成用户事实。

#### reported_status

`reported_status` 保存用户在首页手动选择的原始状态，不先把它改写成系统推断。

示例：

```json
{
  "value": "有点累",
  "observed_at": "2026-09-05T20:50:00+08:00",
  "source_type": "explicit_user_statement",
  "source_ref": "user_home_status",
  "confidence": 1.0,
  "valid_until": null
}
```

`reported_status` 与派生字段分开：

| 用户手动状态 | activity 投影 | availability 投影 | condition signal |
|---|---|---|---|
| `元气满满` | `unknown` | `probably_available` | 无 |
| `专注` | `studying` | `probably_busy` | 无 |
| `忙碌` | `unknown` | `busy` | `overload` 仅在有额外证据时生成 |
| `有点累` | `unknown` | `unknown` | `fatigue / mild` |
| `疲惫` | `unknown` | `unknown` | `fatigue / strong` |
| `放松` | `resting` | `probably_available` | 无 |
| `悠闲` | `leisure` | `probably_available` | 无 |
| `心情不错` | `unknown` | `unknown` | 不写入身体 signal |
| `紧绷` | `unknown` | `unknown` | `overload / moderate` |
| `在路上` | `commuting` | `probably_busy` | 无 |
| `运动中` | `exercising` | `probably_busy` | 无 |
| `休息中` | `resting` | `probably_busy` | 无 |

这些投影来自 `derived_rule`，其 confidence 必须低于原始 `reported_status`。一条手动状态不相关的维度应保持 `unknown`，不得为了填满字段强行推断。

用户手动状态的保存周期与“它还能否作为当前判断依据”是两件事：

- 首页选择可以一直保留，直到用户手动修改；
- `reported_status` 仍可保留为“最后一次明确报告的状态”；
- activity、availability 和 condition signal 等当前投影可以有独立 freshness window；
- 超出 freshness window 后，只停止把它当作当前现场，不自动修改或清除用户在首页选择的状态。

#### availability.value

用户可用性枚举：

```text
available
probably_available
probably_busy
busy
do_not_disturb
asleep
unknown
```

#### condition_signals

用于保存近期明确出现、会影响理解或表达的用户状态信号。

`kind` 推荐枚举：

```text
fatigue
sleepiness
hunger
pain
illness
physical_discomfort
overload
other
```

`level` 推荐枚举：

```text
mild
moderate
strong
unknown
```

注意：

- 这里只保存短期状态信号，不诊断疾病；
- 用户表达的情绪可以作为当前 Event 或相关语境，但不得在此生成未经确认的心理诊断；
- 超过有效期的 signal 必须移除或标记 stale。

### 7.5 interaction

`interaction` 描述双方近期互动的客观结构。

#### conversation_status

```text
active
paused
closed
stale
unknown
```

建议默认规则：

| 状态 | 建议判定 |
|---|---|
| `active` | 最近 15 分钟内存在连续双向互动 |
| `paused` | 对话暂时停止，但仍可能自然继续 |
| `closed` | 已明确结束，如“晚安”“先去忙了” |
| `stale` | 长时间没有互动，上一轮对话不再视为正在进行 |
| `unknown` | 数据不足 |

时间阈值必须配置化，并可根据产品实际数据调整。

#### awaiting_reply_from

```text
user
libra
neither
unknown
```

该字段表示对话结构上的待回应方，不表示任何一方有义务回复。

例如用户说“我先去考试，考完找你”，不应简单标记为 `awaiting_reply_from = user`；它更适合作为 open loop 或未来 follow-up 约定处理。

#### open_loop

Open loop 表示近期对话中尚未自然闭合、且可能需要后续处理的事项，例如：

- 答应晚些时候继续的话题；
- 用户的重要事项结束后需要跟进；
- 尚未回应的明确问题；
- 冲突后的修复事项。

Current Context 只保存数量和引用 ID，不保存完整内容。详细内容由 Conversation / Memory / Commitment 模块维护。

### 7.6 relationship

`relationship` 只表示近期互动气候，不保存长期关系定义。

#### recent_interaction_quality

```text
value: 0–1
window_minutes: 统计窗口
evidence_count: 窗口内有效互动样本数
confidence: 该聚合值可信度
```

`value` 建议解释：

| 范围 | 含义 |
|---|---|
| `0.80–1.00` | 明显温暖、顺畅、相互回应 |
| `0.60–0.79` | 整体积极或稳定 |
| `0.40–0.59` | 中性、信息不足或好坏混合 |
| `0.20–0.39` | 明显疏离、紧张或不顺畅 |
| `0–0.19` | 强冲突或严重断裂信号 |

当 `evidence_count` 很少时，必须降低 `confidence`，不得因单条普通消息得到高确定性的关系结论。

#### conflict_state

```text
none
active
cooling_down
repairing
resolved
unknown
```

#### repair_state

```text
not_needed
needed
in_progress
completed
unknown
```

`resolved` 和 `completed` 只表示近期冲突已处理，不修改长期 Relationship Memory。

### 7.7 situational

`situational` 保存当前确实有效、会改变行为判断的现实约束。

#### active_focus

只保存当前主要情境的类型、主体、引用和有效期，不复制完整任务描述。

例如：

```text
exam_preparation
work_deadline
travel
medical_recovery
family_matter
shared_activity
```

#### upcoming_pressure

只纳入临近且具有现实影响的事项。V1 建议窗口为未来 24 小时，具体值配置化。

#### quiet_hours

由用户设置、产品设置或明确约定计算。

`quiet_hours = true` 只表示当前处于静默时段，不直接决定是否发送消息；最终决定仍属于 Initiative Decision。

#### active_constraints

只保存当前生效的约束引用，例如：

```json
{
  "kind": "do_not_disturb_until",
  "subject": "user",
  "valid_until": "2026-09-05T23:00:00+08:00",
  "source_ref": "evt_user_message_001"
}
```

### 7.8 data_quality

`data_quality` 使下游模块知道哪些字段不能可靠使用。

```text
missing_critical_fields
stale_fields
conflicting_fields
```

字段路径使用 JSON Pointer 或点路径，例如：

```text
user.activity
relationship.recent_interaction_quality
```

当关键字段缺失或冲突时，下游模块应降低判断强度，而不是补写不存在的信息。

---

## 8. Effective Interaction

`last_effective_interaction_at` 表示最近一次真正形成双方关系互动的时间。

以下行为可以刷新：

- 用户发送真实聊天消息；
- Libra 回复用户并形成实际对话；
- 用户主动回应 Libra 的动态、信件或主动消息；
- 产品明确标记为双方互动的其他行为。

以下行为默认不刷新：

- 后台定时任务；
- Weather Event；
- Libra 自身状态变化；
- 没有用户参与的系统事件；
- 单纯读取消息或状态；
- 仅生成但未发送的内容；
- 推送到达但用户没有参与。

由 Event Layer 维护“哪些事件属于 Effective Interaction”的映射表。

必须满足：

```text
minutes_since_last_interaction
= floor((generated_at - last_effective_interaction_at) / 60 seconds)
```

如果从未发生有效互动：

```text
last_effective_interaction_at = null
minutes_since_last_interaction = null
```

不得使用极大数字代替 null。

---

## 9. 时效与过期规则

### 9.1 状态失效方式

状态有三种失效方式：

1. **显式结束**：收到 `activity_ended` 或新状态覆盖；
2. **到期失效**：`generated_at > valid_until`；
3. **冲突失效**：出现无法可靠解决的互斥证据。

失效后的处理：

```text
保留来源记录用于审计
↓
不再作为当前事实投影
↓
Current Context 中使用 unknown / null
↓
data_quality 记录 stale 或 conflicting
```

### 9.2 V1 默认 TTL

默认 TTL 仅在来源没有提供明确结束时间时使用。

| 字段 | 默认 TTL | 说明 |
|---|---:|---|
| 由手动状态派生的用户 activity | 120 分钟 | 仅使当前投影失效，不清除用户手动状态 |
| 用户 location_type | 360 分钟 | 新位置事件立即覆盖 |
| 由手动状态派生的用户 availability | 120 分钟 | 仅使当前投影失效；明确 DND 以用户给出的结束时间为准 |
| 由手动状态派生的用户 fatigue / sleepiness | 360 分钟 | 仅使当前投影失效；新的明确状态可以提前覆盖 |
| 用户 pain / illness | 720 分钟 | 不表示病情已结束，只表示不能继续当作实时状态 |
| active_focus | 至事项结束或最多 24 小时 | 长期事项应留在任务或 Memory 中 |
| upcoming_pressure | 到 due_at | 过期后由结果 Event 接管 |

所有 TTL 必须集中在配置中，例如：

```text
current_context_ttl_v1.yaml
```

不得分散写死在 Prompt 或业务代码中。

### 9.3 衰减与过期的区别

V1 不建议让所有状态连续衰减。

采用更清晰的规则：

```text
未到期 → 可使用原 confidence
接近到期 → 可降低 projection confidence
已到期 → unknown
```

不得通过降低 confidence 让已过期事实无限期残留。

---

## 10. 冲突解决规则

当同一字段存在多个候选值时，依次检查：

1. 候选值是否已经过期；
2. 来源是否对该主体和字段具有权威性；
3. 是否为主体的明确当前陈述；
4. `observed_at` 是否更新；
5. 信息是否足够具体；
6. 两条证据是否实际上可以同时成立；
7. 是否存在明确的结束或覆盖关系。

示例：

```text
20:00 用户说“我在学习”
20:40 用户说“终于到家躺下了”
```

后者更新且语义上结束了前一状态：

```text
user.activity = resting
```

另一个示例：

```text
设备状态：用户可能在家
21:05 用户明确说“我还在公司”
```

用户明确陈述优先：

```text
user.location_type = office
```

如果两个高可信来源时间接近、内容互斥且无法判断：

```text
value = unknown
data_quality.conflicting_fields += ["user.location_type"]
```

不得让 LLM自行选择一个“更像真的”值。

---

## 11. Current Context Builder

### 11.1 输入

```text
UnifiedEvent
Current State Store
Recent Interaction Records
Active Schedules / Constraints
Relationship Short-term Signals
Current time and timezone
```

Memory Retrieval 的完整结果不应先于 Context Builder 注入。

Context Builder 可以读取专门的短期状态索引或引用 ID，但不得把检索到的长期叙事直接复制到 Current Context。

### 11.2 构建顺序

```text
1. 接收并校验 UnifiedEvent
↓
2. 确定 generated_at 与 timezone
↓
3. 加载 Libra 权威当前状态
↓
4. 加载用户近期有效状态候选
↓
5. 加载近期互动统计与对话结构
↓
6. 加载当前生效的现实约束和短期事项引用
↓
7. 对所有候选值执行 TTL 与结束事件检查
↓
8. 解决字段冲突
↓
9. 执行确定性派生
↓
10. 计算 data_quality
↓
11. 生成不可变 CurrentContextSnapshot
↓
12. 按消费者生成 Context Projection
```

### 11.3 确定性派生

以下字段优先由程序计算：

- `day_phase`；
- `is_workday`；
- `minutes_since_last_interaction`；
- `messages_last_60m`；
- `messages_today`；
- `quiet_hours`；
- 基于明确 activity 的低风险 availability 推导；
- TTL、stale 和 conflict 标记。

这些字段不应交给 LLM 自由生成。

### 11.4 模型推断的限制

V1 允许模型为少量难以规则化的短期信号提供候选值，但必须满足：

- `source_type = model_inference`；
- `confidence < 0.8`；
- 有明确 `source_ref`；
- 有较短 `valid_until`；
- 不覆盖明确陈述或权威状态；
- 不生成医疗诊断、人格判断或关系事实；
- 不单独作为高影响主动行为的依据。

如果 V1 实现不需要模型推断，可以完全禁用该来源。

---

## 12. Consumer-specific Projection

完整快照用于统一构建和审计。下游输入使用投影视图。

### 12.1 AppraisalContext

Appraisal 只接收会改变当前 Event 意义的字段。

建议结构：

```json
{
  "current_time": "2026-09-05T21:30:00+08:00",
  "day_phase": "evening",
  "libra": {
    "activity": "working",
    "fatigue": 0.42
  },
  "user": {
    "activity": "studying",
    "availability": "probably_busy",
    "condition_signals": [
      {"kind": "fatigue", "level": "moderate", "confidence": 0.9}
    ]
  },
  "interaction": {
    "conversation_status": "paused",
    "minutes_since_last_interaction": 23
  },
  "relationship": {
    "recent_interaction_quality": 0.78,
    "conflict_state": "none",
    "repair_state": "not_needed"
  },
  "situational": {
    "active_focus_kind": "exam_preparation",
    "upcoming_pressure_kind": "exam"
  }
}
```

Appraisal 不应看到与当前 Event 无关的 interaction counters 或全部 active constraints。

### 12.2 NeedContext

Need LLM 只接收会影响本次 Event-driven Need Update 的信息。

特别规则：

> `connection` 的纯时间压力由 Python Recovery / Time Pressure 逻辑单独计算，Need LLM 不得根据 `minutes_since_last_interaction` 重复增加 connection。

V1 推荐直接从 Need LLM 投影中移除该分钟数，并显式标记：

```json
{
  "current_time": "2026-09-05T21:30:00+08:00",
  "libra": {
    "activity": "working",
    "fatigue": 0.42
  },
  "user": {
    "activity": "studying",
    "availability": "probably_busy"
  },
  "interaction": {
    "conversation_status": "paused",
    "awaiting_reply_from": "neither",
    "connection_time_pressure_already_applied": true
  },
  "relationship": {
    "recent_interaction_quality": 0.78,
    "conflict_state": "none",
    "repair_state": "not_needed"
  }
}
```

### 12.3 InitiativeContext

Initiative Decision 主要需要现实可行动性：

```json
{
  "current_time": "2026-09-05T21:30:00+08:00",
  "day_phase": "evening",
  "user": {
    "activity": "studying",
    "availability": "probably_busy"
  },
  "interaction": {
    "conversation_status": "paused",
    "last_effective_interaction_at": "2026-09-05T21:07:00+08:00",
    "minutes_since_last_interaction": 23,
    "awaiting_reply_from": "neither",
    "open_loop_refs": ["loop_exam_followup_001"]
  },
  "relationship": {
    "conflict_state": "none",
    "repair_state": "not_needed"
  },
  "situational": {
    "quiet_hours": false,
    "active_constraints": []
  }
}
```

Initiative cooldown、发送频率限制和通知权限仍作为 Initiative 模块自己的独立输入，不并入 Current Context。

### 12.4 ExpressionContext

Expression 只接收会改变表达方式的现场信息，例如：

- 用户是否忙碌；
- 用户是否疲惫或不适；
- 当前是否深夜；
- 对话是否正处于冲突修复；
- 当前话题是否涉及临近的重要事项。

Expression 不应收到内部数据质量细节、完整统计和无关状态。

### 12.5 投影通用规则

投影时必须：

1. 移除过期字段；
2. 将低于使用阈值的推断转为 `unknown`；
3. 只保留与当前 Event 和消费者职责有关的字段；
4. 保留必要的 confidence，避免把推断伪装成事实；
5. 不复制 raw message、Memory 正文或精确位置；
6. 记录使用的 `context_id`，便于回溯。

---

## 13. 与其他模块的边界

### 13.1 与 UnifiedEvent

Event 描述变化；Current Context 描述 Event 处理时的现场。

```text
Event：用户开始学习
Context：当前 21:30，用户仍在学习，可能忙碌，明早有考试
```

Current Context 可以吸收 Event 更新后的状态，但不得把 Event description 原样复制为 Context。

### 13.2 与 Memory

Memory 保存跨时间仍有价值的内容；Current Context 只保存当前有效的短期投影或引用。

```text
Memory：用户非常重视这次考试
Current Context：考试将在 12 小时后开始，当前处于备考状态
```

### 13.3 与 Emotion / Mood / Need

Current Context 是这些模块的输入之一，不是它们的副本。

禁止字段示例：

```text
libra.current_emotion
libra.current_mood
libra.connection_need
```

这些值应通过各自模块的独立输入传递。

### 13.4 与 Relationship Memory

Current Context 可以保存：

```text
近期互动质量
当前冲突状态
当前修复状态
```

不得保存：

```text
长期依恋风格
关系阶段定义
用户稳定性格判断
长期相处规律全文
```

### 13.5 与 Initiative Decision

Current Context 只提供现实条件，不输出：

```text
should_send
send_now
message_type
```

即使 Context 显示用户空闲，也不等于应该主动联系。

---

## 14. JSON Schema 核心约束

运行时 JSON Schema 至少应校验以下根结构：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "LibraCurrentContextSnapshotV1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "context_id",
    "generated_at",
    "trigger_event_id",
    "timezone",
    "temporal",
    "libra",
    "user",
    "interaction",
    "relationship",
    "situational",
    "data_quality"
  ],
  "properties": {
    "schema_version": {"const": "1.0"},
    "context_id": {"type": "string", "minLength": 1},
    "generated_at": {"type": "string", "format": "date-time"},
    "trigger_event_id": {"type": "string", "minLength": 1},
    "timezone": {"type": "string", "minLength": 1},
    "temporal": {"type": "object"},
    "libra": {"type": "object"},
    "user": {"type": "object"},
    "interaction": {"type": "object"},
    "relationship": {"type": "object"},
    "situational": {"type": "object"},
    "data_quality": {"type": "object"}
  }
}
```

除 JSON Schema 外，Python 还必须执行跨字段校验：

```text
0 <= confidence <= 1
0 <= libra.fatigue.value <= 1
0 <= recent_interaction_quality.value <= 1
observed_at <= generated_at
valid_until == null or valid_until >= observed_at
minutes_since_last_interaction 与时间戳计算一致
过期 ObservedValue 不得进入消费者投影
conflicting field 不得同时以确定值进入投影
source_type = model_inference 时 confidence < 0.8
```

---

## 15. 场景示例

### 15.1 同一句话在不同 Context 下意义不同

Event：

```json
{
  "subject": "user",
  "event_type": "location_arrived",
  "description": "用户说自己到家了。"
}
```

Context A：

```text
用户刚正常下课
近期互动稳定
没有安全相关事项
```

Appraisal 倾向：普通积极事件，情绪意义较弱。

Context B：

```text
用户深夜独自回家
此前说路上有些害怕
Libra 一直等待平安确认
```

Appraisal 倾向：重要目标得到确认，更容易产生 relief。

### 15.2 旧状态失效

```text
19:00 用户说正在学习
默认 TTL = 120 分钟
22:30 构建 Current Context
```

结果：

```json
{
  "user": {
    "activity": {
      "value": "unknown"
    }
  },
  "data_quality": {
    "stale_fields": ["user.activity"]
  }
}
```

系统不得继续以“用户正在学习”为由压制所有主动行为。

### 15.3 Need 与 Initiative 分离

```text
Libra 的 connection need 较高
用户明确表示 23:00 前不要打扰
当前时间 22:10
```

Current Context：

```text
user.availability = do_not_disturb
active constraint = do_not_disturb_until 23:00
```

Need 可以保持较高，但 Initiative Decision 应阻止当前发送。

### 15.4 不把未回复解释为关系恶化

```text
用户 90 分钟没有回复
已知用户正在考试
最近互动质量稳定
没有冲突信号
```

正确 Context：

```text
availability = busy
conversation_status = paused
recent_distance_signal = false
```

不得推断：

```text
用户在疏远 Libra
用户生气了
关系质量下降
```

---

## 16. 持久化策略

Current Context 以实时构建为主，不要求每个字段单独长期持久化。

V1 建议：

- 权威状态保存在各自 State Store；
- Context Builder 每次从权威状态和近期索引构建新快照；
- 用于 Appraisal、Need 或 Initiative 的快照可按 `context_id` 短期留存，以便调试和评估；
- 不把每个快照自动写入长期 Memory；
- 只在出现具有长期意义的 Event、承诺或模式时，由 Memory 系统按自己的规则写入。

快照应视为不可变对象。新 Event 到来时创建新 `context_id`，不得原地修改旧快照。

---

## 17. 隐私与安全

Current Context 遵循最小必要原则：

- 默认只保存粗粒度 `location_type`；
- 不保存未经需要的精确地址、经纬度或轨迹；
- 外部观察必须来自用户已授权的数据源；
- 用户撤销权限后，不再生成新的相关 Context；
- 医疗、亲密关系和冲突信号必须限制用途与留存时间；
- 低置信推断不得触发高影响提醒、质问或关系判断；
- 用于 Prompt 的投影不得包含无关敏感信息。

---

## 18. 监控指标

V1 建议监控：

| 指标 | 目标 |
|---|---:|
| 过期字段被当作当前事实的比例 | 0 |
| `unknown` 被默认解释为 available / false 的比例 | 0 |
| Need connection 时间压力重复计算比例 | 0 |
| 无来源字段比例 | 0 |
| 无法追溯的模型推断比例 | 0 |
| 消费者收到无关字段的比例 | 持续下降 |
| 因冲突字段产生确定性行动的比例 | 0 |
| 精确位置进入 LLM Prompt 的比例 | 0 |

---

## 19. V1 最小实现

如果第一阶段不实现完整结构，最小可运行字段为：

```text
schema_version
context_id
generated_at
trigger_event_id
timezone

temporal.local_time
temporal.day_phase

libra.activity
libra.location_name
libra.location_type
libra.availability
libra.fatigue

user.reported_status
user.activity
user.availability

interaction.conversation_status
interaction.last_effective_interaction_at
interaction.minutes_since_last_interaction
interaction.awaiting_reply_from

relationship.recent_interaction_quality
relationship.conflict_state

situational.quiet_hours
situational.active_constraints

data_quality.stale_fields
data_quality.conflicting_fields
```

其中 `libra.activity`、`libra.location_name`、`libra.location_type`、`libra.fatigue`、`user.reported_status`、`user.activity` 和 `user.availability` 必须使用带来源与时间信息的 `ObservedValue`，不能退回无时间信息的裸值。

---

## 20. V1 最终原则

Libra Current Context V1 遵循以下原则：

1. Current Context 描述“现在是什么局面”，而不是保存整个世界；
2. Event 描述变化，Memory 描述过去，Context 描述当前有效现场；
3. 所有易过期状态都必须具有来源、时间、置信度和有效期；
4. Unknown 不等于 False，也不等于 Available；
5. 明确事实和模型推断必须严格区分；
6. 完整 Snapshot 与消费者 Projection 必须分离；
7. Appraisal、Need、Initiative 和 Expression 只接收最小必要 Context；
8. Context 不复制 Emotion、Mood、Need、Cooldown 和长期 Memory；
9. 纯时间造成的 connection 压力只能计算一次；
10. Current Context 提供判断条件，但不直接决定情绪、主动行为或最终台词。

最终目标是：

> 让 Libra 不只知道“发生了什么”，还能够可靠地理解“这件事是在怎样的当下发生的”。
