# 钉钉连接自动恢复 · 2026-11-03

适用于 LSD AI助手与钉钉的连接持续报错、消息没有进入工作知识助手的故障。守护进程使用正式管理接口，不主动发消息、不重试用户问题、不修改凭据、卡片模板或消息路由。

## 已启用的规则

- 每 30 秒检查机器人专属日志；新进程启动后先观察 60 秒。
- 最近 180 秒至少 6 条连续建连/连接异常，跨度至少 45 秒，且最新异常仍在 60 秒内，才考虑恢复。
- 若有新的消息接收事件、适配器重启标记、人工停用或配置变化，跳过本轮恢复。
- 恢复前检查该机器人的执行记录；正在回答、状态未知、检查接口不可用，或有超出检查上限的记录时，保守跳过。
- 通过 `PUT /api/v1/platform/bots/{uuid}` 重新应用 `enable=true`，重新挂载现有配置。
- 在请求发出前保存尝试记录；即使响应中断，也不会立即重复重挂。冷却 10 分钟，每小时最多 3 次。
- 重挂成功仅表示运行时已重建；不能据此认定钉钉在线。继续观察错误及实际接收事件，后续提问确认完整收发。

这能减少本次这类连接失败造成的长时间无响应，不能保证外部网络、钉钉平台或凭据异常永不发生。不会自动修复知识内容、模型回答或尚未导入的卡片模板。

## 启停与状态

现有 `scripts/start-langbot-codex.ps1` 会一并启动守护检查，已经运行的 Codex 守护进程也会补启动检查；`scripts/stop-langbot-codex.ps1` 会一并停止。它们不会注册 Windows 登录任务；重启电脑后仍按原方式启动服务。

可独立执行：

```powershell
powershell -ExecutionPolicy Bypass -File H:\工作助手\scripts\start-knowledge-watchdog.ps1
powershell -ExecutionPolicy Bypass -File H:\工作助手\scripts\stop-knowledge-watchdog.ps1
Get-Content -LiteralPath H:\工作助手\data\manuals\runtime\connection-watchdog\status.json
```

脚本检查 PID 对应的程序与命令，进程内还持有文件锁，防止重复启动。日志和状态在 `data/manuals/runtime/connection-watchdog`；只保存检查结果、次数和时间，不保存机器人密钥或消息正文。

| status | 含义 |
| --- | --- |
| startup_grace | 启动观察期 |
| no_sustained_failure | 没有检测到持续建连失败，不等于已经核验实时在线 |
| disabled | 用户已停用，保持停用 |
| execution_busy_or_unknown / execution_check_unavailable | 无法确认安全空闲，暂不重挂 |
| remounted_waiting_for_connection | 已重新挂载，继续等待连接和接收确认 |
| remount_unconfirmed_* | 重挂结果不明确，已记入冷却时间 |
| cooldown / recovery_limit | 达到冷却或频率上限 |
| check_unavailable | 管理接口暂不可用，30 秒后继续只读检查 |

## 验证和交接

`scripts/test_knowledge_connection_watchdog.py` 的 8 项测试通过，覆盖新鲜连续故障、成功消息重置、正常连接不操作、人工停用、启动观察、冷却、频率上限、活动/未知执行、历史记录分页、配置变化、请求结果未知时不立即重复重挂。当前机器人只读检查未发现持续错误；故障恢复的真实管理接口已在本次前置排查中恢复用户单聊，用户确认收到“正在处理”及回复。自动触发使用模拟故障验证。

代码入口：`scripts/knowledge_connection_watchdog.py`。默认单次只读检查；后台自动恢复需显式参数 `--serve --recover`，启动脚本已带此参数。正常查看运行状态时直接读 `status.json`，避免与后台进程的文件锁冲突。

保护性限制：活动执行检查按页读取，最多扫描 5000 条该机器人记录，不保留正文；无法完成扫描时不能确认空闲，自动恢复会跳过并记录状态。高频使用场景后续宜接入正式支持 API Key 的活动执行快照，而不是放宽权限或忽略执行保护。
