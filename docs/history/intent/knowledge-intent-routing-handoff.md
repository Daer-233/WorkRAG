# 新对话交接：BM25＋BERT 意图分流

当前以 `knowledge-intent-routing-v2-handoff.md` 为准。本文件保留V1实施历史，不代表当前分类结构。

日期：2026-11-03。工作目录 `H:\工作助手`。请先读 `docs\history\intent\knowledge-intent-routing-v1.md` 和 `output\intent-routing-v1\acceptance.json`。

## 当前结论

代码、独立接口和 LangBot Host 接入已经实现并部署，但 **正式上线门槛没有达到，保持 shadow**。LSD AI助手的真实回复仍沿用原链路，影子分类在后台记录；不要把“已部署”写成“已正式分流”。用户明确同意未达门槛保持影子模式。

回答模型锁定 `gpt-6.1-terra / medium`；补充分类 `gpt-6.1-terra / low`。不启用 Luna，不接员工上传图片的视觉理解，不发送实际文件附件，不改知识库混合检索，不扩大设计库权限。

## 实测结果

| 项目 | 结果 |
|---|---|
| 回归检查 | 33 项通过，含分流、卡片增量、媒体、模型恢复、文件上下文、服务故障 |
| 真实 Host 合成事件 | 通过；实际授权注册器与代理校验拒绝日常检索、设计库、设计工具和技能；跨 workspace 仍拒绝 |
| 合成正式路由作用域 | 只在独立测试解释器模拟 on，确认状态能传到真实 Host 资源构造器；生产仍 shadow |
| 真实分类接口边界探测 | “你好，补卡怎么申请”“Excel 怎么筛选”“润色报销通知：…”“发我报销模板”均由 Terra 返回预期意图，约 12–14 秒 |
| 100 题独立离线验收 | 自动接受 45 条、正确 37 条，准确率 **82.22%** |
| 明确问法自动覆盖 | **54.39%**，31 / 57；未达到 60% |
| 公司问题误入 daily | **1 条**；门槛要求零 |
| BERT | 原始浮点推理 P95 **5,109 ms**；100 条均超过在线两秒限时，不计为在线自动接受 |
| 人工业务审核 | 未做；样例标注 `human_review: pending`，不能写成 HR 已验收 |
| 钉钉真实新路由问答与新卡片上线 | 未执行；没有向员工主动发送测试消息 |

离线耗时是顺序计算 BM25＋原始 NLI 的诊断探测，不是正常在线请求 P95。在线 BERT 仍是两秒硬截止；长诊断等待没有放宽生产限时。BERT 冷启动导入和预热约一分多钟，不能误报为服务挂掉。

8 条错误见验收 JSON。尤其“先讲个笑话，再查一下公司的调休制度”被 BM25 判为 daily，必须解决后才可能上线。还有公司问题误入图片、源文件误入图片及信息不足误入文件/日常。不能拿这 100 条验收题反向调阈值；后续版本需要新的独立验收题。

## 关键代码与配置

- 后端：`apps\backend\app\manuals\intent\`，`manual_main.py` 挂载接口并后台预热。
- Host：`scripts\knowledge_card\intent_host.py`，由现有 `streaming.py` 在立即回执后调用。
- Host 实际钩子：容器 `langbot` 的 `agent/runner/query_bridge.py` 与 `resource_builder.py` 文件末尾 bootstrap；所有原权限、撤销和原始 Pipeline 配置保留。
- 模型：`data\manuals\models\intent\erlangshen-110m-nli`，ModelScope 固定 `v1.0.0`，SHA-256 清单与真实蕴含标签校验。
- 数据：`instances\manuals\intent-samples\index.jsonl`（80）、`calibration.jsonl`（60）、`acceptance.jsonl`（100）。来源为整理的合成工作场景，不是真实员工记录。
- 生效配置：`data\manuals\intent\config.json`；Host `/app/data/work-knowledge-intent.json`。
- 报告：`data\manuals\intent\calibration.json` / `acceptance.json`，镜像交付在 `output\intent-routing-v1`。
- 日志：`data\manuals\intent\routing.log`，轮转，不写完整正文。不要输出私有配置、API Key、登录文件或图片签名 URL。
- 安装：`scripts\install-knowledge-intent.py`；模式：`scripts\set-knowledge-intent-mode.py`；模型准备：`scripts\prepare-knowledge-intent-model.py`。
- 原始安装备份索引：`data\manuals\runtime\intent-install.private.json`，不要公开。

首次下载时只复制公开模型的 config、vocab、weights。运行时 `local_files_only=True`，不自动联网。没有沿用旧设计库二分类提示词、设计关键词加分和默认蕴含下标。

## 后续工作顺序

1. 保持 shadow，先看错误和原始 NLI 分数；通用 NLI 的意图假设目前没有可靠地区分全部类别，校准仅为 source_file 产生门槛，且性能不允许在线自动接受。
2. 在不增加 CPU 负担的前提下，评估可测的推理加速方案。一次临时 torch 整数量化试验仍约 2.3–2.6 秒，未部署，不要称其已解决性能。
3. 补充新的、经业务核实的混合需求/多轮校准场景。改善 BM25 的接受判定，优先避免公司问题进入 daily；任何改写留在同一问题家族的数据 split。
4. 新版本重新校准并准备新的独立验收集，核验准确率、覆盖、公司误入日常为零，以及真实本地 P95；离线报告还不能代表完整员工端效果。
5. 通过后再进行充分影子观察，记录后才允许人工确认 `shadow_passed`；不能为开关修改 JSON 假装通过。
6. 仅全部条件达到后，LSD 单聊正式启用并由用户验证卡片；不要自动向员工发消息。旧照片未知测试只跟踪原会话，不自动重发。

校准脚本的 `--reuse-scores` 只在数据、模型、BM25/NLI 推理及上下文代码哈希一致时允许复用原始测量；适用于修订路由服务或报告后重新确认门槛，不是重测耗时。推理或资料变动必须重新实测。

## 服务与操作

本机后端8060，LangBot5300，本地 Embedding8031、Rerank8032；工作数据库 `manual_rag`，向量集合 `manual_rag_chunks_v1`。知识资料和设计库没有迁移或重建，本次不改任何知识索引。

Python：`C:\Users\liwj\.conda\envs\design-rag\python.exe`。新对话不要换成系统 Python。入口仍为 `http://127.0.0.1:8060/knowledge/`。

```powershell
python scripts/set-knowledge-intent-mode.py off
python scripts/set-knowledge-intent-mode.py shadow
python scripts/set-knowledge-intent-mode.py on   # 当前会被门槛拒绝
python -m pytest scripts/test_knowledge_intent.py scripts/test_knowledge_streaming.py scripts/test_knowledge_card.py scripts/test_knowledge_codex_model.py scripts/test_knowledge_dingtalk_media.py -q
```

后台与钉钉守护已随首次部署重载。重启 LangBot 后检查健康和 `data\manuals\runtime\connection-watchdog\status.json`。Docker 健康不等于钉钉连接成功，守护按原规则检查，不扩大恢复权限。

关闭/回退和门槛保护已通过真实开关验证，见 `output\intent-routing-v1\mode-rollback.json`。在线真实 NLI 超时探测也已完成，见 `live-nli-timeout.json`；进程确实结束后才交给一次 Terra，含进程回收的本地耗时2,297ms。最终后端重载包含五分钟超时冷却与不可下载源文件的准确提示。重建容器后需要重新安装 Host 钩子。

真实 Host 检查可把 `scripts\verify-knowledge-intent-host.py` 复制到 `langbot:/tmp/verify-work-intent.py`，用容器虚拟环境 Python 执行；它用合成事件，不调用平台消息发送。可在检查后读取 JSON，不要输出容器环境变量或私有 Pipeline 全量配置。
