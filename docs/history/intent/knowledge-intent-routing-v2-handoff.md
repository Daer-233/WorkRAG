# 新对话交接：前三项分流改进

2026-11-03，当前目录 `H:\工作助手`。先读 `knowledge-intent-routing-v2.md` 与 `output/intent-routing-v2` 下的报告。GitHub项目为私有 `lsdcasa-233/work-knowledge-assistant`，本机Git凭据已经由用户完成浏览器授权，不在聊天或源码中索要令牌。

用户明确要求：优先完成分类结构、BM25接受条件、混合/多轮校准样例三项，**保持shadow、Terra补充和原回答链路**。不要开启on，不更换回答模型，不扩展到员工上传图片识读或文件投递。

当前结构是“公司资料范围 × 输出形式 + 澄清”，通过 `Axes.intent` 投影到旧五路由。接口增加axes信息，Host权限、原始Pipeline配置、流式卡片和知识检索均保持兼容。

V2索引120、校准120、新验收100。旧V1的100题只算已知回归。新验收明确需求80条，含边界但仍在分母；本地接受38/80=47.5%，38条均正确，公司误入daily为0。覆盖未达门槛；未决62条不计为正确。

首次独立结果已冻结。随后根据旧V1的两项截图/附件回归追加了仅拒绝的检查，阈值没有重新拟合。当前100题回放保持38条正确，旧回归中两项改为交Terra，旧回归本地26条均正确。原始独立报告及单调收紧证明保留，不要删除或改称一轮新的独立成绩。

真实API首次12例并非全通过：一次Terra超时安全澄清；一个未指明制度的问题被Terra澄清，与预期知识路线不同。保留首次记录，不能用后续成功覆盖这些结果。快速路径延迟仅代表校准题的本地BM25路径，不代表全部问题和员工回答速度。

重要路径：

- `apps/backend/app/manuals/intent/factors.py`：范围/动作索引、支持与覆盖、指代/正文/公司证据及输出冲突检查。
- `types.py`：严格Axes与向旧路由的投影；`terra.py`：同一隔离会话方式、双维度JSON、一次20秒。
- `engine.py`：运行集成；`settings.py`：V2样例/报告路径及哈希；`api.py`：可查询版本与NLI验证状态。
- `instances/manuals/intent-policy.v2.json` 与 `intent-samples/v2`：版本化策略及合成样例，业务人员审核仍pending。
- `scripts/calibrate-knowledge-intent-v2.py`：只在未打开验收集之前拟合；旧版校准脚本禁止误用于当前V2。
- `scripts/revalidate-knowledge-intent-v2.py`：本次仅拒绝修订的校验，依赖私有原始快照；不是任意重新调阈值的入口。
- `scripts/upgrade-knowledge-intent-v2.py`：只迁移shadow配置，校验冻结报告，不修改回答模型或语料。
- `scripts/verify-knowledge-intent-v2.py`：内部分类/延迟探测，不发送平台消息。
- `scripts/test_knowledge_intent_v2.py`：因素投影、正文、混合需求、公司范围、输出冲突、一次降级及验收封存。

现有BERT权重没有修改。旧NLI没有验证新因素，且原本耗时超标；当前保留适配器但不复用它的旧门槛、不加载未验证模型。本次不能声称训练了新BERT或解决了它的性能问题。

当前后端配置：`data/manuals/intent/config.json` 的 `intent-v2-factors / sample_set=v2 / mode=shadow`；Host版本配置同步。V1数据和报告没有被覆盖。仅重载本机8060后端；模型8031/8032、设计库、LangBot处理器和卡片模板不需更换。

后续不要用已经打开的100题反调阈值。先让部门人员核查合成问法的业务分类，补充新的独立问题家族，再做下个版本。BERT专门分类训练和CPU优化是后续任务，未包含在本次授权前三项中。

如需回退到原员工回答路径，运行 `set-knowledge-intent-mode.py off` 即可，不删资料或重建索引。实际权限与状态检查、开关验证和部署记录在 `output/intent-routing-v2`。检查报告里的实际通过项，不要把shadow部署写成正式启用。
