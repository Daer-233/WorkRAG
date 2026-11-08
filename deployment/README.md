> 当前交付入口为仓库根 README。问答引擎已更新至 0.4.2，使用 LangGraph＋Pi；钉钉旧模板正文、图片及文件状态见 docs/给下一聊天的接手说明.md。以下为首次安装记录，其中“尚未接入 Agent／钉钉”等早期状态不代表当前版本。

# 本机部署记录

界面名称与资料管理入口见 [入口说明](入口说明.md)，LangBot 内也有同名说明页面。

工作知识助手新增部署见 [使用说明](agent-README.md) 和 [首轮验收记录](agent-acceptance.md)。日常启动同时启动本机只读 MCP（8061）。独立 Agent 和测试流水线现已启用用户配置的真实 DeepSeek API，见 [最新验收记录](deepseek-acceptance.md)；真实钉钉投递仍留待后续接入。

代码位置：`G:\项目\WorkRAG`，跟踪 `origin/full-project`。
原始提交：`aef926d69cb147919b8504304c16eb8a8c9faa45`。
本机适配及最新 README 将提交到 Daer-233/WorkRAG 的 main；full-project 保留为开发来源。

## 已完成

- Docker Desktop 4.98.0 安装在 `G:\docker\Desktop`，官方安装包签名有效。
- WSL 3.0.3 已安装，官方 MSI 签名有效。
- 已核实 WSL 容器磁盘实际位置为 `G:\docker\wsl\disk\docker_data.vhdx`。
- 项目独立 Python 3.11.16 环境位于 `.venv`；CPU PyTorch 已安装。
- Compose 位于 `G:\docker\workrag\compose.yaml`，语法检查通过。
- 固定镜像为 PostgreSQL 16.11、Qdrant 1.16.3、LangBot 4.11.3，远程镜像清单已验证存在。
- 本机配置与随机密钥已生成，未写入受版本控制的文件。
- 模型位于 `G:\docker\models`，各自保留文件 SHA-256 清单。
- 实际 Python 依赖版本记录在 `requirements-windows.lock.txt`。
- 已通过 29 项现有测试（两个模型健康检查，以及混合检索、LangBot 响应适配测试）。
- 两个模型均通过真实 CPU 推理；BGE-M3 返回 1024 维稠密向量和非空稀疏向量；重排模型相关/无关示例得分为 7.5304 / -11.0335。
- Python 文件编译、四个 PowerShell 入口语法和 `git diff --check` 检查通过。

## 最终验收（2026-11-07）

Windows 已完成重启，Docker 引擎及四个容器已启动；两个模型和 WorkRAG 后端健康状态均为 `ok`。
数据库首次执行 23 项迁移，服务重启后新增迁移为 0。
示例 DOCX「部署验收示例（非真实业务制度）」已导入、发布、索引，并检索出测试编号 `WRAG-LOCAL-20261107`。
稠密、稀疏、关键词各召回 5 项，统一重排 5 项，返回 2 条证据；重启后最后一次检索约 1.48 秒，此数值仅是本机单次验收结果。
LangBot 容器内调用检索接口通过，全部服务停止再启动后的资料与检索复验通过。
浏览器已确认知识管理页显示 1 份已发布的验收资料，LangBot 管理入口显示首次管理员初始化页。
用户已完成管理员初始化，并提供 API 密钥；管理 API 和 MCP 的鉴权验证通过，可读取 54 个 MCP 工具。钉钉与生成回答 Agent 尚未接入。

LangBot MCP 地址：`http://127.0.0.1:5300/mcp`，使用 `X-API-Key` 请求头。私有密钥保存在 `data/manuals/runtime/langbot-integration/.env`，已有接入脚本优先读取环境变量，再读取该文件。这里只保存并验证项目凭据，未修改 Codex 全局 MCP 配置。
重新检查连接：`.venv\Scripts\python.exe deployment\connect_langbot_api.py`。
原作者的 `connect-langbot-knowledge.py` 仍含其旧实例的知识库和流水线 UUID，执行配置前需要适配当前实例，不可直接运行其 `configure` 命令。

需要重新执行完整部署验收时，从 PowerShell 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File 'G:\项目\WorkRAG\resume-deployment.ps1'
```

该入口启动 Docker，拉取并启动容器、初始化 WorkRAG 数据库及集合、启动 Python 服务，然后执行示例资料导入、发布、索引和检索验收，并重启本部署服务复验持久化。
如失败会停止并报错，不输出成功结论。日志在 `data\manuals\runtime\local`，验收结果在 `data\manuals\runtime\acceptance.json`。

## 日常使用

- Docker Desktop 启动后运行 `start-local.ps1`，也可双击 `start-knowledge.bat`。
- `status-local.ps1` 检查状态，`stop-local.ps1` 停止本部署服务并保留数据。
- WorkRAG：<http://127.0.0.1:8060/knowledge/>；LangBot：<http://127.0.0.1:5300>。
- Docker 中 PostgreSQL/Qdrant 使用命名卷，数据跟随 Docker 的 G 盘容器磁盘；LangBot 使用 `G:\docker\workrag\langbot`。
- WorkRAG 原件和运行记录保存在 `data\manuals`，以满足源码中的目录隔离检查。
- Docker 访问检索接口时使用 `host.docker.internal:8060`，并带 `Host: localhost:8060` 和 `X-Manual-Request: 1`，符合后端原有本机边界检查。
- 目前模型沿用原项目 CPU 推理；意图分流和部门强制隔离默认关闭。未配置钉钉、付款审批或生成回答 Agent。
- 数据库凭据位于 `G:\docker\workrag\.env` 与 `instances\manuals\.env`，不要提交或分享。

原作者 `scripts` 下依赖旧 Conda、H/I 盘环境的运维脚本保留作参考；本机使用上述新入口。
