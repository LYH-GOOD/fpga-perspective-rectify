#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make-copy.py — 把外部 skill 的 SKILL.md 正文，机械复制成 fpga-project-development 的整合副本。

【为什么要有这个脚本】
  2026-09-20 建 07-writing-skills.md 时，手工抄 684 行正文，抄错 1 行
  （graphviz 流程图的一条边，"Decision where I might go wrong?" 抄成了 "Need to show information?"）。
  而 scripts/sync-check.sh 只比对【上游】的 sha256、从来没见过副本 —— 所以它报了 [OK] 一致。
  **手抄 = 引入错误。** 这个脚本用程序切片，副本正文按构造就与上游逐字节相同。

【用法】
  1. 在下面的 COPIES 表里加一条（上游目录名 / 目标文件名 / 中文标题 / 头部补充说明 / 横幅正文）
  2. python make-copy.py           # 生成
     python make-copy.py --check   # 只校验已存在的副本，不写文件

【[!] 覆盖写的保护】
  本脚本是**覆盖写**。若目标文件已存在、且它当前的中文标题或横幅与 COPIES 表里写的不一致，
  脚本会**拒绝覆盖**并指名是哪个文件 —— 意思是「你改过横幅，但没同步回 COPIES 表」。
  直接把改动补进 COPIES 表再跑；确认要冲掉加 --force。
  没有这道保护，「改完横幅 → 后来刷新指纹时重跑一次」就会**静默丢掉横幅的改动**。

【它做什么】
  - 读上游 SKILL.md 的【原始字节】算 sha256 前 16 位（与 sync-check.sh 第 79 行完全一致）
  - 从第一行 `# ` 开始切出正文（跳过 YAML frontmatter）
  - 拼成：HTML 头部注释 + 中文标题 + 横幅 + `---` + 【正文逐字照搬】
  - 写完立刻回读，逐行 diff 验保真 —— 不通过就报错退出
"""

import hashlib
import sys
from pathlib import Path

SK = Path("~/.claude/skills")
SKILL_DIR = SK / "fpga-project-development"
REF_DIR = SKILL_DIR / "references"
SYNC_DATE = "2026-09-20"

# ─────────────────────────────────────────────────────────────────────────────
# 要生成的副本。加新条目就往这里加。
#   upstream : ~/.claude/skills/ 下的目录名
#   dest     : references/ 下的文件名
#   title    : 中文标题（本项目加的，放在原版英文标题之前）
#   note     : 头部 HTML 注释里的「补充说明：」那几行；None = 单文件，不写这行
#   banner   : 中文标题之后的横幅正文（markdown），写完横幅自动补 `---`
# ─────────────────────────────────────────────────────────────────────────────

COPIES = [
    {
        "upstream": "brainstorming",
        "dest": "08-brainstorming.md",
        "title": "# 头脑风暴 (Brainstorming)",
        "note": "正文逐字照搬，未压缩。原版是 5 个文件 / 60 KB，正文里引用的 1 个支撑文件\n"
                "        没有一起搬进来 —— 它仍留在原目录，位置见下方横幅。\n"
                "        脚本只比对 SKILL.md 的指纹，支撑文件不参与比对。",
        "banner": """> [!] **本文件管的是「把模糊想法变成一份定下来的设计」。它不管「怎么写实现计划」—— 那是 [09](09-writing-plans.md)。**
>
> **正文里出现的 `skills/brainstorming/visual-companion.md` 在本目录下不存在**，它在原目录：
> `C:\\Users\\ROG\\.claude\\skills\\brainstorming\\visual-companion.md`（13 KB）
> 同目录的 `scripts/`（35 KB）是那套浏览器伴侣的服务器代码。
>
> **本项目怎么用这一条：**
>
> - **可视化伴侣（浏览器）本项目基本用不上** —— FPGA 项目的问题是「时序约束怎么写」「AXI 带宽够不够」，
>   不是「这个按钮放左边还是右边」。正文第 30 行「提供可视化伴侣」这一步，本项目可以跳过。
> - 正文第 37 行结束时说 `invoke writing-plans skill` —— 本机指的是 **[09-writing-plans](09-writing-plans.md)**。
> - 正文第 34 行说设计稿存 `docs/superpowers/specs/` —— **本项目存**
>   `D:\\study\\competition\\qian\\information\\基于 FPGA 的实时视频平面自适应校正系统\\_设计稿\\`，
>   文件名 `YYYY-MM-DD-<主题>.md`。计划稿存同级的 `_计划\\`（见 [09-writing-plans](09-writing-plans.md)）。
>   `_` 前缀是为了和 `01`–`06` 那批**定稿材料**分开 —— 过程材料不混进交付物。
> - 正文第 116-119 行的 **「No git repo?」一节本项目正好适用**（本项目不是 git 仓库）。"""
    },
    {
        "upstream": "writing-plans",
        "dest": "09-writing-plans.md",
        "title": "# 写计划 (Writing Plans)",
        "note": "正文逐字照搬，未压缩。原版是 2 个文件 / 8.8 KB。\n"
                "        正文里未引用 `plan-document-reviewer-prompt.md`，故不列入横幅。",
        "banner": """> [!] **本文件管的是「把定下来的设计拆成一份能照着做的任务清单」。它不管「怎么执行这份计划」—— 执行类 skill 本项目暂缓整合。**
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
> **[!] 本项目最大的改动：不用 git —— 每个任务的收尾换成「存档快照」。**
>
> **正文里每个任务的最后一步都是 `git add` + `git commit`。本项目一律换成下面这套。**
> （2026-09-20 用户拍板：**「不按照 git 来」**。）
>
> | 项 | 规定 |
> |---|---|
> | **存到哪** | `D:\\study\\competition\\qian\\project\\_存档\\` |
> | **一次存档** | 新建目录 `YYYY-MM-DD-NN-<简述>\\`，**NN = 这份计划里的任务编号** |
> | **存什么** | ① **手写源文件**：`.v` `.sv` `.xdc` `.cpp` `.h` `.tcl` `.py` `.ipynb` + `.xpr`<br>② **成品图** —— 当版最终产出的结果图（本项目即 `out_test1..5_rectified.jpg`）。**2026-09-26 用户加**，原话「成品图也存吧，我随时好找来看」 |
> | **[STOP] 绝不存** | ① `.runs/` `.cache/` `.hw/` `.sim/` `.ip_user_files/` `.gen/` —— Vivado 构建产物，几百 MB～几 GB<br>② **中间实验图** —— 探针跑的中间产物（本项目在 `_eval/_norm_out/`），随时可重跑<br>[!] **「成品图」≠「中间图」** —— 别因为都是 `.jpg` 就一起存、或一起不存 |
> | **怎么存** | **复制**进去，原文件留在原地继续用（不是移动） |
> | **记一笔** | 往 `project\\_存档\\INDEX.md` **追加一行**：日期 ｜ 步骤 ｜ 改了什么 ｜ **验证到哪一步** ｜ 目录名 |
>
> **[!] 两条 FPGA 特有的坑：**
>
> 1. **存档目录必须在 Vivado 工程目录之外。** 上面定的 `project\\_存档\\` 与工程目录（如 `project\\try\\`）是**平级**的，
>    别建在工程里面 —— 否则 Add Sources 递归扫目录时会把存档里的**旧版 `.v` 一起扫进来** → 同一模块名出现两份 → 综合直接报错。
>    [!] 这条是推理，**未实测**（本项目还没有正式工程）。
> 2. **`INDEX.md` 的「验证到哪一步」不能空着。** 没有 git 的 tag / branch，这一栏就是**唯一**能回答
>    「上周那个能跑的版本长什么样」的东西。填法照 [12-verification-before-completion](12-verification-before-completion.md) 的证据表 ——
>    写「仿真通过」不算，要写「`xsim` 跑完 testbench，无 error」。
>
> **为什么用存档而不是 git**：本项目不是纯代码工程，是「材料 + 代码 + 硬件」混在一起的竞赛作品，
> 而且 Vivado 的构建产物体积极大，git 会把仓库撑爆。存档只留真正有用的那部分
> —— **手写源 + 当版成品图**（成品图是给人翻的，不是给构建系统用的）。
>
> - 正文第 18 行说计划存 `docs/superpowers/plans/` —— **本项目存**
>   `D:\\study\\competition\\qian\\information\\基于 FPGA 的实时视频平面自适应校正系统\\_计划\\`，
>   文件名 `YYYY-MM-DD-<主题>.md`。设计稿同理，存同级的 `_设计稿\\`（见 [08-brainstorming](08-brainstorming.md)）。
>   `_` 前缀是为了和 `01`–`06` 那批**定稿材料**分开 —— 过程材料不混进交付物。
> - 正文第 61 行和「Execution Handoff」那一节的 subagent 执行方式**本项目暂不可用**，到执行阶段再回来补。
> - 正文里的 `pytest` 只是示例 —— Python 侧照用；**PL 侧（Verilog/HLS）的「测试」是 testbench 仿真**，
>   粒度比「2-5 分钟一步」粗得多，别硬套（详见 [10-test-driven-development](10-test-driven-development.md)）。"""
    },
    {
        "upstream": "test-driven-development",
        "dest": "10-test-driven-development.md",
        "title": "# 测试驱动开发 (TDD)",
        "note": "正文逐字照搬，未压缩。原版是 2 个文件 / 18 KB，正文里引用的 1 个支撑文件\n"
                "        没有一起搬进来 —— 它仍留在原目录，位置见下方横幅。\n"
                "        脚本只比对 SKILL.md 的指纹，支撑文件不参与比对。",
        "banner": """> [!] **本文件是 [07-writing-skills](07-writing-skills.md) 明确要求的前置依赖。** 07 开头写着
> 「REQUIRED BACKGROUND: You MUST understand superpowers:test-driven-development before using this skill」——
> 2026-09-20 之前那句指向一个本项目没有的东西，现已补上。
>
> **正文里出现的 `testing-anti-patterns.md` 在本目录下不存在**，它在原目录：
> `C:\\Users\\ROG\\.claude\\skills\\test-driven-development\\testing-anti-patterns.md`（8.3 KB）
>
> ## [!] 本项目必须先分层，否则 TDD 会变成教条
>
> | 层 | 怎么做 |
> |---|---|
> | **Python 侧**（PYNQ / 算法验证 / 图像处理脚本） | **严格 TDD**，就是下面写的红-绿-重构。用 `pytest`，**不要用正文示例里的 `npm`** |
> | **PL 侧**（Verilog / HLS） | **testbench 仿真就是「测试」**，但节奏完全不同：一次综合/仿真几分钟到几十分钟，套不上正文「每步 2-5 分钟」的粒度。改成**按模块走**：先写 testbench（红）→ 写 RTL（绿）→ 上板验证 |
> | **硬件 / 板卡接线** | 谈不上 TDD，用 [12-verification-before-completion](12-verification-before-completion.md) 的证据标准兜底 |
>
> [!] **上面这个分层是推理出来的，未经实测** —— 本项目还没开始写代码。
> 第一次真跑 FPGA 的红-绿循环时，回来修正这一节。
>
> **其余不匹配**：正文示例是 TypeScript + `npm test`，本项目是 Python + `pytest` / Verilog + `xsim`；
> 正文第 120-125 行的 `git commit` —— **本项目不用 git，改成「存档快照」**（完整规程见 [09](09-writing-plans.md)）。
> **核心原则不受影响**：没看着测试失败过，就不知道它测的对不对。"""
    },
    {
        "upstream": "systematic-debugging",
        "dest": "11-systematic-debugging.md",
        "title": "# 系统化调试 (Systematic Debugging)",
        "note": "正文逐字照搬，未压缩。原版是 12 个文件 / 41 KB，正文里引用的 3 个支撑文件\n"
                "        没有一起搬进来 —— 它们仍留在原目录，位置见下方横幅。\n"
                "        脚本只比对 SKILL.md 的指纹，支撑文件不参与比对。",
        "banner": """> [!] **本文件管「出错之后怎么找根因」。它不管「怎么证明做完了」—— 那是 [12-verification-before-completion](12-verification-before-completion.md)。**
>
> **正文里出现的 3 个支撑文件名，在本目录下不存在。** 它们仍在原目录：
>
> | 正文里写的 | 实际位置 |
> |---|---|
> | `root-cause-tracing.md` | `C:\\Users\\ROG\\.claude\\skills\\systematic-debugging\\root-cause-tracing.md`（5.3 KB） |
> | `defense-in-depth.md` | `C:\\Users\\ROG\\.claude\\skills\\systematic-debugging\\defense-in-depth.md`（3.7 KB） |
> | `condition-based-waiting.md` | `C:\\Users\\ROG\\.claude\\skills\\systematic-debugging\\condition-based-waiting.md`（3.5 KB） |
>
> ## [!] 本项目怎么用 —— 第 72-108 行的「多组件系统取证据」直接映到 FPGA
>
> | 正文里的层级（CI → build → signing） | 本项目的对应层 |
> |---|---|
> | Layer 1 | **Python 侧**（PYNQ / Jupyter / 上位机脚本） |
> | Layer 2 | **AXI 总线 / 驱动 / 内存映射** |
> | Layer 3 | **PL 逻辑**（HLS IP / Verilog 模块） |
> | Layer 4 | **板卡 IO / 传感器 / 屏幕** |
>
> [!] **FPGA 上跳过这一步的代价特别高**：一次综合/实现 30 分钟起步，上板一次要插拔接线。
> 「先加探针看是哪一层坏了」在这里不是好习惯，是**必须**。
> Vivado 侧的现成手段：**ILA 抓波形、时序报告、`report_*` 系列、串口打日志**。
>
> **正文里的两处引用**：`superpowers:test-driven-development` → **[10-test-driven-development](10-test-driven-development.md)**；
> `superpowers:verification-before-completion` → **[12-verification-before-completion](12-verification-before-completion.md)**。"""
    },
    {
        "upstream": "verification-before-completion",
        "dest": "12-verification-before-completion.md",
        "title": "# 验收前验证 (Verification Before Completion)",
        "note": None,
        "banner": """> [!] **本文件管「说『做完了』之前必须先拿到什么」。它是 [11-systematic-debugging](11-systematic-debugging.md) 的下游 —— 调试靠它收尾。**
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
> [!] 最后一条正是本项目**已经踩过的坑**：`sync-check.sh` 报 `[OK] 一致`，但副本里抄错了 1 行 ——
> **脚本的输出是真证据，但它证明的不是你以为的那件事。** 详见 [06-sync-protocol](06-sync-protocol.md)。"""
    },
]


def build_header(up: Path, digest: str, note) -> str:
    lines = [
        "<!--",
        f"来源：C:\\Users\\ROG\\.claude\\skills\\{up.parent.name}\\SKILL.md",
        f"上游指纹（sha256 前 16 位）：{digest}",
        f"同步日期：{SYNC_DATE}",
        "本文件是 fpga-project-development 的整合副本。改这里必须同步改上游 —— 见 06-sync-protocol.md",
    ]
    if note:
        lines.append(f"补充说明：{note}")
    lines.append("-->")
    return "\n".join(lines)


def body_of(raw: str) -> str:
    """从第一行 `# ` 开始切（跳过 YAML frontmatter）。"""
    lines = raw.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("# "):
            return "\n".join(lines[i:])
    raise SystemExit("[FAIL] 找不到正文起始的 `# ` 标题行")


def banner_of(text: str, title: str):
    """取出文件中「中文标题 → 下一个 `---`」之间的横幅正文。取不到返回 None。"""
    i = text.find(title)
    if i < 0:
        return None
    j = text.find("\n---\n", i + len(title))
    if j < 0:
        return None
    return text[i + len(title):j].strip()


def main() -> int:
    check_only = "--check" in sys.argv
    force = "--force" in sys.argv
    failures = []

    for c in COPIES:
        up = SK / c["upstream"] / "SKILL.md"
        dest = REF_DIR / c["dest"]

        if not up.is_file():
            print(f"[FAIL] 上游缺失：{up}")
            failures.append(c["dest"])
            continue

        raw_bytes = up.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()[:16]
        body = body_of(raw_bytes.decode("utf-8"))

        assembled = "\n".join([
            build_header(up, digest, c["note"]),
            "",
            c["title"],
            "",
            c["banner"],
            "",
            "---",
            "",
            body,
        ])

        if check_only:
            if not dest.is_file():
                print(f"[FAIL] 副本不存在：{dest.name}")
                failures.append(c["dest"])
                continue
            existing = dest.read_text(encoding="utf-8")
            # 只比正文（从原版英文标题起）
            up_body = body
            got = existing[existing.index(up_body[:60]):] if up_body[:60] in existing else ""
            if got == up_body:
                print(f"[OK] 正文一致  {c['dest']}  （sha={digest}）")
            else:
                print(f"[FAIL] 正文不一致  {c['dest']}")
                failures.append(c["dest"])
            continue

        # [!] 覆盖写保护：磁盘上的横幅与 COPIES 表不一致 = 有人改了横幅没同步回脚本
        if dest.is_file() and not force:
            on_disk = banner_of(dest.read_text(encoding="utf-8"), c["title"])
            if on_disk != c["banner"].strip():
                print(f"[STOP] 拒绝覆盖 {c['dest']} —— 磁盘上的横幅与 COPIES 表不一致。")
                print("    多半是你改过横幅、但没同步回本脚本的 COPIES 表。")
                print("    先把改动补进 COPIES 表再跑；确认要冲掉就加 --force。")
                failures.append(c["dest"])
                continue

        dest.write_text(assembled, encoding="utf-8")

        # 写完立刻回读验证 —— 不通过就报错，不静默通过
        back = dest.read_text(encoding="utf-8")
        if body not in back:
            print(f"[FAIL] 写回后正文对不上：{c['dest']}")
            failures.append(c["dest"])
            continue
        print(f"[OK] 生成  {c['dest']:<24s} 正文 {len(body.splitlines()):>4d} 行  sha={digest}")

    if failures:
        print(f"\n[FAIL] 有 {len(failures)} 项失败：{', '.join(failures)}")
        return 1
    print("\n[OK] 全部完成。" + ("（--check 模式，未写文件）" if check_only else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
