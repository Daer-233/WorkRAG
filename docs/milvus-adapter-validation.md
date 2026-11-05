# Milvus 读写适配验收

2026-11-05。工作助手和 Design RAG 已接入 Milvus 3.0.5。隔离验收使用真实 PostgreSQL、Milvus 和 Qdrant，嵌入与重排使用固定的合成输入，以便比较同一批问题的证据与权限行为。生产切换另行执行。

| 验收题 | Qdrant | Milvus | 必需证据 |
|---|---:|---:|---:|
| 工作助手指定版本 | 201.14 ms | 256.41 ms | 两端各 1 条 |
| Design RAG 默认最新版本 | 267.55 ms | 243.41 ms | 两端各 1 条 |
| Design RAG 指定历史版本 | 230.84 ms | 238.98 ms | 两端各 1 条 |

三题在两端均命中稠密和稀疏召回。耗时为本地单次合成测试，包含数据库与检索调用，不用于估算钉钉或真实模型的回答时间。应用验收覆盖新增、重复 upsert、更新、幂等删除、写入失败和重试。工作助手验证了 PostgreSQL 部门授权与撤权、同版本替换和多版本选择。Design RAG 验证了项目和角色权限、父块撤权、最新与历史版本、以及写入中断后已写入但未确认的块被拦截。原重建脚本使用的 PostgreSQL 元数据字段别名已修正。应用测试中的越权结果、错误版本结果、已删除向量命中均为 0。

工作助手回归 38 项通过，Design RAG 回归 24 项通过。隔离测试报告在本机私有的 data/manuals/runtime/milvus-migration 下，文件名为 acceptance-<library>-<backend>.json。

## 当前迁移集合

| 数据 | 集合 | 全量比对 |
|---|---|---:|
| 工作助手 | wk_manual_snapshot_20261105_102359 | 621 条 |
| Design RAG | wk_design_snapshot_20261105_102359 | 1,828 条 |

逐条核对 UUID、原元数据、1024 维向量和稀疏向量。Design RAG 依据 PostgreSQL 补齐 1,828 个版本 ID，孤立记录为 0。源数据在复制前后摘要一致。详情见 snapshot-20261105_102359.json。快照完成后的新增、更新和删除需要在切换窗口重新同步。Design RAG 查询还需要目标集合对应的 PostgreSQL 索引状态记录，正式切换时须同步建立这批记录。

## 复验配置

生产示例仍以 VECTOR_PROVIDER=qdrant 为默认。测试配置使用 VECTOR_PROVIDER=milvus、MILVUS_URI=http://127.0.0.1:19530 与独立的 MILVUS_COLLECTION。工作助手集合名前缀为 wk_manual_ 或 manual_rag_，Design RAG 为 wk_design_ 或 design_rag_。客户端版本固定为 pymilvus==3.0.1。工作助手的客户端依赖见 instances/manuals/requirements-milvus.txt，Design RAG 的后端依赖见 I:/Design_RAG/requirements/base.txt。

在 Docker 运行且本机端口 15432 空闲时，启动临时数据库并从工作助手目录运行测试脚本。脚本为每次运行生成独立集合，使用已部署的两个向量服务。

    docker run -d --rm --name rag-milvus-acceptance-pg -p 127.0.0.1:15432:5432 -e POSTGRES_USER=manual_rag -e POSTGRES_DB=manual_rag -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16-alpine
    python -m pip install --target data/milvus-sdk -r instances/manuals/requirements-milvus.txt
    python scripts/verify-milvus-adapters.py manual --backend milvus
    python scripts/verify-milvus-adapters.py design --backend milvus
    python scripts/verify-milvus-adapters.py manual --backend qdrant
    python scripts/verify-milvus-adapters.py design --backend qdrant
    docker stop rag-milvus-acceptance-pg

使用已有 design-rag Python 环境运行。测试配置由脚本注入，仅在当前测试进程生效。
