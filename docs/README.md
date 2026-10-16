# 文档导航

日常使用从部署和功能说明开始；开发时按主题查阅，不再把所有文档平铺在同一层。

第一次接触项目请阅读[项目理解指南](guides/PROJECT_GUIDE.md)，先建立整体认识，再深入专题文档。

| 目录 | 内容 |
|---|---|
| [guides](guides/) | [部署](guides/DEPLOYMENT.md)、[功能说明](guides/FEATURES.md)、作品集 |
| [architecture](architecture/) | 后端分层、聊天与工具执行、事务及恢复机制 |
| [memory](memory/) | [LMC 记忆系统](memory/LMC_MEMORY.md)和实现对照 |
| [life](life/) | 生活引擎、日程、生活记忆及聊天并发 |
| [character](character/) | 人物设定、城市、家庭、律所及初始配置 |
| [reference](reference/) | 专题规格和早期实现参考；其中历史描述不代表当前代码 |
| [handoff](handoff/) | 任务交接约定和模板 |

当前目录边界见[项目结构](../README.md#项目结构)，后端开发入口见[后端说明](../backend/README.md)。

整理后的实际验证结果见[运行检查记录](guides/RUNTIME_CHECKS.md)。

云迁移前的数据范围见[项目数据与迁移清单](guides/DATA_INVENTORY.md)，包含实际数据库表和当前导出覆盖情况。

本地开发、VPS 部署时的数据保留规则见[代码发布与使用数据的边界](guides/DEPLOYMENT_DATA_BOUNDARY.md)。

已实施的独立数据目录及发布命令见[持久数据与代码发布](guides/PERSISTENT_STORAGE.md)。
