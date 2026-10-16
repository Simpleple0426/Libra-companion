# 生活 Agent 真实模型评测

## 项目分项评测（2026-10-06）

新增入口 `run_system_eval`，包含聊天 12、原生 LMC 记忆检索 8、生活执行至最终回复 4 个固定开发场景。与原有生活 30 场景分开报告，共 54 个分项场景；不将模块级测试描述为 HTTP 或移动端全应用端到端评测。

从根目录执行：

```powershell
python -m backend.evals.run_system_eval --list
python -m backend.evals.run_system_eval --prepare --case greeting --embedding fts
python -m backend.evals.run_system_eval --live --workers 3 --embedding local
# 指定已有登录 profile；仅影响评测，不改正式应用配置或复制登录凭据
python -m backend.evals.run_system_eval --live --workers 3 --embedding local --cli-home "$env:USERPROFILE\.codex"
```

自检从 backend 目录运行 `python -m unittest discover -s tests -p "test_*eval*.py" -v`。`--prepare` 不调用模型、不评分；环境错误也返回非零退出码。`--embedding fts` 显式只测全文检索，不能作为向量检索效果证据；正式新基线使用 `local`，加载实际 FastEmbed / ONNX 模型，不自动退回 FTS。

聊天场景调用生产 `main_chat_agent`、`chat_research`、`ToolDecision`、`ToolExecutor`、`ChatEmotion` 与 `TurnPipeline`，验证工具循环、会话续接、情绪同步、输出契约、持久化投递和重复提交。原文、天气服务与情绪结果是可控测试适配器；不测真实外部服务、情绪判断质量。记忆由合成来源通过实际候选写入校验建立，调用实际召回与过滤逻辑；不测分段/提取模型质量。跨链路场景使用真实生活 inbox、调度器、工具校验、事务提交及最终聊天回复。

断言与自动语义评审分别保存。语义评审使用同一固定模型的独立新会话，仅属于自动初评，未由人工标注员复核。最终任务通过仍要求生活状态断言通过；聊天准确说明失败，不能让未完成任务通过。预期答案和评分规则不进入回复生成输入，实际已提交状态及检索证据按业务链路提供给模型。工具超时必须实际发生才算故障场景通过。

当前完成基线：聊天 **12/12**、记忆 **8/8**、生活 **29/30**、跨链路任务 **3/4**。各场景本轮只运行一次，不能声称三次稳定性或留出集泛化能力。两条失败都涉及生活操作 proposal 缺少必填字段，宿主拒绝提交；跨链路失败的最终回复准确说明未生效，未虚报成功。

完整证据：[分项基线](../../output/system-evals/BASELINE_20261006.md)、[系统原始报告](../../output/system-evals/20261006T105812859301Z/report.md)、[生活原始报告](../../output/life-evals/20261006T105322277900Z/report.md)。运行依赖版本保存在 `output/system-evals/environment-20261006.json`；未记录模型权重哈希。

报告保存在 `output/system-evals/<UTC时间>/`：manifest、源码快照、逐场景 result、实际回复与自动评审、chat-calls 请求/结果/用量、合成数据库、worker 日志。每次重跑创建新目录；开发轮次 `20261006T105231622007Z` 因评测脚本未处理允许多个状态而出现一条执行错误，已单独保留并标记，不拼接其通过结果到正式基线。CLI 专用 profile 本轮刷新凭据失效，最终评测使用当前用户另一份已有登录，模型不变。

两份完整分项报告可通过以下命令核对共用生产代码哈希并汇总，未完成、prepare 或生产源码不一致的报告会被拒绝：

```powershell
python -m backend.evals.summarize_system_eval --system output/system-evals/20261006T105812859301Z --life output/life-evals/20261006T105322277900Z --output output/system-evals/BASELINE_20261006.md
```

以下保留原有生活评测的参数和边界说明。

固定请求模型 `gpt-5.6-sol`，默认 reasoning 为 `medium`，不继承聊天模型配置，不自动切换其他模型。
采用现有 Codex CLI 登录，不需要把 API Key 写进评测文件。CLI 未回传服务端模型名称，因此报告明确区分请求模型与服务端身份确认。

从项目根目录执行：

```powershell
# 查看全部 30 个固定场景，不调用模型
python -m backend.evals.run_life_eval --list --suite full

# 验证隔离世界可以启动，不调用模型、不产生模型质量分数
python -m backend.evals.run_life_eval --prepare --suite full

# 5 个代表性场景，每个运行一次
python -m backend.evals.run_life_eval --live --suite smoke

# 正式基线：30 个场景，每个重复 3 次
python -m backend.evals.run_life_eval --live --suite full --repeats 3

# 可选并行：独立测试进程，报告会记录并发数；耗时不可直接与串行结果比较
python -m backend.evals.run_life_eval --live --suite full --workers 3

# 定位一个失败场景；独立保存新报告，不覆盖旧结果
python -m backend.evals.run_life_eval --live --case multi_clarify

# 检查判分器本身
python -m unittest discover -s backend/tests -p "test_life_eval*.py" -v
```

测试分类：明确请求 8、缺失信息 5、约束冲突 5、无需操作 4、多轮纠正 4、恢复 4。
预期答案只供宿主断言使用，不注入模型输入。用例均为开发集；尚无独立留出集，不能宣称泛化能力。
从 v2 起，消息 ID 为不带用例名称的哈希标识，避免向模型提示类别。v1 仅作为开发诊断记录，不作为正式基线。
v3 修正 `vague_earlier` 的初始地点为办公室：v2 在家中询问“早点回家”，模型答复无需修改是合理行为，不能作为模型错误。修改仅涉及这一条场景的初始世界，不放宽其判分条件；原始 v2 报告保留，复测单独生成报告。

### 连续修改通知丢失修复（2026-10-04）

通知捕获现在禁用动态列表的连续同文案合并，由 outbox 按提交来源 ID 去重；界面仍保持原来的合并显示。新增回归覆盖连续日程修改、同文案陪伴更新、重复捕获和已确认通知重新初始化。

相关本地测试 39 项通过。真实存储链路的无模型复现中，两次日程修改均提交成功并各自生成关联通知，证据为 `output/life-evals/outbox-reproduction-after-fix.json`；原始缺失通知证据保留在 `outbox-reproduction.json`。

两个原失败场景各重复三次的真实模型尝试保留于 `output/life-evals/20261004T060746726500Z/`。该轮 CLI 未完成模型调用，业务回执为 `model_unavailable`，不能据此宣称修复后的模型任务成功率或全套 30/30。请求模型仍为 `gpt-5.6-sol`，没有切换模型。

随后诊断确认：CLI 执行阶段需要写入现有 `.codex-libra` 运行目录，受限执行返回 `attempt to write a readonly database` 与 `os error 5`。登录检查通过不代表运行数据库可写。允许本次评测所需的运行权限后，真实模型重试完成，两个场景各重复三次，**6/6 通过**，共 12 轮消息的状态提交和关联 outbox 通知断言均通过。报告为 `output/life-evals/20261004T061644452242Z/report.md`；该结果是针对两个原失败场景的复测，完整 30 场景尚未在修复后重跑。

## 实际覆盖边界

`LocalLifeApp.submit_message → 持久化 inbox → tick / Scheduler → LifeAgent / 真实模型 → 工具校验与提交 → outbox → chat_context(message_id)`。

采用真实程序模块、固定业务时钟、独立数据库，日程由现有规则生成。每个用例、每次重复在新 Python 子进程和新测试世界中执行；基础设施目录在导入业务模块前重定向。不会启动正式服务或发送用户消息。现有角色规则和提示词仍属于被测系统，消息和运行数据为合成数据。

**当前不是包含移动端、HTTP 接入、情绪链路、长期记忆检索和最终聊天生成的全应用端到端评测。** “回执投影一致”只验证聊天读取到正确消息的结果，不代表聊天文案无幻觉；虚报成功率留空。不要将本报告写成整个应用的任务成功率。

恢复场景分别覆盖重复投递、队列提交后重新打开运行时、修改提交后重新打开运行时并重投、一次只读工具超时。重新打开运行时关闭并重建真实对象和连接，但不是强杀 OS 进程；不声称覆盖任意崩溃窗口。故障必须实际注入才允许该场景通过。

外部书影检索不属于本套任务，Agent 调用这些工具会收到明确失败，不偷偷提供成功数据。后台若调用其他模型阶段，仍使用相同真实模型，计入调用预算。

## 输出与判分

每次生成独立的 `output/life-evals/<UTC时间>/`：

- `manifest.json`：完整用例、代码/规则文件哈希、请求模型、reasoning、预算、覆盖边界和 CLI 预检。
- `source-snapshot.zip`：清单中代码与规则文件的原始字节快照及 manifest，便于核查和恢复被测版本；不包含完整依赖环境。
- `report.md`、`summary.json`：分类结果、错误写入计数、耗时、调用次数和逐次结果。
- `<case>-r<n>/result.json`：初始/前后状态、逐条断言、真实工具回执、聊天上下文、outbox。
- `transport/calls/`：模型请求、输出 Schema、响应、Token 用量及耗时；不记录隐藏推理。
- `world/` 与 `host/`：仅合成测试数据库，可用于追查失败。

断言全部通过才算场景成功；缺少终态回执不能因“没发生修改”而通过。执行错误保留在总分母；错误写入指本套件关注的日程/陪伴状态变更，仅统计有完整前后状态的禁止写入轮次，执行错误另列。每个场景完成全部指定重复且全部通过，才计入全重复通过场景数；只有一次运行不能证明稳定性。prepare 模式无成功率。

P50/P95 使用 nearest-rank；统计整个场景（多轮、Agent 收尾均包含），不是线上单条回复延迟。小样本 P95 接近最大值。保存实际 CLI Token 用量；不估算金额或补造缺失用量。

默认每个场景总预算 600 秒、每次模型调用 90 秒、最多 36 次模型调用。可通过 `--case-timeout`、`--call-timeout`、`--max-model-calls` 调整，均写入报告。生产调度器的重试仍保留并计数。provider 明确阻断时停止整个套件，不换模型、不重置预算。

先冻结用例和代码运行基线，再根据 trace 修复产品缺陷；修改判分规则需要说明原因并提升 `life_cases.VERSION`。重新运行产生新报告，不覆盖历史。第一版报告只说明固定开发集的表现，简历数字应注明套件版本、模型、样本量和重复次数。
