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

BM25＋BERT 意图分流已接入影子模式，当前未通过正式上线门槛，员工回答仍沿用原链路。部署、配置、校准及即时关闭方法见 `docs\knowledge-intent-routing-v1.md`，后续继续工作先读 `docs\knowledge-intent-routing-handoff.md`。回答固定使用 Terra / Medium。
