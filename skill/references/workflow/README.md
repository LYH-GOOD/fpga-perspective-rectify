# references/workflow/ —— 与大模型协作的方法论（14 篇）

> 2026-11-01 随 `fpga-skill-package-2026-11-01` 并入。
> **这一层不是 PYNQ 专属**，讲的是"怎么和一个有工具执行能力的大模型一起把工程做出来"。
> 与 FPGA 强相关的部分在 [`../generic/`](../generic/)，与具体题目绑定的在 [`../../project/`](../../project/SKILL.md)。

---

## 一、什么时候看哪一篇

| 场景 | 看这篇 |
|---|---|
| 项目要用中文汇报、评审是中文语境 | [`01-chinese-transparent-workflow.md`](01-chinese-transparent-workflow.md) |
| 不确定要不要先问清楚再动手 | [`02-ask-first.md`](02-ask-first.md) |
| 需要查资料 / 找官方文档 | [`03-anysearch.md`](03-anysearch.md) |
| 文档要改结构、想先发散 | [`08-brainstorming.md`](08-brainstorming.md) |
| 动手前要把方案写成一页计划 | [`09-writing-plans.md`](09-writing-plans.md) |
| 要保证改坏了能立刻发现 | [`10-test-driven-development.md`](10-test-driven-development.md) |
| **出了问题、现象很奇怪** | [`11-systematic-debugging.md`](11-systematic-debugging.md) |
| **准备说"做完了"之前** | [`12-verification-before-completion.md`](12-verification-before-completion.md) |
| 要写 Word 报告 | [`13-word-doc-writing.md`](13-word-doc-writing.md) |
| 整合了外部 skill，怕两边脱节 | [`06-sync-protocol.md`](06-sync-protocol.md) |
| 想了解"为什么整合、怎么路由" | [`04-using-superpowers.md`](04-using-superpowers.md) |
| 要**从零建一整个** skill 包（评估 / 打包 / 多平台 / registry） | [`05-agent-skill-creator.md`](05-agent-skill-creator.md)（路由，回原地用） |
| 要写/改一个 skill | [`07-writing-skills.md`](07-writing-skills.md) |
| 多版本迭代，要把基线 / 约束 / 检查结果写成持久文件 | [`14-file-planning-and-evidence.md`](14-file-planning-and-evidence.md) |

**与本仓库其它层的配合**：
`generic/10-prompt-workflow.md` 讲四类提示词模板与三个找 bug 的模式，
[`../team/17-prompt-workflows.md`](../team/17-prompt-workflows.md) 给按任务类型分的专项模板。
三份合起来是一套完整的方法。

---

## 二、每一项的四元组

| 文件 | 适用范围 | 使用方法 | 已验证的效果 | 失效条件 |
|---|---|---|---|---|
| `01-chinese-transparent-workflow` | 中文语境的技术沟通 | 写报告 / 汇报前读 | 本项目全程使用 | 纯英文项目 |
| `02-ask-first` | 任何"需求含糊"的开始 | 开工前读 | 减少返工 | 需求已明确定稿时多余 |
| `03-anysearch` | 需要外部资料时 | 检索时按流程走 | 本项目查 Vivado/PYNQ 文档 | 无网络环境 |
| `04-using-superpowers` | 想理解 skill 路由 | 参考 | — | 只用单一 skill 的项目 |
| `05-agent-skill-creator` | 要从零造一整个 skill 包 | 回原地用（路由，非副本） | — | 只写/改单个 SKILL.md 时看 `07` |
| `06-sync-protocol` | 整合了外部 skill 的包 | 改副本前读 | 防止副本与上游脱节 | 不整合外部 skill |
| `07-writing-skills` | 要写 / 改 skill | 写 SKILL.md 前读 | — | 不写 skill |
| `08-brainstorming` | 方案还没定时 | 发散阶段 | — | 方案已定 |
| `09-writing-plans` | 要动手前 | 写一页计划 | — | 一行改动的小任务 |
| `10-test-driven-development` | 有可自动判定的输出 | 改代码前先写判据 | 判据先行的做法在 `generic/05` 有 FPGA 版 | 无自动判据的场景 |
| `11-systematic-debugging` | 现象异常 / 反复修不好 | 排障时按流程 | 与 `pitfalls/` 配合使用 | — |
| `12-verification-before-completion` | 准备交付前 | 宣称"完成"前过一遍 | 本项目每次交付都过 | — |
| `13-word-doc-writing` | 写 Word 格式报告 | 排版时对照 | 本报告用它 | 非 Word 交付 |
| `14-file-planning-and-evidence` | 多轮迭代的工程 | 每版把基线 / 约束 / 检查结果写入持久文件 | 本项目每版都有 NOTES 与证据文件 | 一次性任务 |

---

## 三、已知的断链（如实说明）

这几篇原是外部 skill 的副本，原文里引用了**未随包附带的子文件**，链接会失效：

| 文档 | 失效引用 | 说明 |
|---|---|---|
| `07-writing-skills.md` | `testing-skills-with-subagents.md` | 上游 skill 的子文件，原交接包未附带 |
| `10-test-driven-development.md` | `testing-anti-patterns.md` | 同上 |
| `06-sync-protocol.md` | `scripts/make-copy.py`、`scripts/sync-check.sh` | 本队自有的维护脚本，**未随包分发**（见下） |

**不影响正文**：前两处引用出现在"延伸阅读"的位置，本目录内的正文是完整的。

**关于那两个维护脚本**：它们是本队本机 skill 安装的配套工具 ——
`make-copy.py`（324 行）把上游目录写死成 `~/.claude/skills`，`COPIES` 表里 5 条样例的
`note` / `banner` 还夹着本项目的具体路径；
`sync-check.sh`（102 行）按每个副本头部记的 `来源：` 逐一去读上游文件重算 sha256。
**换一台机器就没有上游可比**，脚本只会全线报 `[FAIL] 上游缺失`，所以**不带进包**。

`06-sync-protocol.md` 仍然值得读：它讲的是"同一份知识存在两份时，漂移怎么当场堵住"的
**方法**（真值表、三种条目类型、生成器 + 独立复核的双保险）。要移植到自己项目，
把 `COPIES` 表换成自己的清单、把副本头部的 `来源：` 改到自己的上游即可 ——
两个脚本合计 426 行，结构一目了然。

---

## 四、来源

外部通用 skill 的整合副本，2026-11-01 随 `fpga-skill-package-2026-11-01` 交接包并入。
每篇文件头部记着上游路径与上游 `SKILL.md` 的 sha256 前缀（同步规程见 `06-sync-protocol.md`）。

## 本版增补

新增[14-file-planning-and-evidence.md](14-file-planning-and-evidence.md)，用于多轮基线与交付证据管理。当前共14篇工作流正文；原有07/10中未附带的上游延伸材料仅作外部参考，不作为本包运行依赖。UI专项入口见[UI技能](../../ui-ux-pro-max/SKILL.md)。
