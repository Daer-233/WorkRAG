# Milvus 启用与交接（2026-11-06，已回退）

**当前状态：工作助手已于 2026-11-06 下午按用户选择切回 Qdrant `manual_rag_chunks_v1`；Milvus 集合保留为可核对备份，不再作为当前后端。本文是历史切换记录，不要按本文再启用 Milvus。**

历史记录：工作助手及 Design RAG 曾正式启用 Milvus 3.0.5。两套后端均已重启，正常检索接口验证了真实嵌入、稠密和稀疏召回、重排及来源返回。PostgreSQL、原件和图片仍使用各自原位置。

| 应用 | 本机后端 | 当前 Milvus 集合 | 已索引数量 |
|---|---|---|---:|
| 工作助手 | http://127.0.0.1:8060/knowledge/ | wk_manual_snapshot_20261105_102359 | 621 |
| Design RAG | http://127.0.0.1:8030/ | wk_design_snapshot_20261105_102359 | 1,828 |

集合名称沿用已验收快照名，现在作为正式读写集合。当前配置选择 Milvus，后续正常入库使用同一集合。两库保持独立，索引登记按后端和集合区分。

## 数据与核对

切换前重新读取 Qdrant，来源摘要与快照完全一致。此前已逐条验证 2,449 条 UUID、payload、1024 维稠密向量和稀疏向量，Design RAG 的版本 ID 依据 PostgreSQL 补齐。切换时再次核对数量、来源摘要及索引登记的精确 ID 集合，停用后端写入窗口后才修改配置。

PostgreSQL 中创建目标集合对应的登记，完整保留源状态。工作助手为 indexed 621、pending 852；Design RAG 为 indexed 1,828、failed 952、pending 292。这些 pending/failed 记录没有误标成功，本次没有自动重试或补齐它们。

源 Qdrant 集合保留供核对和恢复，不再作为当前后端。切换后的增删改不会自动双写到 Qdrant。

## 运行验证

两套后端报告 vector_provider=milvus，工作助手 vector_ready=true；Design RAG 的 /ready 对 PostgreSQL、Milvus、Embedding、Rerank 均返回 true。

| 真实接口探测 | 结果 | 向量查询 | 总耗时 |
|---|---|---:|---:|
| 工作助手，AI 赋能设计培训内容 | hybrid_rerank，3 份来源、4 条证据，三路各 40 个候选，重排 8 条，无降级 | 359.60 ms | 57.36 s |
| Design RAG，材料检索 | 5 条证据，均有稠密和稀疏分路命中，重排 8 条 | 481.00 ms | 87.08 s |

以上是本机单次真实探测，不是性能保证。工作助手首次请求包含模型加载，Design RAG 的重排本次占 84.28 秒。共享模型本次以 CPU 线程 2 启动，响应速度仍需另行优化。本次未主动向钉钉员工会话发送测试消息，也未改动 Codex 回答链路。

原隔离读写、权限及版本验收见 `docs/history/milvus/milvus-adapter-validation.md`。真实探测仅验证上线连通性，不替代完整的业务问题验收。私有报告位于 `data/manuals/runtime/milvus-migration/live-manual.json` 和 `live-design.json`，快照清单位于同目录 `snapshot-20261105_102359.json`。

## 启动与配置

工作助手继续使用根目录 `start-knowledge.bat`，管理脚本已能依据实例配置启动 Milvus 并检查健康状态。直接运行 `scripts/start-manuals.ps1` 时仍需先启动存储。Milvus 独立启动脚本为 `scripts/start-milvus.ps1`。

Design RAG 仅启动后端时，在 `I:\Design_RAG` 运行 `powershell -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1 -ListenHost 127.0.0.1`。存储和共享模型需先就绪。当前后端由该脚本启动，仅监听本机。启动日志位于 `I:\Design_RAG\logs\backend-milvus.stdout.log` 与 `backend-milvus.stderr.log`。

两份私有配置分别在 `H:\工作助手\instances\manuals\.env` 和 `I:\Design_RAG\.env`，选择 VECTOR_PROVIDER=milvus，并指定各自集合。MILVUS_URI 为 http://127.0.0.1:19530。SDK 固定 pymilvus==3.0.1，位于 `H:\工作助手\data\milvus-sdk`，由 MILVUS_SDK_PATH 指定，两个启动入口均已接通。不要在共享模型环境中盲目升级依赖。

Design RAG 的项目 .venv Python 入口损坏；run-backend.ps1 现在先探测解释器是否可用，再回退到现有 design-rag Conda 环境。新增 `scripts/backend-instance.py` 负责读取本项目配置与加载独立 SDK。H 目录中的 `scripts/design-backend-instance.py`、`design-run-backend.ps1` 是已部署文件的交接副本。

## 恢复说明

切换前的完整配置属于私密文件，仅保存在本机备份目录。

- 工作助手 `H:\工作助手\backups\milvus-cutover\20261106-094525\manual.env.before`
- Design RAG `H:\工作助手\backups\milvus-cutover\20261106-094655\design.env.before`
- Design RAG 旧启动脚本 `H:\工作助手\backups\milvus-cutover\launchers-20261106\run-backend.ps1.before`

回退前先暂停两套后端及写入，比较切换以来的新增、更新和删除。如果已有新写入，必须先按 PostgreSQL 当前有效状态重建或同步 Qdrant，并核对登记和结果；不能只恢复配置后直接开放查询。确认数据一致后，分别恢复备份配置，再重启并验证健康和检索。Milvus 和 Qdrant 都保留，恢复过程不要求删除集合。备份、私有配置和员工资料禁止上传 GitHub。

`scripts/prepare-milvus-cutover.py` 是本次一次性切换工具，只接受仍使用 Qdrant 且与已验证快照一致的来源；当前已启用状态无需重复运行。

## 已知待办

Design RAG 启动后，既有混合导入协调任务持续报告 `list_mineru_image_assets` 查询引用不存在的 `j.project_id`。该问题位于 `I:\Design_RAG\apps\backend\app\repositories\rag_repository.py`，与向量切换无关，当前正常检索已单独验证。尚未修改这一任务，避免顺带恢复可能向外部解析/视觉服务提交的旧队列。后续须核对旧队列范围，再修复此查询并验收入库流程。

后续优先排查重排耗时及失败/待索引队列，再做实际员工问法验收。隔离验收使用独立测试集合，禁止将测试集合名替换为上述正式集合。
