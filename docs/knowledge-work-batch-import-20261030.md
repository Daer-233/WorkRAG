# 工作知识助手：五份资料批量导入记录

日期：2026-10-30。分类统一为人力行政中心。五份资料均已发布并完成索引。

| 资料 | 版本标记 | 父块 | 子块 | 图片 |
|---|---|---:|---:|---:|
| 费用报销规范（交通与住宿标准） | 未标注 | 1 | 3 | 2 |
| IT篇教程 | 未标注 | 10 | 14 | 0 |
| Office安装教学（原文） | 未标注 | 1 | 5 | 0 |
| 打印机地址 | 未标注 | 1 | 1 | 0 |
| LSD入职指引（IT） | 2025（文件名标注） | 4 | 19 | 12 |

合计 17 个父块、42 个子块、14 张来源图片。

## 来源与完整性

只导入用户指定的五个文件。原文、地址、菜单和表格完整保存；原文件字节已归档并校验 SHA256。文件中的安装命令、共享目录和链接未执行或访问。
IT 指引的 2025 标记仅来自原文件名，不认定为生效日期；其他资料版本留空。各份来源独立，不自动裁决版本差异。
TXT 不编造页码；MinerU 文字页码只取唯一原文匹配。一般流程不按页脚切断，菜单不误当步骤，IP 不误当编号。现有单页码接口不伪造跨页范围。
HTML 表格完整保留 rowspan/colspan。报销规范附2张完全匹配的表格裁图；IT指引保存11张显式截图及1张匹配的打印机表格裁图。作为章节配图，未调用视觉 API 生成图注。

## 条目与归档

- 费用报销规范（交通与住宿标准）：`c5948b90-ef27-45f6-8205-30c54dbd905a`。原始文件：`H:\MinerU\费用报销规范.jpg-f1e143a6-3abf-4329-b3ef-018bf011b6e8\MinerU_markdown_202610301703827_0dd5f8e6.md`。归档：`data/manuals/originals/mineru-imports/df20c752eb86a0e8a03a2f72c5f388cbd3a1be5b37e22271e7eedf03bad8249c`。
- IT篇教程：`74836038-60bd-4172-b41c-9cb033f0a6e5`。原始文件：`H:\杂物\IT篇教程.txt`。归档：`data/manuals/originals/mineru-imports/78b136dc8c05e64b4abe5792d5ef06016bafed48cc244187aafbd355c65ed819`。
- Office安装教学（原文）：`f90e1ea8-dd54-45c5-8d50-6fc3518751b2`。原始文件：`H:\杂物\office安装教学.txt`。归档：`data/manuals/originals/mineru-imports/0c72bbd7441c1ac09b12418d9c3e07dd6d2dbbe8c95f043789d92b56ea13fbe6`。
- 打印机地址：`211a9918-52be-4f55-b434-064c74ed48a0`。原始文件：`H:\杂物\打印机地址.txt`。归档：`data/manuals/originals/mineru-imports/eb70424e238e38487be7f81a44f56b19c3ea7d16b40cd6576253bff8fe02e381`。
- LSD入职指引（IT）：`79efd656-201c-45df-be1d-c28cd0b241ae`。原始文件：`H:\MinerU\LSD入职指引（IT）_2025(1)(2)(2).pdf-3dfa95f1-73e0-426a-9216-b3c5d8219252\MinerU_markdown_202610301710209_c0d627e7.md`。归档：`data/manuals/originals/mineru-imports/0e38021b365f19e2edc7003a103b8ff3f3bf080b5423cd4644e551013f24a991`。

## 验收与复用

21项相关单元和兼容测试通过。verification.json 中六项实际 LangBot 默认检索全部通过，使用标题和问题，没有条目过滤。14张缩略图均可读取。公开验收记录不包含密码、网络地址或安装命令原文。未发送钉钉测试消息，不把检索通过当成每份资料的 Codex 回答验收。

准备：python scripts/import-work-knowledge-batch.py。保存草稿加 --import-draft，核对后发布加 --publish-reviewed。已发布资料复用清单，不原地覆盖；源文件改变引发同名冲突时应按新版处理。
复验：python scripts/verify-work-knowledge-batch.py。
本轮补充 TXT 归档与通用本地导入，未重新调用 MinerU，未更换模型或卡片模板。
