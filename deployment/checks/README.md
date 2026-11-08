# 诊断与验收工具

从仓库根目录运行，解释器使用项目 .venv。脚本已添加共享部署模块的路径处理，移到此目录后可直接执行。

| 脚本 | 行为 |
|---|---|
| verify_host_contract.py | 检查当前 Host 权限及实际 SDK，使用模拟提供商 |
| verify_pi_contract.py | 实际 SDK + Pi 模拟接口验收；会在需要时启动 Pi |
| verify_pi_real.py、verify_pi_pipeline.py | 调用已配置真实模型和 MCP，会消耗 API 用量并保存测试会话；不向钉钉发消息 |
| verify_pi_release.py、verify_real_model.py | 真实异常验收，会暂改调试配置；后者会暂停恢复检索后端 |
| verify_local.py、restart_agent_verify.py | 资料初始化／持久化及重启验收，可能修改测试资料或重启服务 |
| verify_legacy_*_delivery.py、send_demo_file_to_inbound_tester.py | 仅向先前确认的本人单聊投递测试卡片或附件，检查回执后再运行，不盲目重复发送 |
| check_*、verify_dingtalk_json_card.py | 平台权限／模板能力检查；部分权限探测会投递测试卡片，执行前阅读说明 |
| verify_agent.py | 模拟模式的调试及反馈验收，不适用于真实模型模式 |

本次文件整理只检查结构、引用和离线兼容，不自动运行真实模型、消息投递或服务重启验收。
