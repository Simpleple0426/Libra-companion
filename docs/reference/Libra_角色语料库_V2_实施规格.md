# Libra 角色语料库 V2 实施规格

> 文档状态：V2 后端入口已实现；正式语料待审核入库，真实模型验收待完成  
> 目标角色：左然  
> 目标系统：Libra  
> 用途：指导角色语料的整理、存储、检索和 Runtime 接入

当前运行入口为 `libra/zuoran_corpus_v2/`，不读取或迁移旧 `zuoran_corpus/`。只允许 approved 且非 runtime_generated 的样本进入检索，空库不自动生成原作证据。实现范围及差异见 [后端重构记录](情绪系统/Libra_Affect_Corpus_Implementation.md)；下文保留完整设计目标。

## 1. 建设目标

角色语料库不是普通台词库，也不是用户长期记忆库，而是一套用于约束和解释角色行为的证据库。

它需要回答三个连续问题：

```text
左然怎么理解当前情况？
        ↓
左然为什么决定这样做？
        ↓
左然最终怎样行动和表达？
```

最终目标是让 Libra 从“模仿左然说话风格的聊天模型”，逐步变成能够以左然的方式理解事情、做出判断、处理情绪、经营关系并参与日常生活的 Agent。

## 2. 系统边界

### 2.1 Corpus 与 Memory 的职责

```text
Memory System
负责：发生过什么、用户是谁、我们经历过什么

Corpus System
负责：左然会怎样理解、判断、行动和表达
```

示例：

```text
Memory：
用户今天因为实验结果不理想而烦躁。

Corpus：
面对恋人因工作结果产生挫败时，左然通常会先理解具体问题，
承认对方的投入，再帮助拆解可以处理的部分；不会只说空泛的安慰。
```

因此：

- Memory 决定“这次需要谈什么”。
- Corpus 决定“左然如何理解和回应”。
- Emotion System 决定“当前情绪状态如何影响反应”。
- Runtime 决定“此时是否真的采取行动”。

### 2.2 Corpus 与状态机的职责

状态机负责确定客观状态，例如：

```text
正在上班
正在通勤
刚刚下班
正在吃饭
```

语料库负责提供角色化倾向，例如：

```text
左然下班途中通常会注意什么？
哪些细节可能让他想到用户？
什么情况下他愿意主动分享？
他会用什么方式表达，而不是机械报备位置？
```

语料不能直接替代状态机，也不能把概率性的角色倾向写成固定触发脚本。

## 3. 核心设计原则

### 3.1 角色证据优先，而不是堆积台词

每条高质量语料应尽量包含以下信息：

```text
场景 Context
→ 角色评估 Appraisal
→ 推断 Inference
→ 决策 Decision
→ 行动 Behavior
→ 表达 Dialogue
```

并非所有样本都必须具有全部字段，但应避免只保留一句脱离情境的台词。

### 3.2 Canon 与 Runtime 分离

原作语料用于证明：

> 左然在特定情境下通常如何理解、表达和行动。

它不能直接成为 Runtime 行为脚本。

例如，原作中出现“我给你买了蛋糕”，只能证明相关场景中的关心方式，不能让 Runtime 在没有事件依据时自动执行买蛋糕行为。

建议为语料设置证据等级：

```text
explicit_canon
原作中有直接、明确的角色证据。

canon_inference
由多条原作证据归纳出的稳定倾向。

approved_extension
原作没有直接展示，但经过人工确认，符合角色逻辑的扩展。

runtime_generated
运行期间生成的候选内容，默认不能反向污染 Canon。
```

`runtime_generated` 只有经过审核后，才能转为 `approved_extension`。

### 3.3 倾向不是必然触发

语料中的行为应表述为条件性倾向：

```text
可能、通常、在满足某些条件时倾向于……
```

避免写成：

```text
遇到场景 X，一定执行行为 Y。
```

实际决策还需要综合：

- 当前时间和地点
- 当前情绪与精力
- 关系阶段
- 最近发生的事件
- 用户当下需求
- 行为成本与现实约束
- 是否已经做过类似表达

### 3.4 正向样本与反模式并存

角色崩坏往往不是缺少正确范例，而是某一种正确行为被无限重复。

因此需要同时保存：

- 正向角色证据
- 不适用条件
- 过度使用风险
- 明确反模式

## 4. 目录结构

```text
zuoran_corpus/
├── dialogue/
│   ├── dialogue_samples.jsonl
│   ├── style_profile.json
│   └── dialogue_anti_patterns.jsonl
│
├── cognition/
│   ├── appraisal_patterns.jsonl
│   ├── inference_patterns.jsonl
│   └── decision_patterns.jsonl
│
├── behavior/
│   ├── behavior_samples.jsonl
│   └── coping_samples.jsonl
│
├── emotion/
│   ├── character_emotion_lexicon.json
│   ├── emotion_trigger_samples.jsonl
│   └── mood_pool.json
│
├── relationship/
│   ├── relationship_lifestyle.jsonl
│   ├── relationship_progression.jsonl
│   ├── intimacy_patterns.jsonl
│   ├── shared_memory_patterns.jsonl
│   ├── support_patterns.jsonl
│   ├── relationship_repair.jsonl
│   └── boundary_patterns.jsonl
│
├── initiative/
│   ├── initiative_trigger_samples.jsonl
│   ├── followup_patterns.jsonl
│   ├── care_action_patterns.jsonl
│   └── sharing_patterns.jsonl
│
├── daily_life/
│   ├── work_patterns.jsonl
│   ├── commute_patterns.jsonl
│   ├── meal_patterns.jsonl
│   ├── leisure_patterns.jsonl
│   ├── shopping_patterns.jsonl
│   └── domestic_patterns.jsonl
│
├── desire/
│   ├── desire_trigger_samples.jsonl
│   └── thought_seed_patterns.jsonl
│
├── anti_patterns/
│   ├── relationship_anti_patterns.jsonl
│   ├── memory_anti_patterns.jsonl
│   └── initiative_anti_patterns.jsonl
│
└── raw/
    └── 原始剧情与来源材料
```

## 5. 各模块职责

### 5.1 dialogue：怎样说

负责语言风格和具体表达方式。

- `dialogue_samples.jsonl`：带上下文的对话范例。
- `style_profile.json`：稳定语言风格约束。
- `dialogue_anti_patterns.jsonl`：需要避免的句式、语气和重复表达。

`style_profile.json` 应作为稳定约束注入，不参与普通 Top-K 检索。

### 5.2 cognition：怎样想

这是 V2 的核心模块。

- `appraisal_patterns.jsonl`：如何评估事件对用户、自己和关系的意义。
- `inference_patterns.jsonl`：如何从已有信息形成克制、可靠的推断。
- `decision_patterns.jsonl`：如何比较行动方案并做决定。

Appraisal 不等于情绪分类。例如用户说“我又做砸了”，不能只输出 `sad`，还应判断：

- 用户是否正在把一次结果归因为整体能力不足。
- 失败是否真的由用户独自造成。
- 用户当前更需要被理解、分析问题还是暂时休息。
- 直接说“别难过”为什么可能没有帮助。

### 5.3 behavior：怎样做

- `behavior_samples.jsonl`：角色行为及其成立条件。
- `coping_samples.jsonl`：面对压力、冲突、挫败或不确定性时的处理方式。

行为样本应尽量包含成本、边界、不适用条件和替代行为。

### 5.4 emotion：情绪怎样表现

- `character_emotion_lexicon.json`：情绪状态到角色表现的稳定映射。
- `emotion_trigger_samples.jsonl`：哪些事件容易触发哪些情绪及其原因。
- `mood_pool.json`：供状态或动态系统使用的情绪表现参考池。

情绪词典和 Mood Pool 更接近配置资源，不宜直接作为普通 RAG 文档。

### 5.5 relationship：怎样经营关系

- `relationship_lifestyle`：日常相处方式。
- `relationship_progression`：不同关系阶段的行为和表达尺度。
- `intimacy_patterns`：亲密表达的条件、程度与边界。
- `shared_memory_patterns`：自然提及共同经历的方式。
- `support_patterns`：提供情绪和现实支持的方法。
- `relationship_repair`：误解、冲突和疏离后的修复方式。
- `boundary_patterns`：尊重边界以及控制过度介入。

共同记忆的具体内容来自 Memory System；此处只保存“怎样自然回忆”。

### 5.6 initiative：为什么主动

- `initiative_trigger_samples`：哪些事件值得产生主动行为。
- `followup_patterns`：如何跟进用户曾明确提到的重要事项。
- `care_action_patterns`：如何把关心转化为合适行动。
- `sharing_patterns`：如何主动分享自己的观察、生活和感受。

事件系统判断“汇报时间已经过去”，语料库提供左然是否会跟进、何时跟进以及怎样询问的角色依据。

### 5.7 daily_life：怎样拥有生活感

记录左然在工作、通勤、饮食、休闲、购物和居家场景中的注意倾向、选择方式和分享风格。

它不决定具体日程，只负责让既有状态呈现出角色化的生活细节。

### 5.8 desire：怎样产生内部倾向

- `desire_trigger_samples`：何种事件可能唤起需求、愿望或期待。
- `thought_seed_patterns`：供内部思考或主动系统使用的种子模式。

该模块不能越过 Runtime 权限直接生成现实行动。

### 5.9 anti_patterns：怎样避免失真

至少覆盖以下问题：

- 每次用户难过都说“我一直在”。
- 所有问题都上升到爱情。
- 高频使用固定爱称。
- 用户提到工作就立即劝她休息。
- 每次召回过去都显式说“我记得”。
- 像数据库一样复述日期和事实。
- 没有当前关联时强行提起旧事。
- 所有主动内容都围绕用户。
- 每次出门都购买礼物。
- 同一种关心或亲密动作连续出现。

## 6. 检索与注入策略

### 6.1 核心 RAG 内容

适合语义检索的内容：

- dialogue samples
- appraisal patterns
- inference patterns
- decision patterns
- behavior samples
- coping samples
- relationship lifestyle
- relationship progression
- support patterns
- relationship repair
- initiative samples
- daily life patterns

### 6.2 稳定配置内容

每次生成时按需注入或由专门模块读取：

- `style_profile.json`
- `character_emotion_lexicon.json`
- `mood_pool.json`

### 6.3 RAG 与规则结合

以下内容适合由事件或状态规则先触发，再进行语料检索：

- shared memory patterns
- emotion trigger samples
- initiative trigger samples
- desire trigger samples
- thought seed patterns

### 6.4 反模式检索

反模式不能只依赖向量相似度。建议采用两层机制：

```text
全局高频禁忌
→ 固定注入简短规则

场景相关反模式
→ 根据当前场景检索
```

还应在生成后执行重复度、固定句式和不当旧事引用检查。

## 7. 与 Memory System 的连接流程

推荐 Runtime 数据流：

```text
当前消息与当前状态
        ↓
Memory Retrieval
召回相关 Episode、Semantic、Relationship、Self Memory
        ↓
Corpus Retrieval
召回相关 Appraisal、Decision、Behavior、Relationship、Dialogue 证据
        ↓
Appraisal
判断当前事件对用户、左然和关系的意义
        ↓
Emotion / Mood
结合当前角色状态调整反应强度
        ↓
Action Decision
决定回复、追问、陪伴、提供帮助或暂不行动
        ↓
Dialogue Realization
依据语言风格生成具体表达
        ↓
Anti-pattern Check
检查模板化、过度亲密、重复关心和强行回忆
```

共同记忆的正确使用方式：

```text
Memory 提供：
上次用户提到泰奶时很想喝。

Corpus 提供：
左然通常怎样自然提及共同记忆。

输出方向：
“上次你提到泰奶的时候，好像还挺馋的。”

避免：
“我记得你在 2026 年 8 月 15 日说过你喜欢泰奶。”
```

## 8. 建议的通用 JSONL 字段

不同目录可以有专用字段，但建议共享以下基础元数据：

```json
{
  "id": "corpus_unique_id",
  "domain": "cognition",
  "type": "appraisal",
  "source_level": "explicit_canon",
  "source_ref": {
    "work": "来源名称",
    "chapter": "章节或卡面",
    "location": "可回查的位置"
  },
  "context": "事件与对话背景",
  "user_state": ["frustrated", "self_doubt"],
  "relationship_stage": ["romantic_stable"],
  "character_logic": "左然如何理解该情境",
  "preferred_direction": ["承认投入", "询问具体阻碍", "提供可执行帮助"],
  "avoid_direction": ["空泛安慰", "立刻劝放弃", "未经询问替用户做决定"],
  "example_output": ["示例表达，仅作风格证据"],
  "tags": ["work", "setback", "support"],
  "confidence": 0.95,
  "review_status": "approved",
  "version": 1
}
```

字段约束：

- `source_level` 必须明确，不允许默认把扩展内容视为原作事实。
- `source_ref` 应能回查原始材料。
- `example_output` 不是必须照抄的回复模板。
- `preferred_direction` 与 `avoid_direction` 应尽量同时存在。
- `confidence` 表示证据可靠度，不表示行为触发概率。
- `review_status` 至少支持 `draft`、`reviewed`、`approved`、`rejected`。

## 9. 语料处理流水线

```text
原始剧情或可靠来源
        ↓
切分 Scene / Event / Dialogue Segment
        ↓
提取角色证据
        ↓
拆分 Appraisal / Inference / Decision / Behavior / Dialogue
        ↓
标记 Source Level 与 Source Ref
        ↓
补充适用条件、不适用条件和反模式
        ↓
人工审核
        ↓
写入正式 Corpus
        ↓
生成 Embedding / Index
        ↓
离线评测与 Runtime 灰度接入
```

不要直接把未经审核的模型抽取结果写入正式 Canon 数据集。

## 10. 分阶段实施建议

### Corpus V2.0：基础可用

优先完成：

```text
dialogue
cognition/appraisal
behavior/coping
anti_patterns
```

目标：针对当前消息和召回记忆，能够生成不模板化、符合左然认知逻辑的回复。

### Corpus V2.1：认知链

补充：

```text
inference_patterns
decision_patterns
```

目标：形成 Appraisal → Inference → Decision → Response 的完整链路。

### Corpus V2.2：关系能力

补充关系阶段、共同记忆引用、支持、修复、亲密与边界样本。

目标：让关系表达随状态和经历变化，而不是固定强度的恋爱话术。

### Corpus V2.3：主动能力

接入事件系统，建设 follow-up、care action 和 sharing 语料。

目标：根据未完成事件、时间节点和生活状态产生自然主动行为。

### Corpus V2.4：日常生活

补充工作、通勤、饮食、休闲和居家场景。

目标：减少机械行程播报，使动态和分享具有具体生活内容。

### Corpus V2.5：情绪与欲望联动

与 Emotion System、Goal System 和 Thought Seed 机制连接。

目标：同一事件在不同情绪、目标和关系状态下产生合理但不完全相同的反应。

## 11. MVP 验收标准

第一版至少满足：

- 能根据当前情境召回角色认知证据，而不只召回相似台词。
- Memory 中的事实不会被 Corpus 误当成固定角色行为。
- 原作证据与人工扩展可以明确区分并回查。
- 回复能体现“理解问题 → 决定如何处理 → 形成表达”的过程。
- 不会频繁显式声明“我记得”。
- 不会把所有关心都写成同一种安慰或亲密表达。
- 不会无条件执行买礼物、联系、出门等现实行为。
- 相同场景重复出现时，输出可以变化但角色逻辑保持稳定。
- 反模式检查能识别高频固定句式和强行引用旧事。

## 12. 当前最重要的施工结论

第一阶段不需要先整理几千句台词。

更合理的顺序是：

```text
1. 确定统一 Schema 和证据等级
2. 先整理一批高质量 Appraisal 样本
3. 为每条样本补充 Decision、Behavior 和表达方向
4. 同步建立 Anti-patterns
5. 接入 Memory Retrieval 做端到端小规模评测
6. 验证结构有效后再批量扩充原作语料
```

语料库 V2 的核心不是“左然说过哪些话”，而是：

> 左然如何认识一件事，为什么做出某个选择，以及怎样用符合关系和情境的方式表达出来。
