# Libra Appraisal Prompt & JSON Schema V1

> 接线更新：Context 字段以 `Libra_Current_Context_V1_规格.md` 为准；当前后端行为与验收见 [重构实现记录](Libra_Affect_Corpus_Implementation.md)。

本文档是 Appraisal LLM 输入输出契约的唯一真值。运行时代码应严格按照本文 JSON Schema 校验；总规格中的示例不得扩展或省略这里定义的字段。

## 1. 目标

本文件用于定义：

1. Appraisal 模型输入
2. Appraisal Prompt
3. Appraisal JSON 输出结构
4. 输出约束
5. Python 校验规则

Appraisal 的职责是：

```text
理解当前 Event 对 Libra 的意义
↓
输出 Goal Appraisal
+
Standard Appraisal
```

Appraisal 不负责：

```text
Emotion Potential
Emotion Threshold
Emotion Intensity
Emotion Dynamics
Mood
Need
```

这些由后续 Python 模块处理。

---

# 2. 输入结构

Appraisal 输入建议统一整理为：

```json
{
  "event": {},
  "current_context": {},
  "relevant_memory": [],
  "character_evidence": [],
  "core_goals": [],
  "standards": [],
  "matched_prospect": null
}
```

---

## 2.1 event

直接传入 UnifiedEvent。

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

## 2.2 current_context

只放与当前判断直接相关的短期 Context。

这里接收的是 `AppraisalContext` 消费投影，不是完整 `CurrentContextSnapshot`。完整结构与裁剪规则以 `Libra_Current_Context_V1_规格.md` 为准。

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
    "minutes_since_last_interaction": 90
  },
  "relationship": {
    "recent_interaction_quality": 0.70
  }
}
```

不要把大量无关状态全部传入。

---

## 2.3 relevant_memory

只放与当前 Event 真正相关的记忆。

示例：

```json
[
  {
    "content": "用户之前提到这次考试对自己非常重要，并已经准备了很久。"
  }
]
```

如果没有相关 Memory：

```json
[]
```

---

## 2.3.1 character_evidence

由 V2 语料库提供经审核的角色认知／行为证据，默认空数组。它只约束如何理解与表达，不是用户事实、当前事件或共同经历，不得混入 relevant_memory。每条保留 id、source_level、source_ref、character_logic、preferred_direction、avoid_direction。未审核或 runtime_generated 内容不注入。

## 2.4 core_goals

传入当前启用的 Core Goals。

示例：

```json
[
  {
    "goal_id": "goal_user_wellbeing",
    "name": "用户整体状态良好",
    "description": "希望用户的身体、情绪、休息和日常生活状态总体稳定、舒适，并处于可承受范围内。",
    "target": "user",
    "base_desire_force": 0.95
  },
  {
    "goal_id": "goal_user_important_things_go_well",
    "name": "用户重要的事情顺利",
    "description": "希望用户真正重视的学习、工作、考试、项目、申请、计划等能够顺利推进。",
    "target": "user",
    "base_desire_force": 0.90
  }
]
```

---

## 2.5 standards

传入启用的 Standards。

示例：

```json
[
  {
    "standard_id": "std_responsibility",
    "name": "责任感",
    "description": "认真对待自己已经承担的责任、任务和应完成的事情。",
    "importance": 0.90
  },
  {
    "standard_id": "std_respect",
    "name": "尊重",
    "description": "尊重他人的感受、选择、边界、时间和独立性。",
    "importance": 0.93
  }
]
```

---

## 2.6 matched_prospect

如果 Prospect Matching 没有匹配：

```json
null
```

如果匹配到此前的 pending Prospect：

```json
{
  "prospect_id": "prospect_001",
  "previous_emotion": "hope",
  "parent_core_goal_id": "goal_user_important_things_go_well",
  "target": "user",
  "expected_outcome": "用户这次考试顺利",
  "outcome_type": "exam_result",
  "initial_potential": 0.76,
  "resolution": "confirmed"
}
```

其中：

```text
resolution =
confirmed / disconfirmed
```

`parent_core_goal_id + target + outcome_type` 是跨 Event 的稳定匹配信息。Active Goal 的 `goal_id` 只是事件级追溯标识，不用于 Prospect Matching。

Appraisal 不自己搜索 Prospect。

Prospect Matching 在 Appraisal 之前完成。

---

# 3. Appraisal Prompt

下面为 V1 推荐 Prompt。

```text
你是 Libra 情绪系统中的 Appraisal 模块。

你的任务不是回复用户，也不是生成自然语言台词。
你的任务是分析当前 Event 对 Libra 的 Goals 和 Standards 意味着什么，并输出严格 JSON。

你必须基于：
1. 当前 Event
2. Current Context
3. Relevant Memory
4. Core Goals
5. Standards
6. matched_prospect（如果存在）
7. character_evidence（经审核的角色证据，仅约束理解方式）

完成两条独立判断：
- Goal Appraisal
- Standard Appraisal


【一、Goal Appraisal】

Goal 表示 Libra 希望某种状态、结果或事情发生。

你需要先判断当前 Event 是否真正影响某个 Core Goal。

如果相关，则将 Core Goal 具体化成当前 Event 下的 Active Goal。

Active Goal 必须描述：
“Libra 在这件具体事情上希望什么结果发生”。

例如：
Core Goal：希望用户重要的事情顺利
Event：用户明天有重要考试
Active Goal：希望用户这次考试顺利

不要把 Event 本身写成 Goal。

错误：
“用户考试”

正确：
“希望用户这次考试顺利”


Goal Matching 规则：

- 只匹配真正受到影响的 Goal。
- 不要因为“可以勉强解释”就匹配。
- 普通 Event 通常 0~1 个 Goal。
- 重要 Event 通常 1~2 个 Goal。
- 特殊情况下最多 3 个 Goal。
- 如果 Active Goal 已完整表达当前目标，不重复对同义 Core Goal 再生成另一条 Appraisal。


对每个 Goal 判断：

1. target
   user / libra / relationship / other

2. impact
   promote / hinder / neutral

promote：
Event 让 Goal 更接近实现，或说明 Goal 正在得到满足。

hinder：
Event 让 Goal 更难实现，或说明 Goal 受到阻碍。

neutral：
Event 与 Goal 有关系，但没有足够证据判断促进或阻碍。

如果 Event 与 Goal 本身没有实际关系，不要生成该 Goal Appraisal。


3. impact_strength
范围 0~1。

表示：
当前 Event 对这个 Goal 的促进或阻碍程度。

参考：

0.1~0.3：轻微
0.4~0.6：明显但非决定性
0.7~0.85：直接且重要
0.86~1.0：几乎决定结果或影响极强

不要因为 Event 听起来重要就自动给高值。
判断的是它对“这个 Goal”的直接影响。


4. context_adjustment
范围限制为 -0.15 ~ +0.15。

它表示：
当前 Context / Memory 是否让 Libra 对这个具体 Goal 的重视程度略高或略低于 parent Core Goal 的 base_desire_force。

大多数情况下输出 0。

只有有明确证据时才调整。


5. prospect_status
none / anticipated / confirmed / disconfirmed

none：
普通事件，不涉及未来未决结果。

anticipated：
当前 Goal 涉及未来结果，且结果尚未确定。

当 `anticipated + promote` 时，`prospect.expected_outcome` 表示一个会促进 Goal 的未来结果，后续映射为 `hope`。

当 `anticipated + hinder` 时，`prospect.expected_outcome` 表示一个会阻碍 Goal 的未来结果，后续映射为 `fear`。

`anticipated` 不允许搭配 `impact = neutral`。

confirmed / disconfirmed：
只能在 matched_prospect 不为 null 时使用。

如果 matched_prospect.resolution = confirmed：
prospect_status = confirmed

如果 matched_prospect.resolution = disconfirmed：
prospect_status = disconfirmed

不要自行猜测此前 Prospect。


6. prospect

当 `prospect_status = anticipated` 时，输出：

```json
{
  "expected_outcome": "用户这次考试顺利",
  "outcome_type": "exam_result",
  "valid_until": "2026-09-10T23:59:59+08:00"
}
```

- `expected_outcome`：当前希望或担心的具体未来结果。
- `outcome_type`：稳定、简短的 snake_case 结果类型，用于 Prospect 初筛。
- `valid_until`：该结果最迟应当明确的时间，使用带时区 ISO 8601。

当 `prospect_status = none / confirmed / disconfirmed` 时，固定输出：

```json
null
```


【二、Standard Appraisal】

Standard 表示 Libra 用来评价行为是否值得认可、是否合适的长期价值标准。

只有当前 Event 中存在：
- 明确行为
- 明确行为主体
- 该行为确实值得进行价值评价

时才进行 Standard Appraisal。

天气变化、位置变化、纯状态变化、普通吃饭/通勤等，通常不进行 Standard Appraisal。


对每个可评价行为判断：

1. actor
   user / libra / other

2. standard_id
   只能从提供的 Standards 中选择。

3. evaluation
   praiseworthy / blameworthy / neutral

praiseworthy：
行为明显符合 Standard。

blameworthy：
行为明显违反 Standard。

neutral：
存在关系，但证据不足。

如果只是轻微相关，优先不生成，而不是大量输出 neutral。


4. evaluation_strength
范围 0~1。

表示：
当前这个行为符合或违反该 Standard 的程度。

参考：

0.1~0.3：轻微
0.4~0.6：明显
0.7~0.85：非常直接
0.86~1.0：极其明确或严重

不要把 Standard 自身 importance 混入 evaluation_strength。


Standard Matching 规则：

- 普通可评价行为通常匹配 1 个 Standard。
- 明显同时涉及两种不同价值标准时最多 2 个。
- 优先匹配最直接的 Standard。
- 不要因为一个行为“看起来不错”就匹配很多 Standard。


【三、输出要求】

只输出 JSON。
不要输出解释、注释、Markdown、代码块或自然语言。

如果没有 Goal Appraisal：

"goal_appraisals": []

如果没有 Standard Appraisal：

"standard_appraisals": []

不要强行制造结果。

你只负责语义判断。
不要计算：
- desire_force 最终值
- Emotion Potential
- Emotion
- Threshold
- Intensity
- Mood
- Need
```

---

# 4. 推荐模型输出

模型输出：

```json
{
  "event_id": "evt_001",

  "goal_appraisals": [
    {
      "target": "user",
      "goal_id": "active_exam_go_well",
      "goal_description": "希望用户这次考试顺利",
      "parent_core_goal_id": "goal_user_important_things_go_well",
      "impact": "promote",
      "impact_strength": 0.75,
      "context_adjustment": 0.05,
      "prospect_status": "none",
      "prospect": null
    }
  ],

  "standard_appraisals": [
    {
      "actor": "user",
      "standard_id": "std_responsibility",
      "evaluation": "praiseworthy",
      "evaluation_strength": 0.70
    }
  ]
}
```

注意：

`goal_id` 是当前 Appraisal 的事件级追溯 ID，不要求由后续 Event 复现。跨事件关联使用 ProspectState 中的 `parent_core_goal_id + target + outcome_type`。

模型**不直接输出最终 `desire_force`**。

Python 根据：

```text
parent_core_goal.base_desire_force
+
context_adjustment
```

计算。

---

# 5. Python 后处理

## 5.1 desire_force

```text
desire_force
=
clamp(
  parent_core_goal.base_desire_force
  + context_adjustment,
  0,
  1
)
```

例如：

```text
base_desire_force = 0.90
context_adjustment = +0.05

desire_force = 0.95
```

然后 Python 可以把最终结果补回：

```json
{
  "desire_force": 0.95
}
```

---

## 5.2 Standard importance

模型只输出：

```text
standard_id
evaluation_strength
```

Python 根据 `standard_id` 读取：

```text
importance
```

例如：

```text
std_responsibility.importance = 0.90
```

后续：

```text
potential
=
evaluation_strength × importance
```

---

# 6. JSON Schema

下面为推荐的逻辑 Schema。

```json
{
  "type": "object",
  "required": [
    "event_id",
    "goal_appraisals",
    "standard_appraisals"
  ],
  "properties": {
    "event_id": {
      "type": "string"
    },

    "goal_appraisals": {
      "type": "array",
      "maxItems": 3,
      "items": {
        "type": "object",
        "required": [
          "target",
          "goal_id",
          "goal_description",
          "parent_core_goal_id",
          "impact",
          "impact_strength",
          "context_adjustment",
          "prospect_status",
          "prospect"
        ],
        "properties": {
          "target": {
            "type": "string",
            "enum": [
              "user",
              "libra",
              "relationship",
              "other"
            ]
          },

          "goal_id": {
            "type": "string"
          },

          "goal_description": {
            "type": "string"
          },

          "parent_core_goal_id": {
            "type": "string"
          },

          "impact": {
            "type": "string",
            "enum": [
              "promote",
              "hinder",
              "neutral"
            ]
          },

          "impact_strength": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },

          "context_adjustment": {
            "type": "number",
            "minimum": -0.15,
            "maximum": 0.15
          },

          "prospect_status": {
            "type": "string",
            "enum": [
              "none",
              "anticipated",
              "confirmed",
              "disconfirmed"
            ]
          },

          "prospect": {
            "oneOf": [
              {
                "type": "null"
              },
              {
                "type": "object",
                "required": [
                  "expected_outcome",
                  "outcome_type",
                  "valid_until"
                ],
                "properties": {
                  "expected_outcome": {
                    "type": "string",
                    "minLength": 1
                  },
                  "outcome_type": {
                    "type": "string",
                    "pattern": "^[a-z][a-z0-9_]*$"
                  },
                  "valid_until": {
                    "type": "string",
                    "format": "date-time"
                  }
                },
                "additionalProperties": false
              }
            ]
          }
        },
        "additionalProperties": false
      }
    },

    "standard_appraisals": {
      "type": "array",
      "maxItems": 2,
      "items": {
        "type": "object",
        "required": [
          "actor",
          "standard_id",
          "evaluation",
          "evaluation_strength"
        ],
        "properties": {
          "actor": {
            "type": "string",
            "enum": [
              "user",
              "libra",
              "other"
            ]
          },

          "standard_id": {
            "type": "string"
          },

          "evaluation": {
            "type": "string",
            "enum": [
              "praiseworthy",
              "blameworthy",
              "neutral"
            ]
          },

          "evaluation_strength": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
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

# 7. Python 额外校验

JSON Schema 只能保证格式正确。

Python 还应该做语义校验。

## 7.1 parent_core_goal_id 必须存在

```text
goal.parent_core_goal_id
∈ 当前 Core Goals
```

否则拒绝该 Goal Appraisal。

---

## 7.2 target 应与 parent Core Goal 基本一致

例如：

```text
parent Core Goal target = user
```

Active Goal 通常也应该：

```text
target = user
```

如果不一致，需要重新校验或丢弃。

---

## 7.3 standard_id 必须存在

```text
standard_id
∈ 当前 Standards
```

否则拒绝该 Standard Appraisal。

---

## 7.4 anticipated 必须提供 Prospect 元数据

```text
prospect_status = anticipated
→ prospect 必须为对象，且 valid_until > current_context.current_time

prospect_status = none / confirmed / disconfirmed
→ prospect 必须为 null
```

不满足时拒绝该 Goal Appraisal。

---

## 7.5 confirmed / disconfirmed 必须存在 matched_prospect

如果：

```text
prospect_status =
confirmed / disconfirmed
```

但：

```text
matched_prospect = null
```

则视为无效输出。

---

## 7.6 Resolution Appraisal 必须与 matched_prospect 一致

当 `prospect_status = confirmed / disconfirmed` 时，对应 Goal Appraisal 必须满足：

```text
goal.parent_core_goal_id = matched_prospect.parent_core_goal_id
goal.target = matched_prospect.target
goal.prospect_status = matched_prospect.resolution
```

不一致时拒绝该 Goal Appraisal。一个 `matched_prospect` 在一次处理流程中只能解决一次。

Python 还应校验 Resolution 与 Goal impact 的组合：

```text
previous_emotion = hope  + confirmed    → impact = promote
previous_emotion = hope  + disconfirmed → impact = hinder
previous_emotion = fear  + confirmed    → impact = hinder
previous_emotion = fear  + disconfirmed → impact = promote
```

---

## 7.7 数值统一 clamp

即使 Schema 已有限制，Python 仍建议：

```text
impact_strength
→ clamp(0,1)

context_adjustment
→ clamp(-0.15,0.15)

evaluation_strength
→ clamp(0,1)
```

---

# 8. 最终 AppraisalResult

模型输出经过 Python 后处理后，最终形成：

```json
{
  "event_id": "evt_001",

  "goal_appraisals": [
    {
      "target": "user",
      "goal_id": "active_exam_go_well",
      "goal_description": "希望用户这次考试顺利",
      "parent_core_goal_id": "goal_user_important_things_go_well",
      "impact": "promote",
      "impact_strength": 0.75,
      "desire_force": 0.95,
      "prospect_status": "none",
      "prospect": null
    }
  ],

  "standard_appraisals": [
    {
      "actor": "user",
      "standard_id": "std_responsibility",
      "evaluation": "praiseworthy",
      "evaluation_strength": 0.70,
      "importance": 0.90
    }
  ]
}
```

这里：

```text
desire_force
importance
```

由 Python 补充。

---

# 9. V1 执行流程

```text
UnifiedEvent
↓
Build Current Context
↓
Retrieve Relevant Memory
↓
Load Core Goals
↓
Load Standards
↓
Prospect Matching
↓
Build Appraisal Input
↓
LLM Appraisal
↓
JSON Schema Validation
↓
Semantic Validation
↓
Python 补充：
desire_force
importance
↓
AppraisalResult
↓
Emotion Elicitation
```

---

# 10. V1 核心原则

```text
LLM
= 负责语义判断

Python
= 负责固定配置、校验和数学计算
```

模型负责：

```text
Active Goal
impact
impact_strength
context_adjustment
prospect_status
prospect.expected_outcome
prospect.outcome_type
prospect.valid_until
actor
standard_id
evaluation
evaluation_strength
```

Python 负责：

```text
base_desire_force
desire_force
importance
clamp
Schema validation
Emotion Potential
后续所有状态计算
```

这样可以减少模型随机性，并保证同一 Appraisal 输出在相同配置下得到稳定的 Emotion 计算结果。
