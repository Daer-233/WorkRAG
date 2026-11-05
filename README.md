# 工作知识助手

项目运行目录：`H:\工作助手`。本机入口：`http://127.0.0.1:8060/knowledge/`。

1. 打开 Docker Desktop。
2. 双击本目录的 `start-knowledge.bat`，启动知识服务并复用本地 Embedding 和 Rerank。
3. 如需 LangBot Codex 处理器，在本目录的 PowerShell 中运行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-langbot-codex.ps1
   ```

服务、资料原件和截图使用本目录的 `data\manuals`；数据库仍使用独立的 PostgreSQL `manual_rag`，向量仍使用 Qdrant `manual_rag_chunks_v1`。PostgreSQL、Qdrant、Python 环境和本地模型是与设计 RAG 共用的现有基础设施，模型文件仍在 `I:\design-ai-data\models`，不随项目重复复制。

迁移前数据库备份位于 `backups\migration-20261030`，包含私有数据；迁移前的代码和文件仍保留在 `I:\Design_RAG`，只作为回退参考。数据库中的资料路径已经切换到本目录，**不要使用旧目录中的知识助手启动器**。原设计 RAG 使用自己的数据库和配置。

独立实例密钥、Codex 守护进程令牌及本地运行资料位于私有配置和运行目录，不要上传或提交。`.gitignore` 已排除这些内容及数据库备份。

父子分块说明见 `docs\knowledge-procedure-groups.md`。资料导入、图片和钉钉验证记录在 `docs` 下，原迁移前文档中的绝对路径以本 README 为准。

意图分流使用 BM25 和专用 BERT，疑难分流由 Terra 补充。员工回答通过 LangBot Codex Agent 处理。当前运行模式以本机配置及 `/api/v1/manuals/intent/status` 为准。配置和校准见 `docs\knowledge-intent-routing-v3.md`，验收记录见 `output\intent-routing-v3\验收记录.md`。

## 会话记忆与部门范围

LSD AI 助手单聊可使用 PostgreSQL 会话记忆，保存已引用资料和版本以支持追问。部署、有效期和回退方式见 `docs\knowledge-session-memory-postgres.md`。

资料管理页提供部门映射、跨部门授权及资料适用范围设置。部门识别复用本机审批助手的钉钉通讯录配置，应用密钥不会写入仓库。**部门检索限制仍在联调，不能将配置页面或影子检查视为权限已生效。** 已有资料需确认归属，正式启用前需完成普通检索、会话追问、图片和原文件的端到端隔离验证。

## 向量存储试验

默认配置仍为 Qdrant。项目包含 Milvus 独立实例、迁移工具和适配器的试验代码。已有隔离测试与暂存快照，生产切换须重新同步并完成验证。参见 `docs\milvus-adapter-validation.md` 和 `docs\milvus-migration-handoff.md`。

员工资料、截图、数据库、模型权重、凭据、备份以及本机运行日志均不随仓库上传。配置模板位于 `instances\manuals\.env.example`。
