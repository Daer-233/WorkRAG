# 本地覆盖率与专用 BERT 分类器 V3

本次只改进本地分流覆盖率、训练专用 BERT。保持 `shadow`，员工仍走现有回答链路，回答模型 Terra / Medium、补充分类 Terra / Low 不变。知识资料、向量检索和设计库未改动。实际结果见 `output/intent-routing-v3/acceptance.json` 和验收记录。

## 分类方式

元数据和缺失信息检查 → 扩充样例的双维度 BM25 → 监督训练的 BERT → 一次 Terra 补充分类 → 必要时澄清。BERT 的三个头分别输出公司/通用范围、文字/图片/源文件形式、是否澄清，再校验为原有五种路由。标签来自明确映射，不使用原 NLI 的标签下标，也不把匹配分数说成准确率。

BERT 在独立进程运行，CPU 2 线程、并发 1；单次调用硬超时 2 秒，超时终止该进程并交给现有回退。启动加载和预热另行计时；尚未就绪不阻塞员工回复。超长输入不静默截断后接受分类，而是交给 Terra。显式公司问题不能因为包含“一般”等词就接受日常路由。

## 训练和数据

复用已经固定并校验的 Erlangshen-RoBERTa-110M-NLI 的 BERT 编码器，丢弃 NLI 分类头。冻结底层 11 层，训练第 12 层、pooler 和三个专用分类头。属于部分微调，不是完整模型微调。训练使用 CPU 4 线程，运行时为 2 线程，不修改共享 Embedding/Rerank 模型。

数据目录：`instances/manuals/intent-samples/v3`。训练 784 条、开发 114 条、校准 148 条、主题留出验收 148 条。训练可使用原 V2 的索引/校准集；已打开的 V1/V2 验收集只做已知回归。训练脚本只读取训练和开发集；开发集选择检查点，校准集定阈值，随后封存模型、代码和配置指纹再评测留出集，不依据验收集反复调阈值。

这些是人工整理的合成场景，由代理检查标签，`human_review=pending`。不同组的家族标识和完整上下文请求不重复，但共享通用问句模板，语义改写关系仍需人工审核。已发现旧训练样例和开发集都含访客登记；开发集仅用于选择检查点，不作为独立准确率结论。不能据此声称已经达到真实员工语料准确率。多轮、混合需求和纯图片场景另有记录。上线仍需人工审核和真实影子观察。

私有权重在 `data/manuals/models/intent/supervised-bert-v3`，只保存训练参数增量 `delta.safetensors`，基座不复制。清单固定基座清单与权重校验值、训练参数校验值、显式标签、输入长度、训练/开发数据校验值、种子、最佳轮次。运行禁止下载模型或执行远程模型代码。权重、缓存、员工资料和密钥不进入 Git。

## 运行与回退

在项目目录使用现有 `design-rag` Python 环境：

```powershell
python scripts/prepare-intent-v3.py
python scripts/train-knowledge-intent-v3.py
python scripts/calibrate-knowledge-intent-v3.py calibrate
python scripts/calibrate-knowledge-intent-v3.py evaluate
python scripts/verify-intent-v3-worker.py
python scripts/upgrade-knowledge-intent-v3.py
```

训练和校准封存后拒绝覆盖；新一轮实验必须新版本，不能删除已打开的验收结果后重调。以上命令供复现说明，本机已经完成的步骤不要重复执行。配置示例在 `instances/manuals/intent-config.v3.example.json`，实际配置在私有的 `data/manuals/intent/config.json`。

升级脚本仅允许影子模式；先让 Host 保持影子，再更新后端配置，保存原配置私有备份。重新启动工作助手后端后加载新进程，不重启共享模型或 LangBot。状态入口为 `GET /api/v1/manuals/intent/status`，分类接口不变。后台未准备好、校准指纹失效时继续回退 Terra，不扩大权限。

随时关闭：

```powershell
python scripts/set-knowledge-intent-mode.py off
```

恢复影子观察使用 `shadow`。正式 `on` 仍需质量、集成、影子观察、人工审核完成且指纹一致；仅有合成集通过不能启用。关闭不改资料、数据库、索引、卡片或回答模型。

模型实现参考：[Transformers BERT](https://huggingface.co/docs/transformers/model_doc/bert)、[PyTorch AdamW](https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW.html)。
