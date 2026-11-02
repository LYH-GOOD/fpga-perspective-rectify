<!--
来源：~/.claude/skills/writing-plans/SKILL.md
上游指纹（sha256 前 16 位）：272e1af349f5062c
同步日期：2026-09-20
本文件是 fpga-project-development 的整合副本。改这里必须同步改上游 —— 见 06-sync-protocol.md
补充说明：正文逐字照搬，未压缩。原版是 2 个文件 / 8.8 KB。
        正文里未引用 `plan-document-reviewer-prompt.md`，故不列入横幅。
-->

# 写计划 (Writing Plans)

> ⚠️ **本文件管的是「把定下来的设计拆成一份能照着做的任务清单」。它不管「怎么执行这份计划」—— 执行类 skill 本项目暂缓整合。**
>
> **正文里出现的 2 处外部引用，本项目目前都指不到东西：**
>
> | 正文里写的 | 本机情况 |
> |---|---|
> | `superpowers:using-git-worktrees` | **未整合** —— 本项目不是 git 仓库，worktree 无从谈起 |
> | `superpowers:subagent-driven-development`<br>`superpowers:executing-plans` | **未整合** —— 2026-09-20 决定：执行类 skill 暂缓，等真进入写代码阶段再评估 |
>
> **本项目怎么用这一条：**
>
> **⚠️ 本项目最大的改动：不用 git —— 每个任务的收尾换成「存档快照」。**
>
> **正文里每个任务的最后一步都是 `git add` + `git commit`。本项目一律换成下面这套。**
> （2026-09-20 用户拍板：**「不按照 git 来」**。）
>
> | 项 | 规定 |
> |---|---|
> | **存到哪** | `<project-root>/project/_存档/` |
> | **一次存档** | 新建目录 `YYYY-MM-DD-NN-<简述>\`，**NN = 这份计划里的任务编号** |
> | **存什么** | ① **手写源文件**：`.v` `.sv` `.xdc` `.cpp` `.h` `.tcl` `.py` `.ipynb` + `.xpr`<br>② **成品图** —— 当版最终产出的结果图（本项目即 `out_test1..5_rectified.jpg`）。**2026-09-26 用户加**，原话「成品图也存吧，我随时好找来看」 |
> | **⛔ 绝不存** | ① `.runs/` `.cache/` `.hw/` `.sim/` `.ip_user_files/` `.gen/` —— Vivado 构建产物，几百 MB～几 GB<br>② **中间实验图** —— 探针跑的中间产物（本项目在 `_eval/_norm_out/`），随时可重跑<br>⚠️ **「成品图」≠「中间图」** —— 别因为都是 `.jpg` 就一起存、或一起不存 |
> | **怎么存** | **复制**进去，原文件留在原地继续用（不是移动） |
> | **记一笔** | 往 `project\_存档\INDEX.md` **追加一行**：日期 ｜ 步骤 ｜ 改了什么 ｜ **验证到哪一步** ｜ 目录名 |
>
> **⚠️ 两条 FPGA 特有的坑：**
>
> 1. **存档目录必须在 Vivado 工程目录之外。** 上面定的 `project\_存档\` 与工程目录（如 `project\try\`）是**平级**的，
>    别建在工程里面 —— 否则 Add Sources 递归扫目录时会把存档里的**旧版 `.v` 一起扫进来** → 同一模块名出现两份 → 综合直接报错。
>    ⚠️ 这条是推理，**未实测**（本项目还没有正式工程）。
> 2. **`INDEX.md` 的「验证到哪一步」不能空着。** 没有 git 的 tag / branch，这一栏就是**唯一**能回答
>    「上周那个能跑的版本长什么样」的东西。填法照 [12-verification-before-completion](12-verification-before-completion.md) 的证据表 ——
>    写「仿真通过」不算，要写「`xsim` 跑完 testbench，无 error」。
>
> **为什么用存档而不是 git**：本项目不是纯代码工程，是「材料 + 代码 + 硬件」混在一起的竞赛作品，
> 而且 Vivado 的构建产物体积极大，git 会把仓库撑爆。存档只留真正有用的那部分
> —— **手写源 + 当版成品图**（成品图是给人翻的，不是给构建系统用的）。
>
> - 正文第 18 行说计划存 `docs/superpowers/plans/` —— **本项目存**
>   `<project-root>/information/基于 FPGA 的实时视频平面自适应校正系统\_计划\`，
>   文件名 `YYYY-MM-DD-<主题>.md`。设计稿同理，存同级的 `_设计稿\`（见 [08-brainstorming](08-brainstorming.md)）。
>   `_` 前缀是为了和 `01`–`06` 那批**定稿材料**分开 —— 过程材料不混进交付物。
> - 正文第 61 行和「Execution Handoff」那一节的 subagent 执行方式**本项目暂不可用**，到执行阶段再回来补。
> - 正文里的 `pytest` 只是示例 —— Python 侧照用；**PL 侧（Verilog/HLS）的「测试」是 testbench 仿真**，
>   粒度比「2-5 分钟一步」粗得多，别硬套（详见 [10-test-driven-development](10-test-driven-development.md)）。

---

# Writing Plans

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about our toolset or problem domain. Assume they don't know good test design very well.

**Announce at start:** "I'm using the writing-plans skill to create the implementation plan."

**Context:** If working in an isolated worktree, it should have been created via the `superpowers:using-git-worktrees` skill at execution time.

**Save plans to:** `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`
- (User preferences for plan location override this default)

## Scope Check

If the spec covers multiple independent subsystems, it should have been broken into sub-project specs during brainstorming. If it wasn't, suggest breaking this into separate plans — one per subsystem. Each plan should produce working, testable software on its own.

## File Structure

Before defining tasks, map out which files will be created or modified and what each one is responsible for. This is where decomposition decisions get locked in.

- Design units with clear boundaries and well-defined interfaces. Each file should have one clear responsibility.
- You reason best about code you can hold in context at once, and your edits are more reliable when files are focused. Prefer smaller, focused files over large ones that do too much.
- Files that change together should live together. Split by responsibility, not by technical layer.
- In existing codebases, follow established patterns. If the codebase uses large files, don't unilaterally restructure - but if a file you're modifying has grown unwieldy, including a split in the plan is reasonable.

This structure informs the task decomposition. Each task should produce self-contained changes that make sense independently.

## Task Right-Sizing

A task is the smallest unit that carries its own test cycle and is worth a
fresh reviewer's gate. When drawing task boundaries: fold setup,
configuration, scaffolding, and documentation steps into the task whose
deliverable needs them; split only where a reviewer could meaningfully
reject one task while approving its neighbor. Each task ends with an
independently testable deliverable.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

## Global Constraints

[The spec's project-wide requirements — version floors, dependency limits,
naming and copy rules, platform requirements — one line each, with exact
values copied verbatim from the spec. Every task's requirements implicitly
include this section.]

---
```

## Task Structure

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Interfaces:**
- Consumes: [what this task uses from earlier tasks — exact signatures]
- Produces: [what later tasks rely on — exact function names, parameter
  and return types. A task's implementer sees only their own task; this
  block is how they learn the names and types neighboring tasks use.]

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## No Placeholders

Every step must contain the actual content an engineer needs. These are **plan failures** — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — the engineer may be reading tasks out of order)
- Steps that describe what to do without showing how (code blocks required for code steps)
- References to types, functions, or methods not defined in any task

## Remember
- Exact file paths always
- Complete code in every step — if a step changes code, show the code
- Exact commands with expected output
- DRY, YAGNI, TDD, frequent commits

## Self-Review

After writing the complete plan, look at the spec with fresh eyes and check the plan against it. This is a checklist you run yourself — not a subagent dispatch.

**1. Spec coverage:** Skim each section/requirement in the spec. Can you point to a task that implements it? List any gaps.

**2. Placeholder scan:** Search your plan for red flags — any of the patterns from the "No Placeholders" section above. Fix them.

**3. Type consistency:** Do the types, method signatures, and property names you used in later tasks match what you defined in earlier tasks? A function called `clearLayers()` in Task 3 but `clearFullLayers()` in Task 7 is a bug.

If you find issues, fix them inline. No need to re-review — just fix and move on. If you find a spec requirement with no task, add the task.

## Execution Handoff

After saving the plan, offer execution choice:

**"Plan complete and saved to `docs/superpowers/plans/<filename>.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?"**

**If Subagent-Driven chosen:**
- **REQUIRED SUB-SKILL:** Use superpowers:subagent-driven-development
- Fresh subagent per task + two-stage review

**If Inline Execution chosen:**
- **REQUIRED SUB-SKILL:** Use superpowers:executing-plans
- Batch execution with checkpoints for review
