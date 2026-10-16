# Libra Need Update Prompt & JSON Schema V1

> 接线更新：Context 字段以 `Libra_Current_Context_V1_规格.md` 为准；当前后端行为与验收见 [重构实现记录](Libra_Affect_Corpus_Implementation.md)。

本文档是 Need Update LLM 输入输出契约的唯一真值。模型输出仅包含 `need / direction / strength`，不得增加 `reason` 等 Schema 外字段。

## 1. 目标

本文件用于定义：

1. Need Update 模型输入
2. Need Update Prompt
3. Need Update JSON 输出结构
4. 输出约束
5. Python 后处理规则

Need Update 的职责是：

```text
读取当前 Event / Emotion / Mood / Context / NeedState
↓
判断哪些 Need 受到影响
↓
输出 direction + strength
```

Need Update 不负责直接计算最终 Need value。

最终数值更新由 Python 完成。

---

# 2. 输入结构

Need Update 输入建议统一整理为：

```json
{
  "event": {},
  "aggregated_emotions": {},
  "mood": {},
  "current_context": {},
  "need_state": {}
}
```

---

## 2.1 event

传入当前 UnifiedEvent。

示例：

```json
{
  "event_id": "evt_001",
  "source": "user_life_activity",
  "subject": "user",
  "event_type": "activity_ended",
  "description": "用户结束了持续两个小时的学习。",
  "occurred_at": "2026-09-04T18:10:00+08:00",
  "scope": "instant"
}
```

---

## 2.2 aggregated_emotions

传入当前 Aggregated Emotion View。

示例：

```json
{
  "joy": 0.10,
  "happy_for": 0.55,
  "sorry_for": 0.00,
  "admiration": 0.30,
  "distress": 0.00
}
```

不需要把所有 18 种 Emotion 都强制传入。

可以只传：

```text
current_intensity > 0
```

的 Emotion。

---

## 2.3 mood

传入当前 MoodState。

示例：

```json
{
  "pleasure": 0.18,
  "arousal": -0.05,
  "dominance": 0.32
}
```

---

## 2.4 current_context

只传与 Need 判断有关的 Context。

这里接收的是 `NeedContext` 消费投影，不是完整 `CurrentContextSnapshot`。完整结构与裁剪规则以 `Libra_Current_Context_V1_规格.md` 为准。

示例：

```json
{
  "current_time": "2026-09-04T18:10:00+08:00",
  "libra": {
    "activity": "working"
  },
  "user": {
    "activity": "studying"
  },
  "interaction": {
    "connection_time_pressure_already_applied": true
  },
  "relationship": {
    "recent_interaction_quality": 0.70
  }
}
```

注意：

`connection` 的时间压力由 Python 单独计算。

因此 LLM 不需要根据：

```text
interaction.minutes_since_last_interaction
```

重复人为增加 `connection`。

除非当前 Event 本身带来了额外的联系需求变化。

---

## 2.5 need_state

传入 Recovery 后、Event-driven Update 前的 NeedState。

例如：

```json
{
  "connection": 0.72,
  "closeness": 0.60,
  "reassurance": 0.20,
  "care": 0.65,
  "expression": 0.45,
  "autonomy": 0.45
}
```

这里传的是：

```text
value
```

不需要把 `baseline / recovery_time_min` 全部交给 LLM。这里是由内部 NeedState 的各项 `value` 构造出的 LLM 输入投影视图；持久化的 NeedState 仍使用对象结构。

---

# 3. Need Update Prompt

下面为 V1 推荐 Prompt。

```text
你是 Libra 情绪系统中的 Need Update 模块。

你的任务不是回复用户，也不是决定 Libra 是否应该主动发消息。

你的任务是：

根据当前 Event、Emotion、Mood、Context 和 NeedState，
判断当前有哪些 Need 因这次状态变化而：
- increase
- decrease
- neutral

并判断影响强度：
- weak
- medium
- strong

你只输出严格 JSON。


【一、Need 定义】

Libra 有 6 类 Need：

1. connection
表示：
想和用户保持互动和联系。

增加：
- 当前事件让 Libra 更想和用户产生联系
- 当前互动明显低于希望维持的水平，并且本次 Event 进一步强化这种倾向

减少：
- 当前事件本身提供了实际互动或回应
- 联系需求得到明显满足


2. closeness
表示：
想维持关系中的熟悉、信任和亲近。

增加：
- 当前事件体现关系出现疏离、理解不足或亲近感不足
- Libra 更想重新建立熟悉和信任

减少：
- 当前事件明显增强双方理解、信任或亲近感


3. reassurance
表示：
想确认关系状态稳定、减少关系中的不确定感。

增加：
- 当前事件制造了明显的关系不确定性
- Libra 无法确认重要关系信号

减少：
- 当前事件提供了明确、稳定的关系确认
- 原有不确定性得到解除


4. care
表示：
想了解用户状态并给予适当关心和支持。

增加：
- 用户当前明显值得关注、照顾或支持
- 与用户相关的 Emotion 明显增强关注倾向

减少：
- 当前已经进行了适当关心
- 用户状态明显恢复稳定
- 关心需求已经得到阶段性满足


5. expression
表示：
想表达自己的感受、想法、生活经历或值得分享的内容。

增加：
- 当前出现明显值得表达的 Emotion
- 出现值得分享的生活内容
- 有尚未表达的想法或感受

减少：
- 当前已经完成相关表达
- 原本的表达冲动得到释放


6. autonomy
表示：
想保留自己的生活节奏和个人空间。

增加：
- 当前互动明显占用了 Libra 自己的生活节奏
- Libra 当前更希望处理自己的事务
- 当前状态更需要独处或恢复节奏

减少：
- Libra 已经获得足够个人空间
- 当前自身事务较少
- 当前更愿意投入互动


【二、判断原则】

1. 只输出真正受到明显影响的 Need。

如果没有明显变化：

"need_updates": []

不要为了“覆盖完整”而强行修改 Need。


2. 不要重复 Python 已经处理的 connection 时间压力。

Python 会根据：
minutes_since_last_interaction

单独计算：
connection context pressure

所以不要仅仅因为“很久没聊天”就再次输出：

connection increase

除非当前 Event / Emotion / Context 还带来了额外的联系需求变化。


3. direction 只能是：

increase
decrease
neutral

如果基本无影响，优先不输出，而不是输出 neutral。


4. strength 只能是：

weak
medium
strong

语义：

weak：
轻微、局部影响。

medium：
明显影响，但不是非常强烈。

strong：
直接、明显、强烈影响。


5. 不要把 Need 当成行为决策。

例如：

connection increase strong

不代表：
Libra 应该立即给用户发消息。

是否行动由 Initiative Decision 负责。


6. 不要把 Goal / Emotion 名称直接复制成 Need。

例如：

happy_for 很高

并不自动意味着：
connection increase

必须判断它是否真的改变了某个 Need。


7. 单次 Event 通常只影响少量 Need。

大多数 Event：

0~2 个 Need

复杂 Event：

最多 3 个 Need

不要一次修改全部 6 个 Need。


【三、输出要求】

只输出 JSON。

不要输出：
- Markdown
- 解释
- 注释
- 自然语言回复
- 最终 Need value

输出格式：

{
  "need_updates": [
    {
      "need": "care",
      "direction": "increase",
      "strength": "medium"
    }
  ]
}

如果没有明显变化：

{
  "need_updates": []
}
```

---

# 4. 推荐模型输出

示例：

```json
{
  "need_updates": [
    {
      "need": "care",
      "direction": "increase",
      "strength": "strong"
    },
    {
      "need": "expression",
      "direction": "increase",
      "strength": "weak"
    }
  ]
}
```

模型不输出：

```text
value
baseline
recovery_time_min
delta
```

---

# 5. JSON Schema

```json
{
  "type": "object",
  "required": [
    "need_updates"
  ],
  "properties": {
    "need_updates": {
      "type": "array",
      "maxItems": 3,
      "items": {
        "type": "object",
        "required": [
          "need",
          "direction",
          "strength"
        ],
        "properties": {
          "need": {
            "type": "string",
            "enum": [
              "connection",
              "closeness",
              "reassurance",
              "care",
              "expression",
              "autonomy"
            ]
          },

          "direction": {
            "type": "string",
            "enum": [
              "increase",
              "decrease",
              "neutral"
            ]
          },

          "strength": {
            "type": "string",
            "enum": [
              "weak",
              "medium",
              "strong"
            ]
          }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

---

# 6. Python Strength Mapping

固定映射：

```text
weak   = 0.05
medium = 0.10
strong = 0.20
```

方向：

```text
increase → +delta
decrease → -delta
neutral  → 0
```

例如：

```json
{
  "need": "care",
  "direction": "increase",
  "strength": "strong"
}
```

Python：

```text
delta = +0.20
```

---

# 7. Python 更新流程

Need 更新必须按固定顺序执行：

```text
Current NeedState
↓
1. 计算 elapsed_time
↓
2. 计算 baseline / context target
↓
3. Recovery
↓
4. 调用 Need Update LLM
↓
5. Schema Validation
↓
6. direction + strength → delta
↓
7. 应用 Event-driven Update
↓
8. clamp(0,1)
↓
9. 更新 updated_at
↓
10. 保存 NeedState
```

---

# 8. Recovery

基础公式：

```text
Need_new
=
Need_current
+
(target - Need_current)
× recovery_step
```

其中：

```text
recovery_step
=
elapsed_time_min / recovery_time_min
```

限制：

```text
recovery_step ∈ [0,1]
```

---

# 9. connection Context Pressure

V1 由 Python 单独处理。

| 距离上次有效互动 | pressure |
|---|---:|
| `0 <= x < 60 min` | 0.00 |
| `60 <= x < 180 min` | +0.05 |
| `180 <= x < 360 min` | +0.10 |
| `360 <= x <= 720 min` | +0.15 |
| `x > 720 min` | +0.20 |

其中 `x = interaction.minutes_since_last_interaction`。若该值缺失或小于 0，V1 使用 `pressure = 0.00`。

计算：

```text
connection_target
=
clamp(
  connection.baseline
  + connection_pressure,
  0,
  1
)
```

其他 Need：

```text
target = baseline
```

---

# 10. Python 语义校验

除了 JSON Schema，还建议做以下检查。

## 10.1 Need 不重复

同一输出中，同一种 Need 只允许出现一次。

错误：

```json
[
  {
    "need": "care",
    "direction": "increase",
    "strength": "medium"
  },
  {
    "need": "care",
    "direction": "decrease",
    "strength": "weak"
  }
]
```

如果重复：

```text
→ 拒绝 / 重新请求模型
```

---

## 10.2 neutral 可以直接忽略

如果模型输出：

```json
{
  "need": "connection",
  "direction": "neutral",
  "strength": "weak"
}
```

Python 可以直接：

```text
skip
```

因为：

```text
neutral → delta = 0
```

---

## 10.3 clamp

最终：

```text
Need.value
=
clamp(value, 0, 1)
```

---

# 11. 最终 NeedState

例如更新前：

```json
{
  "connection": 0.72,
  "closeness": 0.60,
  "reassurance": 0.20,
  "care": 0.65,
  "expression": 0.45,
  "autonomy": 0.45
}
```

LLM 输出：

```json
{
  "need_updates": [
    {
      "need": "care",
      "direction": "increase",
      "strength": "medium"
    },
    {
      "need": "expression",
      "direction": "increase",
      "strength": "weak"
    }
  ]
}
```

Python 更新：

```text
care:
0.65 + 0.10 = 0.75

expression:
0.45 + 0.05 = 0.50
```

最终：

```json
{
  "connection": 0.72,
  "closeness": 0.60,
  "reassurance": 0.20,
  "care": 0.75,
  "expression": 0.50,
  "autonomy": 0.45
}
```

---

# 12. V1 核心原则

```text
LLM
= 判断 Need 是否受影响、方向和强度

Python
= Recovery、Context Pressure、Delta、Clamp、持久化
```

模型负责：

```text
need
direction
strength
```

Python 负责：

```text
baseline
recovery_time_min
connection pressure
strength → delta
最终 Need value
updated_at
```

这样可以避免模型直接修改状态数值，保证 Need System 的变化可控、可追踪、可调参。
