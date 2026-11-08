# Milvus 迁移进度与交接

**最新状态（2026-11-06 下午）：工作助手已按用户选择回退到 Qdrant `manual_rag_chunks_v1`，意图分流保持关闭并由 LangBot Codex Agent 处理。Milvus 仅作为已核对备份保留。[正式启用记录](milvus-production-cutover.md) 已标记为历史，不再代表当前配置。**

用户希望工作助手及 Design RAG 从 Qdrant 迁移至 Milvus。当前仅完成一份暂存快照，**没有切换应用、没有停写、没有删除 Qdrant**。PostgreSQL 的业务记录、原始文件和图片继续存放在原位置，Milvus 不替代它们。

| Qdrant 来源 | Milvus 暂存集合 | 快照数量 |
|---|---|---:|
| manual_rag_chunks_v1 | wk_manual_snapshot_20261105_100424 | 621 |
| design_rag_chunks_v1 | wk_design_snapshot_20261105_100424 | 1,828 |

复制原 UUID、1024 维稠密向量、稀疏向量和原 payload。两端数量一致；每库抽查 26 条编号、payload 和两种向量一致；复制前后来源全量摘要一致。复制过程的来源摘要并非事务快照，之后的增删改也不会自动同步。请在切换前重新同步并校验。

每库抽取 8 个向量，分别对比 child 筛选下稠密和稀疏检索前 10 项：工作助手平均重合均为 9.875/10，首项均 7/8；设计库稠密平均 9.125/10、首项 8/8，稀疏 10/10、首项 8/8。仅为小规模抽样，不等同于完整语义查询、权限或员工问答验收。详细记录位于本机私有文件 `data/manuals/runtime/milvus-migration/snapshot-20261105_100424.json`。

脚本 `scripts/migrate-qdrant-milvus-snapshot.py` 只建立新暂存集合、不覆盖或删除来源；`scripts/compare-milvus-snapshot.py` 只读对比。官方客户端安装在独立私有 `data/milvus-sdk`，不改变当前生产 Python 环境。

剩余工作：实现并测试两套应用的 Milvus 读写适配器，保持 1024 维、稠密＋稀疏召回与融合、权限/角色/项目、版本/子块/页码过滤、增删改及索引队列行为；对比真实经审核的问题和异常场景。Design RAG 现有代码位于 `I:\Design_RAG`，在当前工作区写入权限之外；应在获得环境允许的写入方式后处理。切换时需确定一致性窗口、同步期间新写入和删除，复核数量及来源元数据，逐库切换并保留可验证回退。未经这些步骤不能宣称迁移完成。
