# 当前生活系统

正式入口是 `application/local_life.py`。目录名保留以兼容现有导入路径。

运行链路：`scheduler.py` 后台调度 → `coarse_plan.py` / `coarse_plan_generator.py` 粗计划 → `skill_router.py` / `coarse_plan_execution.py` → 对应 Skill → `activity_engine.py` 活动事务 → `event_store.py` 实际事件。

- `cognition.py`、`event_assimilation.py`、`memory_service.py`：认知、事件吸收和记忆。
- `model_client.py`、`cognition_contracts.py`、`action_validation.py`：模型调用、协议和执行校验。
- `interaction.py`、`interaction_contracts.py`：消息、睡眠计时和唤醒。
- `coarse_plan_generator.py`：生成粗计划；`coarse_plan.py`：保存和读取；`coarse_plan_updates.py`：用户消息引起的调整。
- `coarse_plan_schema.py`、`coarse_plan_execution.py`：粗计划结构与执行约束；`fine_plan.py`：细计划。
- `skill_reading.py`、`skill_movie.py`、`skill_dining.py`、`skill_personal_care.py`、`skill_housework.py`、`skill_exercise.py`、`skill_television.py`、`skill_rest.py`、`skill_outing.py`、`skill_work.py`：十类技能实现。
- `skill_router.py`：选择 Skill；`skills/<类别>/SKILL.md`：对应提示词。
- `home_catalog*`、`firm_catalog.py`、`meal_places.py`：家庭、律所、城市空间。
- `resource_library.py`、`weread*`、`douban.py`：可用书影音资源。
- `media_recommendations.py`、`movie_reviews.py`、`quote_*`：聊天推荐、影评和摘录。
- `store.py`、`memory_*`、`encoding.py` 等：存储和检索基础设施。
- `state_schema.py`：过滤历史十维字段的兼容层，不计算评分。
- `life_continuity.py`：从已提交事件生成持久生活线；阅读和观影按作品跨时段延续，其他事项按实际活动区分。保留少量事件节点，并以当前活动状态和实际进度修正聊天投影。

聊天与主动联系共用 `verified_life_state.life_continuity` 中的生活线、近期事件、已保存随想与作品笔记。Life 的 `state.read` 也可读取这些素材。随想与作品笔记只证明已经产生并保存的想法，不能证明其中描述的愿望或作品情节在生活中发生。新生活事件仍由现有活动事务先提交，再供聊天引用；该投影不创建额外事件或修改安排。

成功提交的文本与语音消息在独立 mailbox 中保存最近的发送摘录，聊天读取缓存即可得到最新记录，不等待生活模型或写入生活状态。记录用于判断重复表达，不代表消息中涉及的活动已经执行。发送摘录写入失败不撤销已提交的聊天消息。生活线存于当前 Life 数据库，重启后保留；聊天读取投影不推进生活、不调用模型。

测试放在 `backend/tests`，诊断和一次性数据迁移放在 `backend/scripts`。查看线上状态：在 backend 下运行 `python -m scripts.life_status`。

已删除早期隔离运行器、假聊天桥接、实验预算/验收入口、实验素材和退役的时间评分账本。历史数据库和迁移备份保留，旧实验命令不再提供。

文件名已按职责重命名。历史事件 ID、数据库字段、模型阶段名和工具协议沿用已有名称（例如 `p3_reply`、`daily_agenda`），以保持现有数据与聊天接口兼容；它们不是残留的旧模块。
