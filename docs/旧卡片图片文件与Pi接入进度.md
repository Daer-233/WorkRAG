# 旧卡片图片、文件及 Pi 接入进度

更新：2026-11-08。

## 当前有效状态

问答引擎已升级 **0.4.1**，调试助手和正式问答流水线均启用官方 **Pi Agent 1.5.0**。外层 LangGraph 保留；真实模型/MCP、附件追问、流式、失败、超时、调用上限、隔离及 Pi 重启已验证。详见 [Pi 接入与验收](Pi-Agent接入与验收.md)。

旧模板正文、3 张图片默认折叠／放大及 DOCX 收件已有用户确认；文件打开未单独确认。两个旧模板兼容开关均为 true，A2UI 仍停用。本轮未更换云端模板；Pi 切换后的钉钉客户端表现待用户观察。

## 历史记录（以下“Pi 仅离线”“待发布”等说法均已被上文覆盖）

### 先前实际验收

用户已提供实际云端旧模板导出，定位完成态 answer 的 isStreaming=true 与普通变量更新不匹配；服务端已补专用流式通道，用户确认新正文正常显示。折叠图片区已启用，用户确认默认收起、3 张图正常显示且可点击放大。原生 DOCX 已确认收到，文件是否可打开未单独确认。以上为本人单聊真机验收，不代表生产部门隔离或其他会话验收。A2UI 停用，正式 Agent 仍为原 LangGraph 实现。

当前启动器保留正文兼容、原生 File 转换、媒体拒收检查和图片折叠配置，容器重建时恢复已启用的媒体接入。故障回退时须保留用户已填回的旧模板 ID。统一验收记录：legacy-media-user-acceptance.json。

## 当前正式行为

用户决定停止 A2UI 新卡片尝试并已自行重新填写旧模板 ID。A2UI 配置已停用，不再把真实单聊切到新协议。问答引擎仍为 WorkRAGGraph 0.3.10，保留原有真实正文流式、LangGraph、LangBot 模型 UUID 和 MCP 授权。

## 图片

当前每条回复最多 3 张，是 WorkRAG 后端和模板槽位的共同配置，不是平台上限。已基于当前 LangBot 官方旧模板生成补丁：

`data/manuals/runtime/agent-deployment/legacy-media-template/langbot-stream-with-folded-images.json`

仅在三个正文状态区各增加一个默认收起的图片区，保留原来的原生等待、流式、正文、思考折叠和底部操作。结构检查移除新增图片节点与变量后，与官方原模板完全相同。该文件为旧 editorData 格式，适用于旧模板编辑器；不是此前 A2UI 文件。

用户尚未确认导入发布。Host 已安装 `legacy_media_bridge.py`，但 `folded_template_published=false`；不会往不支持图片变量的旧模板里静默写图片并吞掉原生图片。用户确认发布后，执行 `deployment/install_legacy_media_bridge.py --folded-template-published` 并重启 Host、等待 MCP 恢复，再实际验收默认收起、展开及大图预览。模板 ID 必须与当前配置匹配。

## 文件

原文件通过原生附件返回，SDK 的 Message 与 MessageChunk 文件转换修复继续保留。新增平台接收者拒收、过滤、限流列表检查，避免把这些结果误认为发送成功。

`deployment/verify_legacy_file_delivery.py` 已实际经过旧 DingTalkAdapter 创建旧卡片并发送一份演示 DOCX；接口均返回成功，平台拒收检查未报错。回执位于 `legacy-file-adapter-acceptance.private.json`。用户是否收到并能打开仍待确认。脚本防重复发送，不能不检查结果就重跑。

`legacy_media_bridge.py` 的 SDK 离线验证覆盖：图片写入卡片后不再另外刷图片、保留 File、未发布时维持原输出、平台拒收报错。2 项通过。该结果不等于图片真机渲染通过。

启动器包含已经安装的媒体桥恢复逻辑，保持原有图片发布开关，不会因重建自动启用未发布模板。所有私有配置与日志留在本地忽略目录。

## Pi Agent

用户明确指的是 `https://github.com/earendil-works/pi`。已将官方 `@earendil-works/pi-agent-core`、`pi-ai`、`pi-schema` 固定为 1.5.0，安装在 `apps/pi-harness`，生成 lockfile。要求 Node >=22.19，本机为 22.20.0。

用真实 Pi Agent 核心和明确的模拟模型流完成 3 项离线兼容验证：真实增量事件、自定义工具执行后继续模型轮次、两个交错请求的状态隔离。尚未接真实 DeepSeek／LangBot 模型授权和 MCP，也未替换正式 Agent 节点。

建议接入范围：保留 LangGraph 外层 load/reuse/followup/finalize、SQL 和证据校验；由 Pi 独占内部模型／工具循环。新增每请求 Node worker 与 Python IPC，模型流和工具 RPC 通过 InvocationBridge 回到拥有 LangBot 授权的 Runner 任务，不复制模型密钥。必须继续执行原来的 6 次工具上限、180 秒超时、取消、2 请求并发、用户身份与本轮证据检查，避免 Pi 与原 Graph tools 节点重复执行同一调用。

上述只是已验证的迁移基础；正式引擎仍保留原状。
