# 本地部署

> 这是旧 Codex / Host 接入路线的参考说明，不是当前 Pi 助手的安装步骤。当前机器请使用 [Python 环境与启动说明](../current/项目目录与Python环境.md) 和 [部署导航](../../deployment/README.md)。

## 资料与检索

- 使用 Python 3.11，安装 [服务依赖](../../requirements-workrag.txt)。使用本地 PostgreSQL 和 Qdrant，准备独立的数据库及角色 `manual_rag`。将 [配置示例](../../instances/manuals/.env.example) 复制为 `instances/manuals/.env` 后填写凭据与图片签名密钥。
- Embedding 和 Rerank 默认分别使用本机 8031 和 8032，服务可独立运行。模型文件由部署者准备。原始文档、解析结果、图片、日志和备份存放在私有数据目录。
- 从仓库根目录运行 `python scripts/manual-instance.py init` 创建应用表和向量集合，然后运行 `python scripts/manual-instance.py serve` 启动服务。知识管理和证据预览在 `/knowledge/`。LangBot 通过 `POST /api/v1/manuals/retrieve` 调用检索。

## LangBot 与钉钉

- 在本地 LangBot 配置钉钉机器人、CodexAgent 和授权的 HTTP 知识库。按 [绑定示例](../../instances/manuals/workrag-bindings.example.json) 填写工作流、机器人、知识库和原生 Agent UUID，将完成后的文件保存在 LangBot 容器的 `/app/data/workrag-bindings.json`。本机配置脚本可通过 `WORKRAG_BINDINGS_FILE` 读取同一份绑定，或读取 `WORKRAG_PIPELINE`、`WORKRAG_BOT`、`WORKRAG_KB`、`WORKRAG_NATIVE_AGENT`。这些值随实例而变。
- LangBot 部署脚本针对容器内适配器和 CodexAgent 的既有代码结构。先运行 `scripts/install-knowledge-streaming.py` 安装流式桥接，再运行 `scripts/install-knowledge-intent.py --deploy`、`scripts/install-knowledge-session-memory.py install` 安装 Host 钩子。接收去重和首次卡片状态分别由 `scripts/install-knowledge-dingtalk-inbound.py` 和 `scripts/install-knowledge-dingtalk-initial-card.py` 安装，两个脚本均支持 `--rollback`。使用 Python 执行脚本，按脚本提示重载相应服务。
- PostgreSQL 会话记忆需要先执行 `scripts/install-knowledge-session-memory.py provision-postgres`。配置好脱敏测试资料后，将 `scripts/verify-knowledge-session-memory.py` 复制到容器 `/tmp/verify-work-session-memory.py`，填写本机的 `WORKRAG_TEST_ARTICLE`、`WORKRAG_TEST_ALBUM`、`WORKRAG_TEST_REIMBURSEMENT`、`WORKRAG_TEST_ONBOARDING` 后执行安装器的 `enable-postgres`。测试相册准备 11 张图片，先用安装器的 `link-photos --article <标题> --album <标题>` 建立关联。
- V3 需要本机模型与独立校准文件。公开仓库提供合成样例和训练、校准脚本，部署时使用当前代码重新校准。使用 `scripts/set-knowledge-intent-mode.py shadow` 开始影子验证。指定单聊可使用 `on --codex2-only`，恢复旧链路使用 `shadow --codex2-only`。
