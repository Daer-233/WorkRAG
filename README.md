# WorkRAG｜工作知识助手

面向行政、IT 和财务等内部资料的钉钉知识助手。员工可以在单聊中查询操作流程、查看来源与配图，或接着上一轮询问同一份资料。管理员在本机整理图文资料、审核分块和发布版本。

## 系统架构

```mermaid
flowchart LR
    A["钉钉单聊"] --> B["LangBot 接收、确认与去重"]
    B --> C["Host 检查 PostgreSQL 会话记忆"]
    C --> D["新问题：BM25 → BERT → Terra 补判"]
    D -->|日常问题| E["agent 直接回答"]
    D -->|工作问题| F["agent 调用授权检索"]
    C -->|资料追问| F
    F --> G["关键词、稠密、稀疏召回"]
    G --> H["统一重排与父块回填"]
    H --> I["agent 按证据生成"]
    E --> J["钉钉流式卡片"]
    I --> J
    I --> K["保存实际引用的资料与版本"]
```

## 实现亮点

- **按流程组织资料**。父块对应章节或完整流程，子块对应步骤或完整说明。管理员可在发布前调整边界、顺序、页码和配图关系。查询命中子块后回填其父块，分别返回跨资料证据。
- **混合检索**。标题与关键词、BGE-M3 稠密向量、稀疏向量三路召回，使用 BGE-Reranker-v2-m3 统一重排。PostgreSQL 保存原文、版本与会话引用，Qdrant 保存可重建的检索索引。
- **可追问的图文回答**。卡片显示处理状态、真实增量和来源，支持已入库图片。会话记忆按单聊和员工隔离，有效期 24 小时。追问时重新核对发布状态和版本，必要时请员工选择资料。
- **工作与日常分流**。独立 BM25 样例索引和监督 BERT 负责本地分类，Terra 处理低置信度问题。日常路线不获得知识库权限。V3 接管范围可限定到指定机器人单聊，支持退回影子模式。钉钉接收端在消息入队后确认，短期内按消息 ID 去重。

## 当前成果

| 指标 | 本机试点结果 |
| --- | --- |
| 资料规模 | 13 条记录，11 条已发布并完成索引。索引条目涉及 2 个已命名分类，也包含未归类条目与演示资料。 |
| 检索 Hit@5 | **15/15（100%）**，小样本有依据题。 |
| 跨资料证据覆盖 | **6/6** 个目标证据，来自 3 道跨资料题。 |
| 无依据题正确返回证据不足 | **3/5**，另 2 道返回了不适用的资料。 |
| 检索耗时 | **平均 9.59 秒，P95 16.67 秒**，20 道预标注问题，预热后单并发。 |
| 意图分类 | V3 合成留出集，本地自动接受准确率 **97.0%（128/132）**，明确问法覆盖率 **97.6%（121/124）**。 |


题量、分母、失败类型与耗时口径见 [脱敏评测报告](docs/evaluation.md)。

## 本地运行

准备 Python 3.11、独立 PostgreSQL 数据库和角色 `manual_rag`、本机 Qdrant，以及 BGE Embedding 和 Rerank 服务。可以用 [配置示例](instances/manuals/.env.example) 创建本地 `instances/manuals/.env`。填写本机数据库凭据和独立图片签名密钥，从仓库根目录执行以下命令。

```powershell
python scripts/manual-instance.py init
python scripts/manual-instance.py serve
```

知识管理界面在 `http://127.0.0.1:8060/knowledge/`。LangBot 需要另行部署和设置 CodexAgent、机器人及工作知识库绑定。部署顺序和配置边界见 [本地部署说明](docs/deployment.md)。代码与示例可用于部署，业务资料、模型权重及运行凭据由部署方保管。

## 开源依赖与来源

### 实际使用

- [LangBot](https://github.com/langbot-app/LangBot)：接收钉钉消息并管理运行器和授权。
- [MinerU](https://github.com/opendatalab/MinerU)：提取 Markdown、页码和配图。
- [PostgreSQL](https://github.com/postgres/postgres)：保存原文、版本与会话引用。
- [Qdrant](https://github.com/qdrant/qdrant)：保存可重建的混合检索索引。
- [BGE-M3](https://huggingface.co/BAAI/bge-m3)：生成稠密向量与稀疏权重。
- [BGE-Reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)：对候选证据重排。
- [FastAPI](https://github.com/fastapi/fastapi)：提供后端 HTTP API。
- [Uvicorn](https://github.com/encode/uvicorn)：运行 ASGI 服务。
- [Pydantic Settings](https://github.com/pydantic/pydantic-settings)：读取环境和应用配置。
- [python-dotenv](https://github.com/theskumar/python-dotenv)：加载本地环境文件。
- [Psycopg](https://github.com/psycopg/psycopg)：访问 PostgreSQL。
- [Qdrant Python Client](https://github.com/qdrant/qdrant-client)：访问 Qdrant 向量索引。
- [HTTPX](https://github.com/encode/httpx)：发起 HTTP 请求及测试接口。
- [python-multipart](https://github.com/Kludex/python-multipart)：处理表单文件上传。
- [pypdf](https://github.com/py-pdf/pypdf)：处理 PDF 页及页段。
- [Pillow](https://github.com/python-pillow/Pillow)：处理图像和缩略图。
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF)：读取 PDF 页面和图像。
- [python-docx](https://github.com/python-openxml/python-docx)：读取 Word 文档。
- [python-pptx](https://github.com/scanny/python-pptx)：读取 PowerPoint 演示文稿。
- [beautifulsoup4](https://pypi.org/project/beautifulsoup4/)：解析 HTML 文档。
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)：实现 MCP 服务和工具通信。
- [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding)：运行 BGE 向量化与重排。
- [PyTorch](https://github.com/pytorch/pytorch)、[Transformers](https://github.com/huggingface/transformers)和 [Safetensors](https://github.com/huggingface/safetensors)：用于训练本地意图分类器、加载分词器并保存权重。

### 设计参考

- [Dify 父子分块文档](https://docs.dify.ai/en/cloud/use-dify/knowledge/create-knowledge/chunking-and-cleaning-text)：参考父子分块交互，WorkRAG 自行实现流程边界编辑、发布前预览和父块上下文回填。
