# 工作知识助手 GPT-6 Luna 试切换记录 · 2026-11-03

## 最终状态

未将 Luna 保留为默认模型。已恢复本次切换前的处理器参数 `args-json=[]`，继续继承现有隔离环境的 `gpt-6.1-terra / medium`。本机全局 Codex 配置未修改；检索、权限、知识库绑定及钉钉路由未变。

用户条件是“合适就切换”。Luna 的文字问答可以工作，但完整照片流程没有通过验收，因此不能把整套助手宣布为已稳定迁移。也不能据此推断 Luna 本身不支持图片；官方模型文档列出图像输入、流式输出与工具调用支持，本次问题在现有接入链路。

## 已验证

- 官方名称与标识：GPT-6 Luna，`gpt-6-luna`。官方将其定位于明确、重复、高频的摘要、提取等任务；Codex 官方建议可从 High 开始尝试。
- 当前登录的 Codex 模型列表包含 Luna。实际新会话及已有会话均可解析为 `gpt-6-luna / high`。
- 实际运行的 `turn_context` 元数据确认模型为 Luna / High，不以模型自述作为切换证明。
- 入职制度题准确回答补卡 3 次、流程时效 30 天，并引用原文第 6 页、提供整理稿需求提醒。
- 未明确规定的游戏机福利问题没有捏造发放政策；引用的 3 个福利证据均真实且属于第 7 页。最初自动检查认为该题应完全不提醒文件，但该题实际检索到了相关福利资料，提醒引用资料的整理稿具有真实来源，不属于凭空提供附件。

## 未通过的部分

照片用例在观察期内未得到完成结果，监控原会话仍为 pending；排查中出现未授权 `design-rag-visual-search` 技能激活错误。没有为绕过错误授予设计库权限，也没有重新提交状态未知的照片问题。该内部测试没有向真实员工或钉钉群发消息。

使用本次模型的文字问答虽然完成，但耗时并不短；不据此承诺切换后整体更快。`acceptance.json` 的早期 `elapsed_seconds` 包含等待和后续读取结果的时间，不能当作模型推理耗时；后续脚本已改称 `elapsed_until_observation_seconds`。真实处理时刻应查原查询的 Host 日志。

## 文件与回退

- `scripts/set-knowledge-codex-luna.py`：仅为该 Pipeline 添加/回退模型参数；原参数有私有备份。当前已执行 `--rollback`。
- `scripts/knowledge_codex_model.py`：解决恢复旧会话时旧模型覆盖新默认值的问题；只对启动配置选择 Luna 的客户端设置 model/effort，不修改权限。2 项针对性测试通过。当前 Terra 配置不会触发 Luna 覆盖。
- `scripts/probe-knowledge-codex-model.py`：无模型回答、无平台投递的新旧会话参数核验。
- `scripts/verify-knowledge-luna.py`：内部 Pipeline 验收，只跟踪未知结果的原会话，不自动重发。
- `output/model-migration-luna-20261103`：模型解析、实际运行元数据和验收摘要；最终选择见 `decision.json`。

私有原答复、源证据与处理器备份位于 `data/manuals/runtime`，不可整包公开。后续如果继续尝试 Luna，应先限制到正确的工作知识检索工具并解决照片测试的未完成状态，再重新验收；当前没有实现文字/图片按模型分流。

官方来源：<https://learn.chatgpt.com/docs/models?surface=cli>、<https://developers.openai.com/api/docs/models/gpt-6-luna>。
