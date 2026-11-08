# 独立 Milvus 实例

固定版本 Milvus 3.0.5，使用官方 Compose 配置及独立的 etcd、MinIO。配置位于 `instances/milvus/compose.yaml`；官方原版保存在同目录的 `compose.official.yaml`。基于官方配置将 Milvus 的 19530、9091 端口限制到本机，MinIO 不映射宿主端口。数据库文件保存在 `H:\工作助手\data\milvus`，由 `.gitignore` 排除。

打开 Docker Desktop 后，在工作助手目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-milvus.ps1
```

停止：`powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-milvus.ps1`。停止脚本保留数据。检查状态：`docker compose -p workknowledge-milvus -f instances/milvus/compose.yaml ps`。本机连接地址 `http://127.0.0.1:19530`，管理界面 `http://127.0.0.1:9091/webui/`。

此实例仅供本机试用，先不迁移工作知识助手；现有 PostgreSQL、Qdrant、文档及索引不需要改动。后续迁移应先核对向量模型、维度、距离度量、数据权限、过滤条件和稀疏检索兼容性，备份原库，在独立集合重建并对照检索结果后再切换，保留 Qdrant 回退。

备份时先停止 Milvus，完整备份 `data\milvus\volumes` 内的 Milvus、etcd 和 MinIO 三份数据；恢复时使用与备份相同的镜像版本和一致时间点的三部分数据。不要只拷贝 Milvus 文件夹。不要执行 `docker compose down -v` 或删除数据目录作为日常停止方式。

部署方式参考 [Milvus 官方 Windows 部署文档](https://milvus.io/docs/install_standalone-windows.md)。
