# 工作知识助手图文卡片 V1 · 交接

## 当前状态

2026-11-02 更新：即时状态和真实 Codex 增量已接入线上运行链路。Host 在启动 Runner、守护进程和模型前发出首帧；真实知识检索开始/结束事件更新“正在检索资料 / 正在生成回答”。现用模板通过兼容层在同一卡片显示状态和正文，约每 500ms 尾随刷新，最终沿用原有卡片图片上传路径。新模板的状态区也复用相同事件。

图片折叠、小缩略图和原文折叠仍属于下述待导入新模板；本次没有切换云端模板 ID。保留现有插件权限修订、知识库与模型配置。内部验证发现桌面 Codex 更新后旧程序路径失效，已仅修正该处理器的 command 字段并保存私有备份。即时状态无需等待新模板导入。

输出目录：`H:\工作助手\output\knowledge-card-v1`。先打开 `preview.html`，不需要卡片平台和模型 API。预览使用本机知识库真实返回的 11 张培训照片与 1 份来源；顶部流式演示明确是预设事件演示，不能当成实际 Codex 流式验收。

`dingtalk-template.json` 使用 editorData 字符串外层包装，可作为导入模板。模板尺寸、三列网格与图片属性已参照真实导出结构整理，但尚未在钉钉平台完成导入、渲染与发布验收。96×64 缩略图、窄屏尺寸、点击放大以及折叠后再次展开的本地状态，在本机 HTML 中经过浏览器检查；不能据此宣称钉钉真机也已通过。特别要检查原生 Image 的窄屏压缩与 CollapsePanel 的嵌套状态是否与预览一致，若平台行为不同，须修正新模板后再切换。

## 文件与变量

### 2026-11-02 即时状态部署

- `scripts/knowledge_card/streaming.py`：仅工作知识助手管道在 Runner 启动前发出首帧；现用模板复用同一卡片显示真实阶段和累计正文，约 500ms 尾随刷新。失败保留已生成文字；知识库繁忙不显示成正常完成。最终仍经既有图片上传和媒体引用处理。
- `scripts/install-knowledge-streaming.py --deploy`：为现用 Host、CodexAgent 容器和本机守护进程安装兼容补丁；不切换云端模板、不改权限或模型。`--rollback` 恢复初次部署前源码，私有备份位于 `data/manuals/runtime/knowledge-streaming-install.private.json` 指向的目录。
- `scripts/refresh-langbot-codex-command.py`：仅当旧桌面 Codex 路径已失效时，更新本处理器 command；原设置有私有备份。后续桌面程序更新再次更换路径时可重跑。
- 验证：16 项测试通过；容器内实际适配器与 SDK 的无外发检查通过；真实内部 Pipeline 完成 130 个流式事件。该次首次计算遇到检索超时/繁忙，API 等待超过 60 秒后只跟踪原会话，没有重复提交状态未知的请求。共享模型就绪后，一次独立只读检索耗时 7.14 秒，返回入职培训及原始第 6 页。
- 本轮未向钉钉主动发送测试消息，也未验收客户端显示时延或未导入的新模板布局。卡片中的阶段是处理状态，不是模型内部推理。

相关测试：`scripts/test_knowledge_card.py`、`scripts/test_knowledge_streaming.py`、`scripts/test_knowledge_dingtalk_media.py`。容器重建后重跑安装器并重启 LangBot、插件运行时及本机 Codex 守护进程；资料后端与共享模型无需重启。

- `scripts/knowledge_card/model.py`：只从本次 Host 工具结果生成来源和配图；保留版本/父流程边界；原始页码不取检索批次。模型正文可以用 `[[cite:证据UUID]]`，投影后映射成 `[1]` 等编号，未知编号不会成为来源。
- `scripts/knowledge_card/codex_delta.py`：支持 `item/agentMessage/delta`，用同条消息的权威完成快照回填，避免重复；不转发 reasoning 内容。保留原 Runner 执行、权限、取消与上下文逻辑，仅在原方法外增加兼容钩子。
- `scripts/knowledge_card/adapter.py`、`delivery.py`：每条回复有独立状态和约 500ms 的尾随刷新；立即显示阶段变化、最终/失败状态。模板开关未启用或模板 ID 不匹配时委托旧适配器。
- `variables.example.json`：卡片 API 线格式示例。`status/answer/notice/flowStatus` 为状态与正文；`images/sources` 是序列化 JSON 列表，固定的 `image_N/source_*_N` 是原生模板兼容投影。示例媒体 ID 是占位标识，不能用于真正发卡。
- `events.example.json`：运行级事件示例。`retrieval.completed.results` 必须传真实授权检索包，不能传模型自写的“参考资料”。

原生模板最多设置 12 张图、12 个来源槽。超出时有续查说明。来源标题默认可见，原文默认折叠；图片区默认展开前三张，余图在内层折叠区；图片区整体可收起。原文中的引用页码为空时明确说明缺页码。

## 重新构建与验证

在 `H:\工作助手` 下：

```powershell
& "$env:USERPROFILE\.conda\envs\design-rag\python.exe" scripts/build-knowledge-card.py --with-library
& "$env:USERPROFILE\.conda\envs\design-rag\python.exe" -m pytest scripts/test_knowledge_card.py scripts/test_knowledge_dingtalk_media.py -q
node scripts/check-knowledge-card-ui.cjs
& "$env:USERPROFILE\.conda\envs\design-rag\python.exe" scripts/install-knowledge-card.py
```

最后一条仅准备带 SHA256 清单的接入包，不部署、不修改线上。浏览器检查结果见 `ui-verification.json`，截图为 `preview-1440.png`、`preview-390.png`、`preview-320.png`。原生模板和增量钩子还需在新模板导入后真实联调。

## 恢复卡片平台访问后的接入

1. 新建独立 AI 卡片模板，导入 JSON，先在平台填入测试媒体 ID 和变量，检查图片尺寸、展开、收起、引用和移动端；保留原模板。
2. 平台验证通过后，执行以下命令，将 `NEW_TEMPLATE_ID` 换成新模板 ID。`--validated` 代表已经实际完成上述模板检查，不能为了跳过检查而使用。

```powershell
& "$env:USERPROFILE\.conda\envs\design-rag\python.exe" scripts/install-knowledge-card.py --activate NEW_TEMPLATE_ID --validated
docker restart langbot_plugin_runtime
docker restart langbot
powershell -ExecutionPolicy Bypass -File scripts/stop-langbot-codex.ps1
powershell -ExecutionPolicy Bypass -File scripts/start-langbot-codex.ps1
```

安装器只针对 LSD AI助手，备份旧模板 ID 与相关源码，给现有 CodexAgent 本地修订追加兼容钩子，不重装插件。开关位于 LangBot 的 `/app/data/work-knowledge-card-v1.json`；只有 `validated=true` 且模板 ID 匹配才启用新适配器。

3. 用钉钉真实单聊验收：立即出现状态；检索阶段确实可见；收到真实增量即更新；最后无重复段落；默认三图，展开 11 图；依据能展开且页码/版本正确；图片失败、繁忙和模型失败时文字仍可读。验证未通过时回退旧模板，不覆盖已有知识资料。

```powershell
& "$env:USERPROFILE\.conda\envs\design-rag\python.exe" scripts/install-knowledge-card.py --rollback
docker restart langbot
```

回退恢复旧模板并移除新卡开关；原增量兼容钩子保留。如要撤销钩子，使用私有 runtime 中 `card-*.before.py` 备份恢复对应文件，并重启相关进程。私有目录不可整包分享或提交，可能包含其他连接凭据。容器重建后需要重新部署接入包。
