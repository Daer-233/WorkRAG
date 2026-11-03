# 钉钉工作知识库图片投递

## 当前更新：卡片内图片

用户已确认独立图片消息可以收到，随后要求图片放进卡片，并删除逐张配图说明及技术证据 UUID。当前实现改为：读取原有签名图片 → 上传钉钉媒体 → 在原图片位置保留 `![分类](media_id)`，不再重复发送独立图片消息。支持完整本机地址及 `/api/v1/manuals/assets/...` 相对地址。保留分类标题和资料来源，证据 UUID 仍留在检索元数据。

`scripts/check-knowledge-dingtalk-media.py --live-upload` 使用真实照片和机器人凭据上传媒体，然后模拟最终卡片发送入口检查图片引用；不会发送聊天消息。卡片客户端是否实际渲染须单独人工验收，上传成功和文本引用生成不等于已经完成客户端验收。若当前卡片模板不能渲染 media_id，不应称为已支持；需调整卡片图片组件或采用可访问的受控图片地址。

以下为此前独立附件阶段的记录。

2026-10-30：培训照片可以检索，但原回复中的本机图片 Markdown 地址无法由钉钉手机端访问。

本地扩展安装在 LangBot `dingtalk-omni` 适配器中：普通回复或流式最终回复把知识库签名图片链接读取为缩略图，再转换为原生 Image(base64) 组件，复用现有 DingTalkClient 上传及发送接口。回复文字保留来源和图片顺序。中间流式片段不上传，避免重复投递。

仅允许 `http://127.0.0.1:8060` / `localhost:8060` 的 `/api/v1/manuals/assets/{UUID}` 签名地址；容器固定访问 `host.docker.internal:8060`，由知识库验证签名。拒绝跳转、未知参数和任意主机，单图最多 8 MiB，单段最多 12 张。图片读取失败会保留文字和明确的失败说明。媒体上传失败仍由已有适配器记录错误。

验证：`scripts/test_knowledge_dingtalk_media.py` 三项测试通过；`scripts/check-knowledge-dingtalk-media.py` 真实检索转换得到 11 个原生图片组件，保留来源，没有发送平台消息。实际钉钉收件展示仍需用户发问验收。

部署：在 H:\工作助手 执行：

```powershell
& "$env:USERPROFILE\.conda\envs\design-rag\python.exe" scripts/install-knowledge-dingtalk-media.py
docker restart langbot
```

扩展属于本地适配，不是官方插件升级。重启容器保留，重建或升级镜像后需要重新执行安装脚本；脚本核对入口结构，结构不符会停止。

回退：把 `data/manuals/runtime/dingtalk-adapter.before-media.py` 用 `docker cp` 恢复到 `langbot:/app/src/langbot/pkg/platform/adapters/dingtalk/adapter.py`，再重启 langbot。备份与私有运行配置位于同一忽略目录，不提交整个 runtime。
