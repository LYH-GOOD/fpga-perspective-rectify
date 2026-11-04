# report —— 设计报告

## 设计报告正文

[`design_report.pdf`](design_report.pdf) —— **30 页**，提交用定稿。

| 项 | 值 |
|---|---|
| 大小 | 11,093,194 B |
| sha256 | `26f63d5c6735c687bfa419083b64f8045c30110fd0089357c77b45b97fa754aa` |

> **2026-11-03 修订**：p27 三个数字更新为实测值 —— 115→114 个文件、26.5→26.2 MB、
> 10→9 条用例图（`ai_selftest/1108.png` 未登记为用例，只跑 9 条）。
> 只改这三处字符，其余逐页文本比对无差异（`build/reports/report_number_patch.txt`）。
> 原件保留在 `_backup/design_report_20261103_before_p27_numbers.pdf`（sha256 `e00e628b…`）。
>
> **2026-11-04 修订**：两份 PDF 的文档属性里带有个人署名（author 字段），已清空。
> 正文逐页文本比对完全一致（30 页全同），只动了属性块；因此 sha256 随之变化。
>
> **2026-11-04 补录**：`report/` 此前**缺少指南 §3.3.3.1 明令要求的大模型协作记录**
> —— PDF 第四部分只有概述，没有提示词原文与模型回答原文。现补入 `llm-collaboration.md`
> 与提取脚本 `../build/extract_llm_log.py`。`design_report.pdf` 一个字节未动。
>
> **2026-11-04 换版**：`design_report.pdf` 换成本日 15:56 导出的那一版 —— 正文
> **25,972 字符**（上一版 20,353），多了 5,619 字符，**4.4 节已换成 ROSS 重写稿**
> （553 条路径 / 389 行报告 / 15.16 秒 / `0x00011003` / 盲重建 +0.248、+0.643 ns 均在文中）。
> 导出件的文档属性 `author` 带笔名，已清空，30 页正文逐页与导出件比对完全一致。
> 备份链：`_backup/design_report_20261104_before_v33b.pdf`（sha256 `fb524ae1…`）、
> `_backup/design_report_20261104_before_v33c.pdf`（sha256 `b5bf2eb1…`）。
>
> **2026-11-04 第三次换版**：换成队友改过目录的 `(5)(2)` 导出 —— 正文与上一版**逐页文本完全相同**，
> 只有 `6.2 设计总结` 一条目录页码由 30 改为 29，其余 27 条一字未动。按此版交付。

结构（按指南 3.3.5.3 组织）：

| 部分 | 内容 |
|---|---|
| 摘要 + 第一部分 作品概述 | 1.1 功能与特性、1.2 应用领域、1.3 主要技术特点、1.4 主要性能指标、1.5 主要创新点、1.6 设计流程 |
| 第二部分 系统设计 | 2.2 硬件系统（PL 校正核与行缓存架构、图像增强与输出链路）、2.3 软件系统（组织与数据流、传统自动定位、AI 融合机制、跟踪与恢复、平面透视校正、增强参数与帧率管理） |
| 第三部分 工程成果 | 3.2 逐项特性成果、3.3 训练数据与模型验证、3.4 实时运行与验证边界、3.5 PL 校正核的设计迭代（11.99 → 4.686 拍/像素，2.56×） |
| 第四部分 大模型协作 | 4.1 智能体工作流、4.2 提示词与自我纠错、4.3 技能包的提炼过程与边界、4.4 AMD ROSS 套件使用心得 |
| 第五部分 复现说明 | 路径 A 直接上板（约 15 min）、路径 B 从源码重建 |
| 第六部分 | 6.1 可扩展之处、6.2 设计总结 |

## 大模型协作记录（指南 §3.3.3.1 要求项）

[`llm-collaboration.md`](llm-collaboration.md) —— 19.7 KB。四个部分正好对上指南点名的四项：
**提示词**（四类写法，带真实原文）、**自我纠错轨迹**（8 例，每例有可核查的证据链）、
**智能体工作流设计**（技能包路由 / 长期记忆 / 子 agent / MCP）、**这份记录怎么核**。

- 数据来源是**本机会话记录（JSONL）的机器提取**，不是估算；截止 **2026-11-01 12:32**，
  此后的会话未计入 ⇒ 文中的交互量是可核查的**下界**。
- 提取脚本 [`../build/extract_llm_log.py`](../build/extract_llm_log.py) 随包提供，可在自己的会话目录上重跑。
- 原始 JSONL 含本机用户名与工作目录，**不随包提交**。
- `design_report.pdf` 第四部分是这件事的成稿（约 5 页，4.4 已换成重写稿），本文件是**明细与原文**；
  两者结论一致，细节以本文件为准。

## AMD ROSS 套件的完整记录（4.4 节的展开）

`design_report.pdf` 的 4.4 节是提交用定稿。下面两份是它的完整记录与重写稿：

| 文件 | 是什么 |
|---|---|
| [`ross_experience.md`](ross_experience.md) | 从接入到盲重建的完整记录：每轮的原始报错、判据、改动点与结论，含没写进正文的失败过程 |
| [`ross_section_4.4.md`](ross_section_4.4.md)<br>[`ross_section_4.4.docx`](ross_section_4.4.docx) | 4.4 节的重写稿，docx 可直接替换进报告。**若替换，须重新导出 PDF** |

读这三个文件前先知道三个口径，否则容易误读：

- 结论只针对 **Vivado 2026.1 + ROSS 官方 Go 版**这一组合；换版本后行为会变。
- 盲重建的时序数字（+0.248 / +0.643 ns）与时序裕量来自 2026.1 环境，
  与 `design_report.pdf` 里 2025.2 交付位流的数字**不可直接比较**；两者能比的只有"换版本也能重建出等价设计"这一点。
- 重写稿引用的数字（553 条路径、389 行报告、15.16 秒、`0x00011003`）在 `ross_experience.md` 里都有出处；
  两者不一致时以记录为准。

## 迭代与发布记录

`releases/` 是开发过程的一版一页发布记录，共 **31 个文件**：29 份版本说明 + 2 份指路文件。
它与上面的报告正文互补：正文讲"为什么这么设计"，`releases/` 讲"每一版改了什么、当时是怎么判定的"。

### 主线版本（按版本号）

| 版本 | 文件 | 主题 |
|---|---|---|
| 10 | `hotfix_release_report.md` | 计时修复、切换进度条、新目标先自动 |
| 10 | `startfix_release_report.md` | 启动目录修正版 startfix1 |
| 11 | `smooth_release_report.md` | 平滑（首行注明第 12 版以 `live` 为准） |
| 12 | `live_release_report.md` | 实时显示（首行注明第 13 版见 `overlay`） |
| 13 | `overlay_release_report.md` | 独立四角框与恢复冷却 3 秒 / 5 秒 |
| 14 | `paired_release_report.md` | 同帧成对显示与实时原图恢复 |
| 15 | `pic56_release_report.md` | 人工审核全量数据模型 |
| 16 | `continuity16_release_report.md` | 短时实时延续与显式 AI 入口锁 |
| 17 | `manual17_release_report.md` | 进度条收尾与手动参考跟踪 |
| 18 | `display18_release_report.md` | 预览与连续显示 |
| 21 | `reuse21_release_report.md` | V18 基线，相机全路径复用与 2 秒恢复冷却 |
| 22 | `profile22_release_report.md` | 480P / 600P 切档进度条 |
| 23 | `sharp23_release_report.md` | PL 锐化与左侧图像设置 |
| 24 | `sharp24_release_report.md` | 交接 bit 的 remap1.5 兼容修复 |
| 25 | `sharp25_release_report.md` | 锐化即时预览 |
| 26 | `target26_release_report.md` | AI 后可点选切书、实时重选 |
| 27 | `light27_release_report.md` | 可实时调节的低 BRAM 光补 |
| — | `ui28_release_report.md` | UI28：恢复与实时显示迭代 |
| 29 | `pic78_release_report.md` | PIC78 模型（2026-11-01） |
| 30 | `fps30_release_report.md` | 0.5 秒 FPS 统计、2 小时运行 |
| 31 | `fps31_release_report.md` | 1 秒 FPS 统计 |
| 32 | `fps32_release_report.md` | 2 秒 FPS 统计 |
| 33 | `fps33_release_report.md` | 3 秒 FPS 统计（**当前交付版**） |

版本号不连续（缺 19、20），因为那几版没有独立发布说明。

### 历史版说明（首行直接指向当前版）

这 6 份不是某版的独立记录，而是保留下来方便回溯的旧说明，读它们的第一行就知道该看哪份：

| 文件 | 首行指向 |
|---|---|
| `recovery_release_report.md` | 第 11 版当前行为见 `smooth` |
| `unified_release_report.md` | unified8 历史说明，当前 recovery9 见 `recovery` |
| `hybrid_release_report.md` | hybrid6 历史说明，当前 unified8 见 `unified` |
| `physical_release_report.md` | 历史记录，hybrid6 见 `hybrid` |
| `trackfix_release_report.md` | 历史记录，hybrid6 见 `hybrid` |
| `installfix1_report.md` | 历史版，Current13 行为见 `overlay` |

### 两份指路文件

| 文件 | 内容 |
|---|---|
| `readme_ai_live.md` | 一行：先看 `fps33_release_report.md` |
| `modification-notes.md` | 一行：同 `fps33_release_report.md`（原为同一份文件的重复拷贝） |

### 每份发布说明怎么写

格式基本固定为六段：**基于哪版 → 改了什么 → 哪些没动 → 验了什么 → 没验什么 → 怎么上板**。

第 5 段"没验什么"是刻意的：它写清这一版**没有**做过板端实测的部分
（例如第 33 版明确写着"没有进行板端 3 秒 FPS 实测或 2 小时实机长跑"）。
**读的时候不要把这一段的推断和报告正文里的实测结论混为一谈。**

## 约定

- 报告中出现的每一个数据，都必须能追溯到 `build/` 或 `board/` 下的原始记录。
- 不写未实测的数据。
- 复现说明必须细到「在哪台机器上、敲哪条命令、看到什么算成功」。

## 相关

- 技能包见 [`../skill/`](../skill/)
- 项目总览见 [`../README.md`](../README.md)
- 包内五项要求对照见 [`../PACKAGE_MANIFEST.md`](../PACKAGE_MANIFEST.md)
