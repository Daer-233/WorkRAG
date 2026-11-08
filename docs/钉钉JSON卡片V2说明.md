# WorkRAG 钉钉 JSON 卡片 V2

按用户提供的钉钉官方组件文档重做，使用 **A2UI v1.0 + 钉钉 Public Catalog**，组件以 `component`、`id` 和平铺属性定义，通过 ID 引用组成组件树。这不是旧 `editorData` 搭建器导出格式。

生成目录：`G:\项目\WorkRAG\data\manuals\runtime\agent-deployment\card-json-v2`。

| 文件 | 用途 |
|---|---|
| workrag-card.a2ui.json | 创建画布、初始化数据、声明完整组件树 |
| create-wire.json | 机器人请求中的协议版本、状态与字符串数组 a2uiMessages；仍需服务端填写目标与 outTrackId |
| stream-update.a2ui.json | 累计正文与状态文字更新示例 |
| finish-update.a2ui.json | 最终正文及反馈入口示例；请求外层另需 flowStatus=FINISH |
| image-update.a2ui.json | 设置图片地址、显示默认折叠区域；地址是占位值，须替换 |
| file-update.a2ui.json | 设置文件名称、地址、大小与类型；地址是占位值，须替换 |
| preview.html | 使用虚构 PNG／DOCX 的本地布局演示，不是钉钉渲染证明 |
| validation.json | 官方工具的实际校验输出 |

卡片包含状态、Markdown 正文、“查看图片／获取原文件”按钮、默认收起的图片和来源区域、原生 File 组件，以及“有帮助／需改进”反馈入口。图片区 `defaultExpanded=false`、`maxHeight=360`，预留 3 个可点击预览的 Image 槽。

按钮声明 `workrag.resource.request` 和 `workrag.feedback` 事件，携带回答 ID、资料 ID、版本。服务端必须按真实回调身份重新检查归属和权限，不能信任按钮提供的身份或权限。动作声明不等于回调已经接通，也不能依赖 wantResponse 自动更新；业务端需调用更新接口。

## 当前边界

### 最新进展：权限通过，文字接入已启用

用户已开通新接口权限。修正单聊投递参数后，新接口创建 HTTP 200、单聊 deliverResults.success=true、完成更新 HTTP 200 且 business_success=true。新 API 使用 `imRobotOpenDeliverModel.robotCode`，不能沿用旧接口的 `spaceType`。本人的私聊文字接入已安装启用，其他会话保留原来的输出。

用户第一次实际问答仍收到普通消息，已定位为机器人当前旧模板 ID 为空，Host 因此将流式能力判为 false，新卡接口没有被调用。现已补齐 A2UI 无旧模板的能力判断并重启验证 supported=true，正在等待用户复测。尚不能宣称处理中与流式显示通过。新卡内图片、文件和按钮仍未接入，原生附件链路继续保留。

启动器已增加已启用接入模块的容器重建恢复；停用命令为 `deployment/install_dingtalk_a2ui_bridge.py --disable`。不改变已发送卡片。模块原始文件备份位于 Host 持久化 data 目录。

### 先前接入记录（已解决的权限阻塞）

已复用现有机器人凭据向用户之前确认的本人单聊测试新接口。钉钉实际返回 HTTP 403、`Forbidden.AccessDenied.AccessTokenPermissionDenied`；未创建测试卡。官方要求应用具备 `AICard.Instance.Write` 权限，需用户在钉钉开发者后台为当前应用开通。原卡片仍可使用，未切换线上绑定。

`deployment/dingtalk_a2ui_bridge.py` 已准备新卡创建、真实正文增量更新和完成状态的接入模块，3 项离线测试通过。`deployment/install_dingtalk_a2ui_bridge.py` 提供受权限探测结果约束的启用入口和停用回退；在 403 未解决前拒绝启用。首次启用仅针对已确认的本人单聊，其他会话继续走原卡片。尚未实际安装此模块；图片、文件继续用现有原生附件，卡片内媒体和按钮回调仍需后续接线及真机验收。

权限开通并生效后，由接手者执行 `deployment/check_a2ui_private_access.py --retry-after-permission` 重新检查；该参数仅允许重试已明确返回 403 的上次请求，不会自动重复发送结果未知或已成功的卡片。检查每个投递目标以及完成更新结果后，再安装接入模块、重启 Host 并等待 MCP 就绪。不要仅凭模板校验通过绕过权限检查。

官方 DWS v1.0.67 与用户指定仓库的 Python 校验器均用于预检。仓库快照提交为 `6a40d5cd2c7195aaffecbd38edf3a821451ea95f`，最终通过结果以 validation.json 为准。离线校验不能证明绑定求值、资源加载、客户端渲染和实际回调，这些仍待真实接入验收。新卡尚未发送、线上绑定未修改。

已应用官方仓库的 dingtalk-aicard 编写规范：根布局使用无背景、无额外外边距的 Column，让钉钉宿主控制外观；运行中的 Markdown 使用 `[AIGenerating]` 标记，完成或失败时移除。来源与图片默认收起，不公开内部推理或原始工具参数。

初始资源值为空且隐藏。接入时先确认用户、已发布资料和版本，再提供客户端可访问的授权地址；不能把 127.0.0.1、host.docker.internal 或本地路径当作员工下载地址。图片与文件更新示例中的 example 域名不可直接使用。

新协议通过机器人 `/v1.0/card/ai/instances/createAndDeliver` 等接口发送，不要求预先在旧搭建器发布模板。当前 LangBot 仍走旧 `/v1.0/card/instances/createAndDeliver` 和 cardTemplateId 链路，需单独适配新协议。**不要将此文件导入旧 editorData 页面或填成模板 ID。**

当前问答引擎已安装 0.3.10；原有卡片的真实流式已由用户确认，每次约 3–4 个汉字。新模板本身不保证逐字一帧；需要实际持续发送正文增量，更新请求外层设置 INPUTTING／FINISH。彩色边框效果仍未验收。

用户提供的“消息类型不匹配或缺少 query，忽略处理”尚未在当前源码及最近容器日志中定位，不能断言是模板错误。新卡动作应进入独立事件处理链，不应强制要求它带普通聊天的 query 对象。

## 重建

```powershell
cd G:\项目\WorkRAG
.\.venv\Scripts\python.exe deployment\build_dingtalk_json_card.py
& .\data\manuals\runtime\agent-deployment\card-json-reference\dws-tool\dws.exe aicard lint --file .\data\manuals\runtime\agent-deployment\card-json-v2\workrag-card.a2ui.json --preflight new-card
.\.venv\Scripts\python.exe deployment\verify_dingtalk_json_card.py
```

重建覆盖本地生成物并将校验状态复位，须保留新的实际校验结果。服务端接入后，每条回答需分配独立 surfaceId／outTrackId，更新沿用原卡 ID；示例固定 ID 不可用于多人共享的全局卡片。

官方依据：[JSON 构建卡片](https://open.dingtalk.com/document/development/json-build-card)、[组件概述](https://open.dingtalk.com/document/development/json-card-component-overview)、[官方规范仓库](https://github.com/DingTalk-Real-AI/dingtalk-aicard)。
