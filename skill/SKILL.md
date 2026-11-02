---
name: fpga-project-development
description: Use for any turn of work on an FPGA / embedded-systems project — PYNQ、Zynq、Vivado、Vitis HLS、Verilog、板卡与传感器接线、竞赛作品文档与答辩材料、技术选型、调试排查。Applies to questions, research, documentation, code, and debugging alike.
---

# FPGA 项目开发（总入口）

**当前项目：2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道 · AMD 赛道 · 自主选题 · 初级组 · 板卡 PYNQ-Z2（XC7Z020）。**

本项目**只用这一个 skill**。它是 **9 个外部 skill 的整合体**（8 份副本：01/02/03/08/09/10/11/12；`13` 只借排版）+ **7 份自有**（06/14/15/16/17/18/19）—— 工程层的 5 个（08–12）是 2026-09-20 追加的，`13-word-doc-writing` 是 2026-09-21 追加的，`14-coding-pitfalls` 是 2026-09-27 追加的，`15-measurement-and-comparison` / `16-vivado-and-pl-build` / `17-prompt-workflows` / `18-case-templates` / `19-pynq-runtime` 是 2026-11-01 追加的（`19` 当天稍晚补齐 PYNQ 运行时那一层）。

> 📖 **给人看的导航见 [README.md](README.md)** —— 每一项的适用范围 / 使用方法 / 已验证效果 / 失效条件 / 来源，都摊在那张表里。
> 要给评审或陌生队伍看时，先给这一份。

⚠️ **`writing-skills` / `using-superpowers` / `agent-skill-creator` 已于 2026-11-01 退出整合**（实测 0 次阅读，原 skill 仍可直接调）—— 要写 skill 或改 SKILL.md，**直接调原 skill，不要在本包找中转**。详见下文「路由」一节末尾。

**`06` / `13` / `14` / `15` / `16` / `17` / `18` / `19` 是「自有」条目**（本项目原创、无上游 ⇒ **跳过外部同步**，规程见 06）：`06` 是本项目自己定的同步规程；`13` 的规范参数提炼自 math-modeling 的 `paper-formal-writer`，但正文是本项目自己写的；`14` 的素材**全部来自本项目 v1~v7 的实战失败记录**。

## ⚠️ 不要再单独调用这些（除非下表写明「回原地」）

整合之后它们在**磁盘上依然存在**，但本项目一律改读这里的 `references/`：

| 原 skill | 本项目改读 | 形态 |
|---|---|---|
| **流程层** | | |
| `chinese-transparent-workflow` | [01-chinese-transparent-workflow](references/01-chinese-transparent-workflow.md) | 副本 |
| `ask-first` | [02-ask-first](references/02-ask-first.md) | 副本 |
| `using-superpowers` | ⛔ **本项目不读** —— 本项目只有一个 skill，路由层没有对象可路由 | — |
| **检索层** | | |
| `anysearch` | [03-anysearch](references/03-anysearch.md) | 副本 |
| **造物层** | | |
| `agent-skill-creator` | ⛔ **本项目不读** —— 要造 skill 时直接 `Skill(agent-skill-creator)` | — |
| `writing-skills` | ⛔ **本项目不读** —— 要改 SKILL.md 时直接 `Skill(writing-skills)`（全局 `CLAUDE.md` 本来就这么写） | — |
| **工程层**（2026-09-20 追加） | | |
| `brainstorming` | [08-brainstorming](references/08-brainstorming.md) | 副本 |
| `writing-plans` | [09-writing-plans](references/09-writing-plans.md) | 副本 |
| `test-driven-development` | [10-test-driven-development](references/10-test-driven-development.md) | 副本 |
| `systematic-debugging` | [11-systematic-debugging](references/11-systematic-debugging.md) | 副本 |
| `verification-before-completion` | [12-verification-before-completion](references/12-verification-before-completion.md) | 副本 |
| **交付层**（2026-09-21 追加） | | |
| `math-modeling` 的 `paper-formal-writer`（**只借排版**） | [13-word-doc-writing](references/13-word-doc-writing.md) | **自有** |

**工程层这 5 个，你的全局 `CLAUDE.md` 里已经点了名。** 那张「动手前：先确认该用哪个 skill」表里的 4 行
—— `brainstorming` / `systematic-debugging` / `writing-plans` / `verification-before-completion` ——
现在**全部落在本文件里**，全局规则和本项目规则不再打架。

**⚠️ 故意没整合的（别去调，也别以为漏了）：**

| skill | 为什么不在 |
|---|---|
| `using-git-worktrees`、`finishing-a-development-branch` | 本项目**不是 git 仓库**，这两个整篇讲 worktree / merge / PR |
| `subagent-driven-development`、`executing-plans`、`dispatching-parallel-agents` | **执行类，2026-09-20 决定暂缓** —— 等真进入写代码阶段再评估 |
| `documentation-writer` | 需先改造（Diátaxis 是为**软件**文档设计的），等材料成规模时再评估 |
| `stm32f4-programming-essentials-skill` | STM32F4 MCU —— 本项目是 PYNQ-Z2（Zynq） |
| `math-modeling` | **数学建模竞赛 CUMCM** —— 另一个竞赛。⚠️ 但 2026-09-21 起**从中借了一部分**：它的 `paper-formal-writer` 里那套 **Word 排版规范**已提炼进 [13-word-doc-writing](references/13-word-doc-writing.md)。**借的是排版，不是数模论文骨架** —— 那套章节结构（问题重述/模型假设/18000 字）对本项目不适用，**不要读 `math-modeling/SKILL.md`，直接读 13**。 |

**改了 `references/` 里的整合版，原版必须同步改** —— 规程见 [06-sync-protocol](references/06-sync-protocol.md)。

## 每轮对话必做：在回复结尾汇报本轮用了哪些 skill

每轮回复的**最后**附上：

> ---
> 🧩 **本轮使用的 skills**
>
> | skill | 用到的功能 |
> |---|---|
> | `fpga-project-development` | 总入口；读 references/02 |
> | `anysearch`（经 references/03） | 查了 XXX，跑了 `search --max_results 5` |

规则：

- **一轮里什么都没读到也要写**，写成 `仅 fpga-project-development（未读 references）`。
- "功能"要写**具体动作**（读了哪个文件、跑了哪条命令、查了什么），不许只写"用了 ask-first"。
- description 只写触发条件、不写流程 —— 所以这条规则只在本正文里，别去 description 里找。

## 路由：什么时候读哪个

下表按**工作流顺序**排 —— 从上往下就是一件事从想法到收尾要走的路。

| 你在做什么 | 读 |
|---|---|
| 任何**多步任务**（几乎是所有任务） | [01](references/01-chinese-transparent-workflow.md) |
| 要问用户问题、或拿不准该不该先动手 | [02](references/02-ask-first.md) |
| **需求模糊**（"帮我做个 X"）—— 先把想法变成定下来的设计 | [08](references/08-brainstorming.md) |
| 设计定了 —— 拆成一份能照着做的**任务清单** | [09](references/09-writing-plans.md) |
| 要**写代码 / 写 RTL**（Python 侧严格 TDD；PL 侧先读该文件横幅） | [10](references/10-test-driven-development.md) |
| **正在写码** —— 编码 / 行尾 / 期望值 / 复验独立性 / 落盘闸门 / **日志与单文件报告** / 图像与算法细节 | [14](references/14-coding-pitfalls.md) |
| **要计时 / 比帧率 / 做 A/B / 量成本** —— 尤其要说「快了 N%」之前 | [15](references/15-measurement-and-comparison.md) |
| 要**建 / 复制 Vivado 工程**、用 **vivado-mcp**、写 **Tcl/BD**、跑**综合布线出 bit**、写 **HLS**、**交付到 PYNQ** | [16](references/16-vivado-and-pl-build.md) |
| 要**问大模型做某类技术任务** —— 软硬件划分 / 看综合报告定瓶颈 / 让它把判据做红 / 报数前定口径 / 改开关前验证会不会跑到 | [17](references/17-prompt-workflows.md) |
| 要**从零搭工程、或抄现成骨架** —— 目录树 / `.tcl` 构建驱动 / 单文件报告 Python / HLS 核骨架 / 报告格式 / 可复现性校验 | [18](references/18-case-templates.md) |
| 要**把 bit 拿到板上跑起来** —— `Overlay()` 加载与校验、读写 HLS 寄存器、DMA 搬数据（封装现成，见下文 `dma_xfer.py`）、**板上一堆「没有报错但结果不对」** | [19](references/19-pynq-runtime.md) |
| **出错 / 报错 / 行为不符合预期** —— 动手改之前 | [11](references/11-systematic-debugging.md) |
| 要**说「做完了 / 通过了 / 修好了」之前** | [12](references/12-verification-before-completion.md) |
| 要**产出一份 Word 文档**（.docx）—— 或要给已有的 docx 统一排版 | [13](references/13-word-doc-writing.md) |
| 要**联网**查资料、核实事实 | [03](references/03-anysearch.md) |
| 要**写或改一份 SKILL.md**（含改本项目自己这个）、或从零造 skill 包 | **不读本包** —— 直接 `Skill(writing-skills)` / `Skill(agent-skill-creator)` |
| 改动了 `references/` 里的任何文件 | [06](references/06-sync-protocol.md) |

**2026-11-01 裁掉三份路由条目**（`04-using-superpowers` / `05-agent-skill-creator` / `07-writing-skills`）：
13,547 条 assistant 消息里这三份 **0 次被读过**，而它们对应的原 skill
（`using-superpowers` / `agent-skill-creator` / `writing-skills`）**仍在本机可直接调** ——
副本只多一层中转，不带来能力。

- **文件留在盘上不删**：`02` 和 `10` 里还有指向它们的指针，而 `02` / `10` 是**副本**，
  删了就得连上游原版一起改（规程正是 06）—— 为省 0 个 token 去动两份副本，不划算。
- **`06` 不在此列，必须留**：11 份 `references/` 的第一行都指着它，删它 = 11 处断链。

### 🔧 写码前先跑 `scripts/preflight.py`

```bash
python scripts/preflight.py <文件或目录>    # 检查
python scripts/preflight.py --selftest      # 先证明它能判红
```

专抓「会静默炸」的机械项：`.py` 里 `print` 到 GBK 控制台的非 GBK 字符、`.bat` 非 ASCII 或用了 LF、
Windows 路径字面量含中文（`cv2.imread` 返回 `None` 不报错）。

**误报比漏报更致命** —— 一个天天喊的检查器会被无视。所以它的 `--selftest` 里专门塞了
「docstring 里的 `⇒⚠✓`」和「枚举值 `auto/legacy` 的斜杠」两个陷阱样例，**必须一条都不报**。
（2026-11-01 首版只凭「含 `/` 就算路径」判，实测误报 448 条；同时它第一趟就查出
`make-copy.py` / `sync-check.sh` 自己的成功提示打印的是 `✅`，在 GBK 控制台下必崩 —— 已修。）

### 🔧 另外三个校验脚本（都在 `scripts/`，都有 `--selftest`）

| 脚本 | 什么时候跑 | 判什么 |
|---|---|---|
| `python scripts/check-timing.py <报告或目录>` | 综合 / 实现报告出来后、出 bit 之前 | WNS ≥ 阈值、WHS ≥ 阈值、五类资源 Util% ≤ 阈值；**解析不了就判红，不当通过** |
| `python scripts/check-timing.py --collect --dcp <design.dcp>` | 还没有报告、只有一个 `.dcp` / `.xpr` 时 | 自己驱动 Vivado 跑 `report_timing_summary` + `report_utilization`，**再交给上面同一套判据**。⛔ 采集**不是**判据：Vivado 退出码 0 只说明它跑完了，报告缺了 / 空的 / 负 WNS 照样判红（自检里 5 条臂专测这个）。默认带 `set_param general.maxThreads 1` —— 本机默认线程下 `report_timing_summary` 必崩 `0xC0000374`，见 [16](references/16-vivado-and-pl-build.md) V9 |
| `python scripts/check-repro.py a.bit b.bit [--allow=LO-HI]` | 交付前、换机器重建后 | 逐字节比对；**必须先声明「哪几个字节允许不同」**，没声明就判红 |
| `python scripts/check-golden.py --ref <参考> --out <产出>` | 每次改动跑完、说「没改坏」之前 | 逐文件比（图 / 文本 / 字节）；三态；**参考里有、产出里没有 ⇒ 一律红** |

⛔ 三个都**必须先跑 `--selftest`**：它证明「负 WNS 会判红」「改了 1 字节会判红」
「**同一对图只改 `--pct-tol` 就能翻判定**」—— 没有这一步，绿的唯一可能原因是检查器空转。
（`check-golden.py` 第一版真踩过：10 条自检全绿，而 `--pct-tol` 是个**永远不会生效**的死开关。）

### 🔧 上板前：从 `.hwh` 生成主机侧骨架

```bash
python scripts/gen-host-skeleton.py <system.hwh> [--name 名字] [--out 目录]
python scripts/gen-host-skeleton.py --selftest      # 11 条臂，其中 4 条真的 exec 生成物
```

读 `.hwh` 里的 `MEMRANGE` / `ADDRESSBLOCK` / `REGISTER`，生成一份**能直接 `import` 的主机侧模块**：
基地址表、寄存器偏移表、write-only 名单、64 位配对的未命名寄存器对，
以及一个 `r()` 读 write-only 就抛、`w()` 写只读就抛的 `Ip` 类。

**为什么它值钱**：本项目的三条运行时铁律（地址寄存器 write-only、64 位要拆两次 32 位、
基地址别照抄 `0x43C00000`）在 `.hwh` 里都是**机器可判的**（`ACCESS="write-only"`），
人肉抄一遍就必然出错 —— 让它抄，并且抄错了当场判红。

⛔ 它**不是**「生成完就当对」：`--selftest` 里有 4 条臂**真的 `exec` 生成的代码**。
第一版就是靠这几条臂抓出真 bug —— 生成的 `BASE` / `REG` 字典**漏了冒号**，
文件根本跑不起来，而只判字符串长相的前几条臂当时全绿。

### 🔧 上板搬数据：`scripts/dma_xfer.py`

```python
from dma_xfer import DmaXfer
x = DmaXfer(dma)                 # dma = overlay 里的 axi_dma，用它的 .mmio 读状态
x.transfer(src, dst)             # src/dst 都是 pynq.allocate 出来的 buffer

from dma_xfer import transfer_np
out = transfer_np(dma, frame)    # 裸 numpy 进、裸 numpy 出，内部自己 alloc/free
```

```bash
python scripts/dma_xfer.py --selftest    # 12 条臂，全程不需要板子、不需要 pynq
```

它把三件**不会报错但会出错**的事固化下来：

1. **顺序**：`sync_to_device()` → `sendchannel.transfer()` → `recvchannel.transfer()` →
   等 MM2S → 等 S2MM → **两端都完成后**才 `sync_from_device()`。少写前面那个 sync、
   或把后面那个 sync 提到 `wait` 之前，**程序都不报错**，只是结果是错的。
2. **超时**：pynq 的 `wait()` **没有超时参数**，DMA 一卡住脚本就永久挂死。
   这里改成轮询单调时钟截止，超时抛 `DmaError`。
3. **出错定位**：`DmaError` 的消息里带 `S2MM_SR` 的十六进制原值和逐位判读，
   直接说清是「错误位（`DMAIntErr` 等）/ Halted / 还在跑（是超时不是失败）」哪一类，
   而不是甩一句「超时」。

⚠️ **这份封装本身没有单独上板跑过**（自检用假对象，验的是调用顺序、超时与错误路径，
不是硬件行为）。第一次上板请先跑一遍再把它当结论。

## 📁 本项目的目录约定（2026-09-20 定）

站内所有路径都以 **`<project-root>/`** 为根。

| 用途 | 路径 |
|---|---|
| **定稿材料**（已存在，别动编号） | `information\基于 FPGA 的实时视频平面自适应校正系统\01-…07-*` |
| **Word 文档的 Markdown 源** —— [13](references/13-word-doc-writing.md) 产出 | 与 `.docx` 同目录，`<文档名>_source.md` |
| **设计稿** —— [08](references/08-brainstorming.md) 产出 | 同目录 `_设计稿\YYYY-MM-DD-<主题>.md` |
| **计划稿** —— [09](references/09-writing-plans.md) 产出 | 同目录 `_计划\YYYY-MM-DD-<主题>.md` |
| **存档快照** —— **代替 `git commit`** | `project\_存档\YYYY-MM-DD-NN-<简述>\` + `INDEX.md` |
| **工具脚本** —— [13](references/13-word-doc-writing.md) 的渲染器 | `tools\render_docx.py`（`python tools/render_docx.py <源.md> [出.docx]`） |

- **`_` 前缀 = 过程材料**，故意和 `01`–`06` 那批**定稿材料**分开 —— 不然以后分不清哪些是交付物、哪些是草稿。
- **⛔ 本项目不用 git。** [09](references/09-writing-plans.md) 正文里每个任务收尾的 `git add` + `git commit`，
  一律换成「**存档快照**」。**完整规程（存什么 / 绝不存什么 / `INDEX.md` 怎么填）见 09 的横幅。**
- **存档存两类**：① **手写源文件**（`.v` `.sv` `.xdc` `.cpp` `.h` `.tcl` `.py` `.ipynb` + `.xpr`）；
  ② **当版成品图**（本项目即 `out_test1..5_rectified.jpg`）—— 2026-09-26 用户加的规则，
  原话「成品图也存吧，我随时好找来看」。**成品图是给人翻的，不是给构建系统用的。**
- **⛔ 绝不存**：Vivado 的 `.runs/` `.cache/` `.hw/` `.sim/` `.ip_user_files/`（构建产物，**几百 MB～几 GB**）；
  以及 `_eval/_norm_out/` 那类**中间实验图**（随时可重跑）—— **别因为都是 `.jpg` 就和成品图一起处理**。

## 五条红线（读没读 references 都有效）

1. **面向用户的汇报一律中文。** 进度必须可见：任务开始给编号清单，完成一步**立即**更新，不许攒着一起报。
2. **联网搜索只走 anysearch CLI**，禁用内置 WebSearch / WebFetch。CLI 路径见 03。
3. **动手前先查 skill**：调度层（04）优先于实现层；不确定就直接调，让系统报错来判断可用性。
4. **写代码 / 配置 / 硬件之前，95% 门槛始终有效**（02）。宁可多问一轮，不许猜着写。
5. **每写一个会跑出结果的脚本（自检 / 测试 / 诊断 / 批处理），就必须让它自产一个单文件报告**，
   头部带时间/机器/sha16，**每笔 write 都 flush**，内容与屏幕**逐字相同、谁都不截断**；
   要交回来的东西一律做成**一键下载**（`Content-Disposition: attachment`），
   失败路径也必须进日志全文 —— **⛔ 禁止 `str(x).split("\n")[0][:80]` 这类截断**。
   细则见 [14](references/14-coding-pitfalls.md) 的 **H 组**。
   （用户 2026-09-27 原话：「就不需要我手动给你粘贴好多东西了，只用下载一个文件就行（**以后写代码都要**）」）
