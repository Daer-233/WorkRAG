# 项目目录与 Python 环境

## 当前使用哪个环境

**本机 WorkRAG 使用 venv，不使用 Conda。**

| 项目 | 当前值 |
|---|---|
| 项目根目录 | G:\项目\WorkRAG |
| 项目解释器 | G:\项目\WorkRAG\.venv\Scripts\python.exe |
| Python 版本 | 3.11.16 |
| 基础 Python | G:\docker\python\cpython-3.11-windows-x86_64-none |
| Pi | 独立 Node.js 服务，源码 apps/pi-harness，不使用 Python / Conda |
| LangBot 插件 | Docker 中的 Python 环境，由插件运行时管理 |

检查时发现本地 PyCharm 配置仍引用 F:\JAVA_Develop\anaconda3；这与项目实际启动环境不同。没有自动改写 IDE 的个人 SDK 注册信息。请在 PyCharm“设置 → 项目 → Python 解释器 → 添加本地解释器”中选择已有 Virtualenv，并选中上表的 .venv\Scripts\python.exe。工作目录设为项目根目录。

若创建 PyCharm 运行配置：脚本选择 deployment\local.py，参数填 start，解释器选择项目 .venv。停止用 stop，查看状态用 status。无需创建新的 Conda 环境。

终端无需激活环境也可运行：

```powershell
cd 'G:\项目\WorkRAG'
.\.venv\Scripts\python.exe deployment/local.py start
.\.venv\Scripts\python.exe deployment/local.py status
```

如需安装依赖，同样使用 `.\.venv\Scripts\python.exe -m pip ...`，避免装进 Anaconda。当前机器已有完整依赖，单纯整理目录不需要重新安装。

## 平时用哪些入口

| 文件 | 用途 |
|---|---|
| start-knowledge.bat | 双击启动 |
| stop-knowledge.bat | 双击关闭项目；--check 只查看 |
| restart-knowledge.bat | 重启服务 |
| start-local.ps1 / stop-local.ps1 / status-local.ps1 | PowerShell 日常入口 |
| deployment/local.py | 真正的 Python 服务管理入口 |
| resume-deployment.ps1 | 首次部署恢复与完整验收，会重启服务，不是日常启动按钮 |

## 整理后的目录

```text
WorkRAG/
├─ README.md                  总入口
├─ *.bat / *-local.ps1        日常启停入口
├─ apps/                      后端、前端、模型、Agent 与 Pi 源码
├─ plugins/                   LangBot 插件源码
├─ deployment/                当前部署和运行管理
│  ├─ checks/                 诊断、真实联调和验收脚本
│  └─ tests/                  模拟接口的离线测试
├─ docs/
│  ├─ README.md               文档导航
│  ├─ current/                当前使用说明与交接
│  ├─ guides/                 参考操作说明
│  └─ history/                按主题分类的历史记录
├─ scripts/                   共用辅助工具与旧部署工具
├─ instances/                 配置示例与本地忽略配置
├─ data/                      资料、私有配置、日志及验收结果
├─ output/                    历史实验产物
└─ .venv/                     当前 Python 环境
```

本次主要调整文档与验收工具的位置，并修正仓库内路径；源码服务目录、虚拟环境、原件、模型权重和容器数据位置未迁移。旧脚本和历史方案保留，不作删除。

旧脚本中的 H/I 盘、Anaconda、Milvus、BERT 和旧 Host 补丁记录不等于本机运行配置。当前系统以根 README、本目录交接说明和 deployment/local.py 为准。
