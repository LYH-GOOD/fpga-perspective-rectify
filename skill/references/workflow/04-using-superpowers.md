<!--
来源：C:\Users\ROG\.claude\skills\using-superpowers\SKILL.md
上游指纹（sha256 前 16 位）：fcb9f64d960b854a
同步日期：2026-09-20
本文件是 fpga-project-development 的整合副本。改这里必须同步改上游 —— 见 06-sync-protocol.md
压缩说明：删去了 Platform Adaptation 一节（Codex / Pi / Antigravity 三套适配，本项目跑在 Claude Code）。
-->

# 技能调度 (Using Superpowers)

> ⚠️ **本文件中反复出现的"skill"，在本项目里指的是 `fpga-project-development` 及其 `references/`。**
> 本项目不再单独调用那 5 个外部 skill —— 见总入口的路由表。

<SUBAGENT-STOP>
如果你是被派去执行某个具体任务的子 agent，忽略本文件。
</SUBAGENT-STOP>

## 铁律

**只要觉得某个 skill 有哪怕 1% 的可能适用于你正在做的事，就绝对必须调用它。**

**如果某个 skill 适用于你的任务，你没有选择。必须用。**

这不是可以商量的。你不能靠自我说服绕过去。

## 规则

**在做出任何回复或动作之前调用相关的 skill** —— 包括追问澄清、翻代码库、看文件之前。如果调用后发现不合适，你不用照着做。

**进入 plan mode 之前：** 如果还没 brainstorm 过，先调 `brainstorming`。

然后宣布"正在用 [skill] 来做 [目的]"，并严格照做。如果它有清单，为每一项建一个 todo。

## 优先级

多个 skill 同时适用时，**流程层优先** —— 它们定方法，实现层再执行。

- "我们来做 X" → 先 `brainstorming`，再实现层 skill
- "修个 bug" → 先 `systematic-debugging`，再领域 skill
- "写或改一个 skill / SKILL.md" → 先 `writing-skills`

### ⭐ 冲突按【层】裁决，不按【音量】

有若干个 skill 都声称自己无条件优先。它们**抢的不是同一个决定** —— 每个管一层。两张表看起来打架时，套这张表：

| 层 | skill | 管什么 |
|----|-------|--------|
| **调度层** | `using-superpowers`（本文件） | **该用哪个** skill |
| **流程层** | `brainstorming`、`systematic-debugging`、`writing-plans` | 工作的**节奏与范围** |
| **纪律层** | `ask-first`（[02](02-ask-first.md)） | **够不够** 95% 才动手 |
| **实现层** | 各领域 skill | 具体怎么做 |

- **节奏压过纪律。** `brainstorming` 生效时，它"一次一问"压过 `ask-first` 的"每次 2-4 问"。但 `ask-first` 的 95% 门槛依然供着。
- **凡是要【写】的，95% 门槛压过节奏** —— 写代码、写配置、动硬件。流程 skill 的节奏**从不**授权你凭猜测动手。
- **"先查 skill 再追问"**（见红线表）的意思是：先决定**该用哪个** skill。它**不禁止提问** —— 澄清提问通常就是流程 skill 自己的第一步。
- **`brainstorming` 的 HARD-GATE 只挡实现层 skill**，不挡流程层 —— 它按设计就该路由到 `writing-plans`，不算违规。

## 红色警报

出现这些念头 = 停，你正在自我说服：

| 念头 | 现实 |
|------|------|
| "这只是个简单问题" | 问题也是任务。查 skill。 |
| "我得先要点上下文" | 查 skill 在追问之前。 |
| "我先翻翻代码库" | skill 会告诉你**怎么**翻。先查。 |
| "我快速看一眼 git/文件就行" | 文件没有对话上下文。查 skill。 |
| "我先收集点信息" | skill 会告诉你**怎么**收集。 |
| "这不需要正经 skill" | 只要有 skill 存在，就用。 |
| "我记得这个 skill" | skill 会演进。读当前版本。 |
| "这不算个任务" | 动作 = 任务。查 skill。 |
| "用 skill 太重了" | 简单的事会变复杂。用。 |
| "我先把这一件事做了" | 做任何事前先查。 |
| "这感觉挺有产出" | 无纪律的行动浪费时间。skill 就是防这个的。 |
| "我知道那是什么意思" | 懂概念 ≠ 用 skill。去调它。 |
| "这只是个小改动 / 文档微调" | **大小不是判据。** 有 skill 覆盖就用。 |
| "description 说了我不用这个" | **description 只说什么时候【加载】。只有正文说什么时候可以跳过 —— 而正文不豁免任何尺寸。** |

## 用户指令

用户指令（CLAUDE.md、AGENTS.md、直接要求）优先于 skill，skill 又优先于默认行为。只有在用户明确让你跳过时，才跳过 skill 的流程。
