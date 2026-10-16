# 左然阅读知识库

`catalog.json` 保存用户确认的阅读事实；`knowledge_cards.json` 保存可检索的内容概述、主题与讨论角度；`verified_quotes.jsonl` 只保存按具体版本核验过的短引文。

运行时可以依据知识卡转述、概括和讨论作品，但不得把概述伪装成原文。只有 `verified_quotes.jsonl` 中 `verified=true` 且带有版本、章节或页码依据的内容可以放进引号作为逐字引用。中文译文按具体版本分别保存，不把不同译本混为同一句话。

知识卡不证明左然正在重读某书。`reading_status=read` 只表示用户确认他读过；当前阅读活动仍由 Life Thread 单独记录。
