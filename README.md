# 工作知识助手

项目运行目录：`H:\工作助手`。本机入口：`http://127.0.0.1:8060/knowledge/`。

1. 打开 Docker Desktop。
2. 双击本目录的 `start-knowledge.bat`，启动知识服务并复用本地 Embedding 和 Rerank。
3. 如需 LangBot Codex 处理器，在本目录的 PowerShell 中运行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-langbot-codex.ps1
   ```

服务、资料原件和截图使用本目录的 `data\manuals`，业务数据库使用独立的 PostgreSQL `manual_rag`。当前本机工作知识实例使用 Qdrant，向量集合为 `manual_rag_chunks_v1`；此前的 Milvus 集合保留为可核对回退备份，不作为当前后端。实际运行状态以本机配置和 `/health` 为准。Python 环境和本地模型复用现有基础设施，模型文件仍在 `I:\design-ai-data\models`，不随项目重复复制。

迁移前数据库备份位于 `backups\migration-20261030`，包含私有数据；迁移前的代码和文件仍保留在 `I:\Design_RAG`，只作为回退参考。数据库中的资料路径已经切换到本目录，**不要使用旧目录中的知识助手启动器**。原设计 RAG 使用自己的数据库和配置。

独立实例密钥、Codex 守护进程令牌及本地运行资料位于私有配置和运行目录，不要上传或提交。`.gitignore` 已排除这些内容及数据库备份。

父子分块说明见 `docs\knowledge-procedure-groups.md`。资料导入、图片和钉钉验证记录在 `docs` 下，原迁移前文档中的绝对路径以本 README 为准。

BM25＋BERT 意图分流默认关闭，员工回答使用现有 LangBot Codex Agent 链路。该实验的快照保存在 GitHub 分支 `archive/intent-bm25-bert`。主分支暂时保留与现有 Host 会话记忆相依赖的代码，运行状态以本机 `/api/v1/manuals/intent/status` 为准。知识库自身的混合检索继续使用原有配置。

## 会话记忆与部门范围

LSD AI 助手单聊可使用 PostgreSQL 会话记忆，保存已引用资料和版本以支持追问。部署、有效期和回退方式见 `docs\knowledge-session-memory-postgres.md`。

资料管理页提供部门映射、跨部门授权及资料适用范围设置。部门识别复用本机审批助手的钉钉通讯录配置，应用密钥不会写入仓库。**部门检索限制仍在联调，不能将配置页面或影子检查视为权限已生效。** 已有资料需确认归属，正式启用前需完成普通检索、会话追问、图片和原文件的端到端隔离验证。

## 向量存储

当前正式配置使用 Qdrant `manual_rag_chunks_v1`。项目仍保留 Milvus 独立实例、迁移工具、适配器和已验收集合，便于以后重新评估或回退；隔离验收记录见 `docs\milvus-adapter-validation.md`。

## 钉钉自动化审批平台 MCP

工作助手已通过 MCP 接入现有钉钉付款审批平台，可读取已授权员工上传的 Excel，并生成付款拆分与审批预览。当前为本人单聊试用，正式提交和审批决定仍在原平台完成。真实钉钉文件上传的端到端验收仍待完成。

部署和回退见 `docs\payment-mcp-v1.md`，验证记录见 `docs\payment-mcp-v1-validation.md`。服务默认使用独立的本机私有配置，示例位于 `instances\payments\config.example.json`。

员工资料、截图、数据库、模型权重、凭据、备份以及本机运行日志均不随仓库上传。配置模板位于 `instances\manuals\.env.example`。
