> 当前版本 0.4.2：调试助手和正式问答流水线均启用 Pi；LangGraph 保留外层状态。Pi 服务由原启动器管理。完整架构、验收和 legacy 回退方法见 [Pi 接入说明](Pi-Agent接入与验收.md)。A2UI 停用，沿用已确认正文及折叠图片的旧模板。

# 工作知识助手：本机使用说明

入口已重新命名：**调试助手 / 问答流水线 / 问答引擎插件 / 资料检索工具**，详见 [入口说明](入口说明.md)。历史文档中的旧名字对应同一组入口，UUID 不变。

插件 `workrag/WorkRAGGraph`，版本 **0.4.2**，当前运行在 LangBot **4.11.3 / SDK 0.7.16**。

当前两个处理器均已选用用户在 LangBot 中配置的 **deepseek-flash**，**模拟模式已关闭**。真实模型问答、知识检索、资料追问、个人历史、流式输出及异常处理已完成本机示例验收，见 [Pi 验收说明](Pi-Agent接入与验收.md)。问答流水线已绑定用户本人钉钉单聊，资料范围仍为本机演示示例。

## 入口

- [本机验收处理器](http://127.0.0.1:5300/home/agents?id=baa3c4d7-366d-44b4-a38f-260b6d3b6e9e)：使用调试入口；支持消息与 `feedback.received` 模拟事件。
- [独立测试流水线](http://127.0.0.1:5300/home/agents?id=28ff66c2-04c2-4cfd-9bff-8b7a9f4efd5c)：保留触发、安全控制、扩展和输出处理配置。
- [标准问答审核](http://127.0.0.1:5300/home/plugin-pages?id=workrag%2FWorkRAGGraph%2Freview)：查看上下文、保存修改、发布、驳回、下架。
- [WorkRAG 资料管理](http://127.0.0.1:8060/knowledge/)：管理资料、发布和索引。
- 本机只读 MCP：`http://127.0.0.1:8061/mcp`；容器地址为 `http://host.docker.internal:8061/mcp`。

两个测试处理器没有绑定实际机器人，原资料库保持独立。当前只允许检索明确标注为验收用途的示例资料。原 Local Agent 与原流水线在验收中保持不变；验收后用户主动移除了这两项，并明确要求保留删除后的现状，故未恢复。

## 日常启动与停止

在 `G:\项目\WorkRAG` 双击 `start-knowledge.bat`，或执行 `start-local.ps1`。`status-local.ps1` 查看状态，`stop-local.ps1` 停止服务并保留数据。启动入口会检查端口与已记录进程，并等待已安装的工作知识助手初始化。

服务包括 LangBot、插件运行时、PostgreSQL、Qdrant、Embedding、Rerank、WorkRAG 后端和 MCP。启动入口会预热 CPU 模型并在插件就绪后重建只读 MCP 连接；首次启动需要等待模型加载。

## 接入自己的 LLM API

1. 在 LangBot 的“模型配置”中新建提供商，填写 API 地址、有效密钥和模型名称，选择支持工具调用的聊天模型。
2. 打开上述测试处理器的 AI 能力，选择“知识问答引擎（LangGraph＋Pi）”，在“回答模型”中选中该模型，关闭“模拟模型验收”。流水线与独立 Agent 的配置分别保存。
3. 仅授予“资料检索工具”（原 `WorkRAGReadOnly`）的四个工具：`search_knowledge`、`get_document_images`、`get_source_file`、`search_my_history`。不要绑定 LangBot 管理 MCP。
4. 在“授权资料 ID”中填入管理员确认可开放的资料 UUID 数组。空数组禁止知识检索；本轮采用显式资料白名单，尚无生产级部门权限映射。
5. 在调试入口验证工作知识、日常问题、工具调用和流式完成，再决定是否绑定机器人。

插件通过本轮授权接口调用选中模型，不读取或复制提供商密钥。模型分类使用同一外部模型；未使用独立 BERT。日常问题允许直接回答，工作知识必须取得本轮有效证据并保留引用。不明确的资料指代应澄清。

本机真实 API 验收已完成。以后更换模型或提供商地址后，应重新验证工具调用、路由、超时和流式行为；SDK 模拟测试不能代替真实 API 验收。

## 反馈与审核

用户明确表示“解决了”“这个方法解决了”时产生正反馈，“还是不行”“这个答案不对”产生负反馈；“谢谢”“好的”和无回复不等于认可。

卡片模拟回调使用 LangBot 调试接口：

```json
{
  "event_type": "feedback.received",
  "conversation_id": "原会话 ID",
  "actor": {"actor_type": "user", "actor_id": "原发送者 ID"},
  "data": {
    "feedback_id": "平台回调唯一 ID",
    "feedback_type": 1,
    "message_id": "已存储回答的 UUID",
    "feedback_content": "可选原因"
  }
}
```

`feedback_type` 为 1 点赞、2 点踩、3 未确认。回答 ID、版本、所属工作区与发送者必须匹配；当前回答保存后不就地编辑，最终版本为 1。重复反馈 ID 去重；新反馈 ID 可以改评。模拟回调不代表真实钉钉卡片已接通。

点赞只建立候选。管理员在审核页把片段问题补成完整问题，检查适用范围、答案和来源，勾选个人信息与范围核对，先“保存修改”，再“审核发布”。编辑和发布使用版本检查，防止覆盖别人的修改。

审核接口使用 LangBot 服务端的 `resource.manage` 权限：owner/admin/developer 可操作，operator/viewer 不可操作。模拟候选明确标记，与真实模型问答隔离。

BM25 检索已发布标准问答。首版本仅对**规范化后完全一致的问题且无额外适用条件**直接复用；改写或条件不明时重新检索。每次复用仍核对当前资料白名单、发布状态与版本；下架立即生效。此处有意采用保守范围，没有用 BM25 分数代替语义与条件验证。

## 状态、隔离与限制

- 会话键包含工作区、机器人、处理器、会话与发送者。同一会话通过 PostgreSQL 锁串行执行，默认最多 2 个 Agent 请求运行、最多 32 个等待请求；CPU 检索串行、有界等待。
- 个人历史限定当前工作区、机器人和当前发送者，避免不同平台恰好同名的账号串用。
- 待确认操作包括类型、资料、版本、步骤游标和 10 分钟有效期。明确确认、拒绝或切换话题后清除；多资料、过期或指代不明时询问。
- 默认每轮 180 秒、最多 6 次工具调用。达到调用上限时返回已取得的资料片段和限制说明；超时取消未完成调用，不声称操作成功。
- 完整聊天默认保存 90 天；每日清理聊天、反馈和过期检查点。已发布及已下架标准问答独立保存；模型只读取近期三轮和相关历史。
- 图片与文件工具返回受控引用，Runner 读取已核对版本后输出附件；旧模板 3 张图片默认折叠、原生文件收件已有本人确认。文件打开未单独确认。没有业务写工具、付款审批或拖拽编辑器。

## 安装包、源码与复验

安装包：`data\manuals\runtime\agent-deployment\workrag-WorkRAGGraph-0.4.1.lbpkg`。通过 LangBot“添加扩展 → 本地安装”安装；该包不包含数据库密码、MCP 令牌或模型密钥。

源码：`plugins\WorkRAGGraph` 和 `apps\workrag-agent`。工作流独立数据库及角色均名为 `workrag_agent`，与 `manual_rag` 分开。密钥保存在被忽略的 `data\manuals\runtime\agent.env`；插件私有配置保存容器数据库地址、范围签名密钥与固定工作区。不要提交或分享这些配置。

依赖已固定在 `apps\workrag-agent\requirements.txt`。当前运行时自带 LangGraph 1.2.6 / checkpoint 4.1.1，因此使用兼容的 PostgreSQL saver 3.0.5；没有修改 Host 或运行时的受信包。

从现有本机部署重新构建：

```powershell
.\.venv\Scripts\python.exe deployment\provision_agent.py
.\.venv\Scripts\python.exe deployment\install_agent.py build
.\.venv\Scripts\python.exe deployment\install_agent.py install
```

首次创建测试配置用 `deployment\configure_agent.py`；它会填入模拟验收默认配置，不要在配置自己的模型后随意重复执行。安装脚本通过官方接口等待安装结束，并刷新只读 MCP 目录；没有安装旧 Host 补丁。

复验：

```powershell
$env:PYTHONPATH='G:\项目\WorkRAG\apps\backend'
.\.venv\Scripts\python.exe -m pytest apps/workrag-agent/tests/test_workflow.py apps/backend/tests/test_manual_hybrid.py apps/backend/tests/test_langbot_knowledge.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe deployment\checks\verify_host_contract.py
.\.venv\Scripts\python.exe deployment\checks\verify_real_model.py
.\.venv\Scripts\python.exe deployment\checks\restart_agent_verify.py
```

`verify_real_model.py` 会调用已选择的真实 API，使用本机示例资料，短暂调整测试处理器的工具授权、调用上限和超时，并短暂停止再恢复本机检索后端以验证工具失败。所有临时配置均恢复，不发送真实机器人消息。旧 `verify_agent.py` 只用于模拟模式，真实模式下会拒绝执行。最后一项会停止再启动本部署的所有服务，并通过当前真实模型复验。运行记录在 `data\manuals\runtime\agent-deployment`，服务日志在 `data\manuals\runtime\local`。

模型通过 `invoke_llm_stream_events` 流式接入。员工侧收到的是核对证据后的分段答案；调试传输协议为 NDJSON，不直接展示未经核验的实时生成片段或模型思考文本。
