# 新对话交接：本地覆盖与监督分类器 V3

工作目录 `H:\工作助手`，私有仓库 `lsdcasa-233/work-knowledge-assistant`。后续先读 `knowledge-intent-routing-v3.md`、`output/intent-routing-v3/验收记录.md` 和 `acceptance.json`。V1/V2 报告仍作为历史和已知回归，不能重称新验收。

用户要求只做前两项：提高本地覆盖率、训练专用 BERT。继续保留影子模式、Terra 补充分流和原有答复链路。不切换 Luna、不启用正式分流、不接通员工图片视觉和实际附件投递、不动资料索引或设计库。

V3 使用双维度 BM25 和监督 BERT 三个头（scope/output/clarification），投影到原有五种意图。基座是已校验的 Erlangshen 中文 BERT，冻结底层 11 层，训练顶层、pooler、三个新分类头，权重增量保存在私有 `data/manuals/models/intent/supervised-bert-v3`。不是继续用 NLI 假设打分，也不是全模型微调。

关键代码：

- `apps/backend/app/manuals/intent/supervised.py`：显式标签、受控请求文本、校验清单、局部微调网络、本地子进程、置信阈值和范围/输出冲突否决。
- `settings.py`：独立 V3 样例/结果路径、代码与数据指纹、上线还要求人工审核完成。
- `engine.py`：先 BM25、再任务 BERT、再现有 Terra；超时和未就绪不假装命中。
- `scripts/prepare-intent-v3.py`：合成样例生成，训练/开发固化后拒绝改写。
- `scripts/train-knowledge-intent-v3.py`：只读训练和开发集，开发集选择检查点，固定种子，私有权重清单；已封存的模型禁止覆盖训练。
- `scripts/calibrate-knowledge-intent-v3.py`：只用校准集定阈值；留出集打开一次，旧版同题对照、无 BERT 对照和 V1/V2 已知回归分别记录。
- `scripts/upgrade-knowledge-intent-v3.py`：只部署 shadow，保持 Terra 和回答模型，私有备份原配置。
- `scripts/verify-intent-v3-worker.py`：真实独立进程、超长输入放弃、硬超时终止；不发员工消息。

数据是代理检查的合成问题，不是脱敏真实员工问答。共享通用问句模板，语义改写独立性仍需人工审核。旧训练和开发集存在访客登记主题关系，已在审计中披露。不要把合成题准确率宣传成真实员工准确率，也不要将未决问题或 Terra 结果算入本地分类准确率。

本机启动 `scripts/start-manuals.ps1`；分类状态 `/api/v1/manuals/intent/status`；立刻回退 `python scripts/set-knowledge-intent-mode.py off`。该开关不改知识资料和原答案链路。后续需要的是人工审核、真实影子误分流观察和新版本评测；不能删除已打开结果后重拟合阈值。

GitHub 使用用户已授权的本机 Git 凭据，原 GitHub 连接器访问新仓库仍可能 404。源码和合成报告可以提交；`data`、密钥、员工文件、照片、数据库、权重和私有运行日志不上传。钉钉旧照片测试的未知结果继续只跟踪原会话，不自动重发。
