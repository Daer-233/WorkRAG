# 工作知识助手：意图分流 V1

实施日期：2026-11-03。当前部署为 **shadow（影子模式）**。它记录拟分流结果，员工的回答仍走原链路；不会等待影子分类完成后才开始回答。当前验收未过，不能切换正式分流。回答模型固定为 **gpt-6.1-terra / medium**；独立补充分类使用 **gpt-6.1-terra / low**。

## 当前实现

本机接口为 `POST http://127.0.0.1:8060/api/v1/manuals/intent/route`，请求头为 `X-Manual-Request: 1`。继续使用现有本机访问限制，不增加公网入口。状态接口为 `GET /api/v1/manuals/intent/status`。

输入字段：

| 字段 | 含义 |
|---|---|
| text | 当前文字，最多 4,000 字符 |
| attachment_types | Host 从实际消息识别的 image / file / audio / video |
| history | 最近两轮对话，最多四条，单条不超过 2,000 字符 |
| previous_sources | 上一条回答实际检索并引用的资料 ID、名称、版本和原件状态 |
| previous_file_offer | 上一回答是否确实提出文件提醒 |

响应包含 `intent / method / mode / has_image / needs_clarification / message / reason / scores / margin / config_version / elapsed_ms / local_elapsed_ms`。`scores` 是各意图的匹配值，不是准确率百分比。员工传入额外的路由、知识库或技能字段将被拒绝。该接口的上下文字段供本机 Host 传递；员工原话不能作为这些字段或授权快照。

分类顺序为：程序确认的附件与文件追问上下文 → 独立 BM25 样例索引 → 本地 BERT-NLI → 一次 Terra 补充分类 → 澄清。公司制度没有检索证据时仍不能转为通用回答。

## 本地分类模型

独立目录：`H:\工作助手\data\manuals\models\intent\erlangshen-110m-nli`。来源为 ModelScope `Fengshenbang/Erlangshen-RoBERTa-110M-NLI` 的 `v1.0.0`。`intent-manifest.json` 记录每个文件 SHA-256、模型来源、版本和实际标签；蕴含标签从模型配置读取，缺失、歧义或校验失败就不启用。

运行时只读本地文件，不下载模型，不调用 MinerU 或视觉服务。BERT 独立进程、并发 1、CPU 2 线程；先完成模型及计算预热，再接收推理。在线单次推理限时 2 秒，超时杀掉该模型进程，转入一次 Terra 分类；超时后冷却 5 分钟，避免每个问题都重新加载模型。首次导入依赖和模型约需一分多钟，期间允许使用 Terra 分类。

当前机器的浮点推理线下探测约 4 秒，不能满足在线限时。另做过同模型的临时整数推理实验，也未达到目标；**没有将整数推理试验加入生产模型**。不能因为模型文件存在，就声称 BERT 已达到正式上线要求。

Terra 使用当前 Codex 登录副本、空工作目录和临时内存会话，不接入业务 MCP、知识库或技能。禁用可发现的本地技能、Shell、Code Mode、网页搜索及多 Agent 功能；工具请求会被拒绝，结果丢弃。只接受五种意图的严格 JSON，20 秒到期或非法输出即澄清，不重试。分类 JSON 不写入员工对话。退出后删除临时登录副本；Windows 若暂时锁住无凭据缓存，会记录待清理状态。

配置依据：[官方 App Server 协议](https://learn.chatgpt.com/docs/app-server)、[本地技能禁用配置](https://learn.chatgpt.com/docs/build-skills)。

## Host 接入与权限

入口仍先输出“正在处理”，之后才分类。正式模式才应用路由；影子模式在后台运行，不等待分类，不修改原有正文、图片或引用。

Host 使用本次调用的内部状态保存分类，按 workspace、bot、pipeline、query、event 关联；员工变量中的同名值不起作用。不修改原始 Pipeline 配置，不改授权撤销校验。

- daily：授权快照中的业务工具、知识库、技能与共享存储为空。
- knowledge / images：仅从正常授权清单中保留工作知识库，不新增授权；无设计库和设计技能。
- source_file：明确追问上一份文件时使用上一回答的真实来源；多份来源先询问。当前没有实际附件发送能力。具名的新文件需求进入现有工作知识检索，不能拿上一份资料冒充。
- clarify：使用同一卡片提出简短问题，不启动回答模型。
- 员工上传图片不会传入视觉理解；文字可用时按文字处理并说明未读取图片，仅图片或缺少可用问题时要求补充文字。

最近两轮上下文保存在 Host 内存，有效期 30 分钟、最多 1,000 个会话；按会话与员工隔离。清空对话或重启 Host 后丢弃。来源只从 Host 检索返回的数据包生成，不能从模型自报来源建立。路由日志只记录层级、意图、分数、耗时、配置版本及降级原因，默认不保存完整提问。日志轮转：`data\manuals\intent\routing.log`，单份约 2 MB，最多三个历史文件。

## 样例、校准与验收

`instances\manuals\intent-samples` 包含 80 条索引样例、60 条校准题和 100 条独立验收题；验收题包含至少 30 条边界、混合需求或多轮题。样例基于工作场景合成，并由本次实现逐条标注和检查，**不是实际员工聊天记录，不代表部门业务人员已审核**；JSONL 中明确保留 `human_review: pending`。

样例的具体请求家族不跨数据集；审计检查家族、完全相同的请求及上下文、数量、标签和边界数量。新增同一问题的改写时必须留在同一 split，不能用验收题反调阈值。当前同一短追问在不同真实上下文里会有不同标签，这是独立的多轮场景。

阈值只用 calibration 拟合，按意图设置最高样例得分与第一、第二意图分差；校准接受至少三题且零错误才生成对应门槛，没有可靠门槛就不直接接受。NLI 使用原始蕴含分数和意图间分差，不加设计关键词或人为置信度。

报告：`data\manuals\intent\calibration.json`、`acceptance.json`，以及 `output\intent-routing-v1`。报告与数据、模型清单、分类代码和 Host 辅助代码哈希关联；变动使旧门槛失效。离线 `--diagnostic-nli-timeout 15` 仅为完整采集原始分数与耗时，不改变线上两秒限时；超过两秒的 NLI 结果不计入自动接受。

正式启用须同时满足：公司问题误入 daily 为零、自动接受准确率至少 95%、明确问法覆盖至少 60%、本地预热 P95 不超过 1 秒，以及内部集成和影子观察通过。当前门槛未过，后续需改善校准数据与本地推理，不允许直接打开 on。

## 部署与回退

使用本机现有 Python：`C:\Users\liwj\.conda\envs\design-rag\python.exe`，工作目录为 `H:\工作助手`。以下命令中的 `python` 应指向该环境。

```powershell
python scripts/prepare-knowledge-intent-model.py --download
python scripts/build-knowledge-intent-samples.py
python scripts/calibrate-knowledge-intent.py --calibrate --diagnostic-nli-timeout 15
python scripts/install-knowledge-intent.py --deploy
python scripts/set-knowledge-intent-mode.py shadow --pin-answer-model
```

重载后端与 LangBot 后生效。重载应避开员工正在回答的请求；不要为了加载分流去重启设计库、PostgreSQL、Qdrant、Embedding 或 Rerank。首次安装或修改 daemon 模型钩子时还须重载本机 Codex 后台。当前已完成首次重载，钉钉连接守护继续启用。

Host 钩子安装在当前容器源码中，普通 restart 会保留；若删除并重建 LangBot 容器，需要重新执行安装脚本并重载，再核验钩子，不要只复制开关配置就宣称已启用。

配置示例：`instances\manuals\intent.example.json`；实际配置为 `data\manuals\intent\config.json`，Host 配置在容器 `/app/data/work-knowledge-intent.json`。推荐通过脚本同时切换，防止两端不一致：

```powershell
# 即时关闭后续请求的分流，恢复原链路，无需删除资料或重建索引
python scripts/set-knowledge-intent-mode.py off
# 恢复影子观察，不影响员工回答
python scripts/set-knowledge-intent-mode.py shadow
# 只有全部门槛报告有效时才允许；当前会拒绝
python scripts/set-knowledge-intent-mode.py on
```

还原 Host 代码可用 `python scripts/install-knowledge-intent.py --rollback` 后重启 LangBot；先设 off。原始备份在私有 `data\manuals\runtime\intent-install.private.json` 指向的目录。无需卸载现有卡片修订。备份时保存配置、JSONL 样例、校准/验收报告和模型清单；密钥与登录文件按现有私有备份方式保存，不能放入交接文档或公开仓库。

本期没有新增管理页面、员工图片识别、附件投递、图谱功能或跨设计库检索。旧照片测试未知结果不重发，本次只用独立内部合成事件验证。
