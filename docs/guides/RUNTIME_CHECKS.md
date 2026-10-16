# 整理后的运行检查

验证日期：2026-09-27。

## 已验证

- 后端通过 `LibraBackend` 计划任务启动，监听 8000 端口。
- `/health`、`/`、`/openapi.json`、`/life-system/status`、`/room-media/movies` 和 `/chat/status` 返回 HTTP 200。
- 三个主数据库的 SQLite 完整性检查均为 `ok`，分库表归属正常。
- 现有生活世界配置通过校验，人物配置指纹与已持久化记录匹配。
- 生活引擎状态为 `ready`，工作线程处于活动状态。
- 独立键盘工具能够读取当前生活状态接口。
- 后端内部模块引用、Python 语法和 Flutter 声明资源路径检查通过。
- `flutter build apk --release --no-pub` 成功，产物位于 `mobile/build/app/outputs/flutter-apk/app-release.apk`。

## 尚未解决或未验证

- 生活 Agent 的模型调用账本此前记录了 `CLI turn failed`，仍处于需复核的保护性暂停；自动决策任务因此被阻塞。引擎就绪不等于自动生活已恢复。
- `flutter analyze` 没有编译级错误，但仍报告 5 项 warning、14 项 info，主要是未使用方法和代码风格问题。
- 本次没有发送真实聊天、执行真实模型生成、验证手机通知送达或在真机上逐页操作。

## 重复检查

在 `backend/` 执行：

```powershell
python -m scripts.check_runtime
python -m scripts.check_runtime --integrity --timeout 60
```

检查器不会输出聊天内容，也不会发送聊天或调用模型。生活调度器存在阻塞时，即使 HTTP 返回 200，也会报告失败。

需要重启计划任务时执行 `./restart_backend_task.ps1`。脚本只处理本项目计划任务所属的进程，等待健康接口通过后才报告成功。
