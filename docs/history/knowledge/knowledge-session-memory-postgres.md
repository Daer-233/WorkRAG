# 工作知识助手 PostgreSQL 会话记忆

LSD AI 助手单聊使用手册库 `manual_rag` 的 `manual_session_memory` 表。记忆包含实际引用的资料、版本、步骤定位和等待选择的状态，保留 24 小时。有效期从最近一次成功更新引用或待选项起算。数据库定期清理过期记录。

LangBot Host 根据可信的工作区、机器人、工作流、单聊、员工和重置代次识别会话。重启可继续读取同一代次的记忆。主动重置会话后从空状态开始。切换前的进程内引用从切换后的首次新回答开始重新建立。

追问先经过 LangBot 原有授权。后端根据本轮检索标识锁定资料和版本，再检查最新发布状态。照片可以来自明确关联的相册。Codex2 单聊中的源文件追问会向发起请求的员工发送经核实的附件。每轮只允许领取一次，文件上限为 10 MB。Markdown 整理稿使用 `.txt` 扩展名，保留内容。卡片在钉钉返回受理回执后更新。找不到会话上下文时会提示补充资料名。

部署时用 `scripts/install-knowledge-session-memory.py provision-postgres` 设置内部凭据。启动手册库后端会创建表。LangBot 加载新模块后，把 `scripts/verify-knowledge-session-memory.py` 复制到容器 `/tmp/verify-work-session-memory.py`，再运行 `scripts/install-knowledge-session-memory.py enable-postgres`。该命令通过合成验收后打开单聊开关。`disable` 可单独关闭会话记忆。

LSD AI 助手的 Codex2 钉钉单聊使用独立开关。部署新版 Host 后，执行 `scripts/set-knowledge-intent-mode.py on --codex2-only` 让 V3 分类接管新问题。PostgreSQL 追问优先处理，分类服务不可用时该轮回退到 Codex2 自行判断。执行 `scripts/set-knowledge-intent-mode.py shadow --codex2-only`，后续新消息立即恢复旧流程并继续影子观察。这个开关保留后端和旧工作流的 `shadow`，全局上线门槛仍独立检查。

重启验收用相同的 `--run-id` 在重启前运行 `--postgres --phase seed`，重启后运行 `--postgres --phase resume`。`scripts/verify-postgres-memory-store.py` 使用独立的合成身份检查 24 小时有效期、过期和迟到回答保护。

## Codex2 影子分流

Codex2 单聊的普通问题在后台调用 V3 意图接口。资料追问和待选项使用 PostgreSQL 会话记忆的判断。容器内 `/app/data/work-knowledge-codex2-shadow.log` 按大小轮转，只记录分类、分流方法、候选规则、耗时和回答是否取得证据。字段 `evidence_returned` 记录本轮有没有返回可引用证据，用于人工复核，不能直接当作正确标签。影子结果标为 `applied=false`。

候选规则处理明确缺少附件、对话段落、指定版本或审批流程的情况。已知 V2 回归题的本地接受样本从 67/71 改善到 71/71。这批题用于排错，不能作为新一轮独立验收。工作题的在线探测走 BM25，日常题走专用 BERT。正式替换前需要通过独立样例、人工审核和真实影子观察，并复查公司制度误入日常路线为零。现有 V3 校准和报告继续保留原样。
