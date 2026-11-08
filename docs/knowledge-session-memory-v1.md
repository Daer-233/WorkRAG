# 工作知识助手会话记忆 V1

PostgreSQL 模式的使用与部署见 [会话记忆说明](knowledge-session-memory-postgres.md)。本文记录进程内模式。

功能作用于 LSD AI 助手单聊。先问一份培训或入职资料，再追问“还有现场的图吗”“发我原文件”或“那下一步呢”。上一轮引用多份资料时，回复卡片所列序号，或回复资料名及版本。

Host 保留上一轮实际引用的资料标识、版本和待选项，沿用现有的最近两轮分类上下文。工作区、机器人、员工、单聊和会话分别隔离，30 分钟无活动后失效，重置会话或重启 LangBot 后清空。检索先通过 LangBot 原有授权，随后由 Host 锁定资料编号和版本。下架或版本变化时需明确指定新资料。无法确认有序步骤时，助手会询问当前进度。钉钉内的文件回复用于确认源文件状态，附件发送仍待接通。

培训正文与相册的已核实关联存放在本机 `data/manuals/session-memory-photo-links.json`。查询图片时由后端重新签发引用，返回上限为 12 张，关联的现场照片优先。可以用 `link-training-photos` 重新核对并登记两份已发布条目。

## 开关和部署

在工作助手目录使用现有 `design-rag` Python 环境。`disable` 即时关闭对后续消息的接管。V3 意图分流使用自己的配置，继续为 `shadow`。

```powershell
python scripts/install-knowledge-session-memory.py disable
```

重新安装时使用 `install`，重启 `langbot` 后将 `scripts/verify-knowledge-session-memory.py` 复制到容器 `/tmp/verify-work-session-memory.py`，再执行 `enable`。该命令先运行容器验收，通过后才开功能。`rollback` 会关闭开关并恢复安装前的 Host 源码，重启 `langbot` 后生效。

## 已验证

- 55 项本地检查通过，涵盖来源引用、会话过期和重置、并发覆盖、步骤边界、下架资料、卡片与 V3 回归。
- 真实 LangBot 容器内，两个检索代理均先执行原授权，再把查询限制到选定资料。用本机知识库验证了相册 11 张照片、选中第二份报销资料后的文件状态，以及错误版本和不同会话的隔离。
- 已启用单聊。验收使用合成事件，钉钉客户端的最终显示可用上述两句培训问答复核。
