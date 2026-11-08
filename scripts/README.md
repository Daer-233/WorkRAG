# 辅助脚本说明

日常启停请使用项目根目录的按钮和 deployment/local.py。本目录混合了旧部署工具与仍共用的辅助模块，因此没有机械搬迁，以免破坏相邻模块导入和运行中的路径。

| 类别 | 常见文件 | 当前定位 |
|---|---|---|
| 资料实例与导入 | manual-instance.py、generic_knowledge_import.py、import-*.py | 当前初始化或手动导入的辅助入口 |
| 旧 Codex / Host 接入 | langbot-codex-*、install-knowledge-*、knowledge_dingtalk_* | 旧路线保留；不能当作当前 Pi 安装步骤批量运行 |
| 意图分类实验 | *intent*、benchmark-intent-training.py、*calibrate* | 历史 BERT / 分类实验，当前 Pi 流水线不启用 |
| Milvus | *milvus* | 历史适配与迁移，当前主库使用 Qdrant |
| 付款平台 | *payment* | 历史模块，未接当前员工只读助手 |
| test_* / verify-* / check-* | 各子模块测试与诊断 | 与历史模块配套，阅读脚本说明后按需使用 |

历史设计文档已归类到 docs/history。旧机器的 Conda、H/I 盘和实例 UUID 不作为本机默认配置。
