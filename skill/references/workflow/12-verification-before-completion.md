<!--
来源：C:\Users\ROG\.claude\skills\verification-before-completion\SKILL.md
上游指纹（sha256 前 16 位）：875fac3c1a2e0090
同步日期：2026-09-20
本文件是 fpga-project-development 的整合副本。改这里必须同步改上游 —— 见 06-sync-protocol.md
-->

# 验收前验证 (Verification Before Completion)

> ⚠️ **本文件管「说『做完了』之前必须先拿到什么」。它是 [11-systematic-debugging](11-systematic-debugging.md) 的下游 —— 调试靠它收尾。**
>
> 这是本整合里**唯一一个纯单文件**条目（原版就只有 SKILL.md）。
>
> ## 本项目怎么用
>
> - 正文第 24-28 行的 **「No git? 用等效证据代替」一节本项目正好适用**（本项目不是 git 仓库）。
>   它给的三个替代物：**重读磁盘上的文件 / 重跑命令并贴输出 / 和改动前的副本 diff**。
> - **FPGA 项目里「证据」长什么样**（这条是我加的，正文没有）：
>
> | 要声称的事 | 必须贴出来的证据 |
> |---|---|
> | 「综合通过了」 | `synth_design completed` + WNS/WHS 数值 —— 不是「没报错」 |
> | 「时序收敛了」 | `report_timing_summary` 里 **WNS ≥ 0 且 TNS = 0** |
> | 「上板跑通了」 | 串口日志原文 / ILA 抓到的波形 / 实际输出 |
> | 「图像校正效果对」 | **同一次实验的输入图和输出图** + 客观指标 —— 不是「看着挺好」 |
> | 「文档改好了」 | 重读改后的文件，贴出改动的那几行 |
>
> ⚠️ 最后一条正是本项目**已经踩过的坑**：`sync-check.sh` 报 `✅ 一致`，但副本里抄错了 1 行 ——
> **脚本的输出是真证据，但它证明的不是你以为的那件事。** 详见 [06-sync-protocol](06-sync-protocol.md)。

---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

**No git? Substitute equivalent evidence — the bar is fresh evidence, not git.**
Where a pattern below says "check the VCS diff", any of these satisfies it:
re-read the changed file from disk, re-run the command and show its output, or
diff against a copy saved before the change. What stays forbidden is unchanged:
trusting a report, or any claim with no artifact behind it.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |

## Key Patterns

**Tests:**
```
✅ [Run test command] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I've written a regression test" (without red-green verification)
```

**Build:**
```
✅ [Run build] [See: exit 0] "Build passes"
❌ "Linter passed" (linter doesn't check compilation)
```

**Requirements:**
```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, phase complete"
```

**Agent delegation:**
```
✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
❌ Trust agent report
```

## Why This Matters

From 24 failure memories:
- your human partner said "I don't believe you" - trust broken
- Undefined functions shipped - would crash
- Missing requirements shipped - incomplete features
- Time wasted on false completion → redirect → rework
- Violates: "Honesty is a core value. If you lie, you'll be replaced."

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is non-negotiable.
