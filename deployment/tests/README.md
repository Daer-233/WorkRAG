# 离线兼容测试

test_legacy_media_bridge.py 验证正文通道、完成态顺序、折叠图片及文件保留；test_dingtalk_a2ui_bridge.py 保留已停用 A2UI 的模拟传输测试。测试使用模拟 HTTP，不发送真实消息，也不启用 A2UI。

需要 LangBot SDK 及 Host 模块，可在现有 LangBot 容器的临时目录运行。不要为了执行它们把其他环境或 Conda 加到项目运行路径。
