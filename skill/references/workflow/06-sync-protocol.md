<!--
类型：自有
本文件是 fpga-project-development 自有的规程 —— 既没有上游副本，也不是路由。
-->

# 外部 skill 同步规程

## 为什么有这一条

用户的原始要求：

> **「如果项目开发 skills 中有的 skills 要修改并且这个被修改的 skills 在外部单独存在，那么就同步修改。」**

整合之后，同一份知识存在**两份**：`references/` 里的**整合版**，和 `C:\Users\ROG\.claude\skills\` 下的**原版**。两份一旦漂移，以后就不知道该信哪个 —— 所以漂移必须**当场**堵住。

## 真值表

| 情况 | 要不要同步 |
|------|-----------|
| 改了 `references/XX.md` 里的**实质内容**（规则、步骤、阈值、判据） | ✅ **必须同步改原版** |
| 改了 `references/XX.md` 里**只对本项目有意义**的东西（项目名、路径、路由指向、删掉不适用的章节） | ❌ 不用改原版 |
| 原版在别处被改了（其他项目、其他会话） | ✅ **必须回头更新整合版**，并刷新指纹 |
| 只是修错别字 / 排版 | ⚠️ 两边都顺手改掉，别拖（成本 5 秒，拖着就成漂移） |
| 改动只发生在**路由型条目**（见下） | ❌ 无副本可同步 |
| 改了**混合型条目**顶部那条"支撑文件在哪"的横幅（见下） | ❌ 不用改原版（原版没这段），**但要顺手确认那几条路径还对** |
| 想改副本的**正文**（从上游抄来的英文原文） | ⛔ **一个字都不许动** —— 见下「横幅 vs 正文」 |
| 改了横幅之后要刷新指纹 | ⚠️ 先把横幅改动**同步回 `make-copy.py` 的 `COPIES` 表**，再跑生成器 —— 否则会被覆盖保护拦下 |

**判据一句话**：**这条知识换个项目还成立吗？成立 → 两边都改；只对本项目成立 → 只改整合版。**

## 路由型条目（例外）

`05-agent-skill-creator.md` **不是副本，是路由** —— 因为 `agent-skill-creator` 是 40 KB 的工具箱（20+ Python 脚本、自带测试、registry、三个示例 skill），复制 SKILL.md 会让它变成读不了的死文本。

**路由型条目没有副本，所以不存在"内容同步"问题。** 这类文件的头部不写 `上游指纹`，改写 `路由目标：<路径>` —— 脚本对它只做一件事：**检查那个路径还在不在**。

⚠️ 这是有意义的检查：整个 `agent-skill-creator` 目录要是被删了或改了名，路由就**断链**了，而副本比对查不出这种问题。

## 混合型条目（`07`、`08`、`10`、`11`）

**混合型条目 = 副本，但上游目录不止 `SKILL.md` 一个文件，而正文引用了其中几个。**
本项目**只搬正文**，支撑文件留在原目录（位置写在各自顶部的横幅里）。

| 整合条目 | 上游目录 | 正文引用的支撑文件 |
|---|---|---|
| `07-writing-skills.md` | `writing-skills/`（7 文件 / 105 KB） | 6 个 |
| `08-brainstorming.md` | `brainstorming/`（5 文件 / 60 KB） | 1 个（`visual-companion.md`） |
| `10-test-driven-development.md` | `test-driven-development/`（2 文件 / 18 KB） | 1 个（`testing-anti-patterns.md`） |
| `11-systematic-debugging.md` | `systematic-debugging/`（12 文件 / 41 KB） | 3 个 |

所以它们的头部**照常写 `上游指纹`**（脚本只比对 `SKILL.md` 这一个文件），**但脚本查不到这些支撑文件**：

| 脚本能查到 | 脚本查不到（已知盲区） |
|---|---|
| 各自 `SKILL.md` 改了没 | 支撑文件被删 / 改名 / 改了内容 |

**这是明知故犯的取舍，不是疏漏。** 把几十 KB 的支撑文本也搬进来做全量比对，换来的只是冗余；不值。

⚠️ **但这一条有解 —— 横幅里的路径是唯一线索，所以它们必须是对的。** 一条命令核完全部 11 条：

```bash
cd "C:/Users/ROG/.claude/skills"
for p in \
  writing-skills/anthropic-best-practices.md \
  writing-skills/testing-skills-with-subagents.md \
  writing-skills/persuasion-principles.md \
  writing-skills/graphviz-conventions.dot \
  writing-skills/render-graphs.js \
  writing-skills/examples/CLAUDE_MD_TESTING.md \
  brainstorming/visual-companion.md \
  test-driven-development/testing-anti-patterns.md \
  systematic-debugging/root-cause-tracing.md \
  systematic-debugging/defense-in-depth.md \
  systematic-debugging/condition-based-waiting.md ; do
    [ -e "$p" ] || echo "❌ 断链：$p"
done; echo "（上方无输出 = 11 条路径全在）"
```

**什么时候跑**：① 动了上面这 4 个上游目录里的任何文件之后；② 隔一段时间没动这个项目、回来时。

## 横幅 vs 正文：改哪儿？

副本 = **横幅**（本项目写的）+ **正文**（从上游抄来的）。**规矩完全不同：**

| 部分 | 能改吗 | 为什么 |
|---|---|---|
| **横幅**（中文标题、`> ⚠️` 那几段、交叉引用映射） | ✅ **该改就改** | 本项目原创，原版没有这段 → 改了不用同步原版 |
| **正文**（上游英文原文） | ❌ **一个字都不许动** | ① 改了就得同步上游，但那些 `superpowers:` 前缀在本机本来就不存在，改了反而制造漂移；② **更要命的是 —— 正文一旦被改，逐行 `diff` 就不再能证明保真**，以后每次同步都得人工复核 |

**所以正文里那些"指向别处"的引用，一律不正文、只横幅。** 已经这样处理的有：

| 正文里写的 | 横幅里的映射 |
|---|---|
| `superpowers:test-driven-development`（10 自己、11 的两处） | → [10-test-driven-development](10-test-driven-development.md) |
| `superpowers:verification-before-completion`（11） | → [12-verification-before-completion](12-verification-before-completion.md) |
| `superpowers:writing-plans`（08） | → [09-writing-plans](09-writing-plans.md) |
| `superpowers:using-git-worktrees`（09） | 未整合 —— 本项目不是 git 仓库 |
| `superpowers:subagent-driven-development` / `executing-plans`（09） | 未整合 —— 执行类暂缓 |

## ⚠️ 脚本查不出的那件事：副本**抄得对不对**

**这是最容易骗过自己的一处。** `sync-check.sh` 比对的是**上游文件的哈希**，它**从来没见过你的副本**。

| 脚本说 | 它实际证明的 | 它**没有**证明的 |
|---|---|---|
| `✅ 一致` | 「上游自 `同步日期` 起没被人改过」 | 「你这份副本和上游逐行相同」 |

**换句话说：副本里抄错、漏抄一整段、多抄一段 —— 脚本全都报 ✅。**

真实案例（2026-09-20，建 `07-writing-skills.md` 时）：684 行正文里有 **1 行抄错** —— 一段 graphviz 流程图里
`"Decision where I might go wrong?" -> "Use markdown"` 被抄成了 `"Need to show information?" -> "Use markdown"`。
**脚本报 ✅ 一致**，是事后逐行 diff 才抓到的。这行会让流程图多一条边、少一条边 —— 图整个是错的。

### 所以：**不要手抄。** 用 `scripts/make-copy.py` 生成，再独立 `diff` 复核

**两道防线，缺一不可 —— 它们防的不是同一件事：**

| 防线 | 防什么 | 怎么跑 |
|---|---|---|
| **① 机械复制** | **抄错**（漏行 / 多行 / 改字） | `python scripts/make-copy.py` |
| **② 独立 diff** | ① **自己写错了**（切片起点不对、拼装时串了文件） | 见下方命令 |

⚠️ **只有 ① 不够**：① 和 ② 若出自同一个假设（例如"第一行 `# ` 就是正文起点"），这个假设一错，两道防线一起瞎。
所以 ② 必须用**不同实现**去核 —— ① 是 Python 切片，② 是 `sed` + `awk`。

#### ① 生成

```bash
cd "C:/Users/ROG/.claude/skills/fpga-project-development/scripts"
python make-copy.py            # 生成（覆盖写，写完立刻回读自检）
python make-copy.py --check    # 只校验已存在的副本，不写文件
```

要加新副本，就去 `make-copy.py` 顶部的 `COPIES` 表加一条（上游目录名 / 目标文件名 / 中文标题 / 头部补充说明 / 横幅正文）。
**它同时把头部要写的指纹算好** —— 不用自己 `sha256sum`。

#### ② 独立复核（`diff` **无输出**才算过）

```bash
SK="C:/Users/ROG/.claude/skills"; REF="$SK/fpga-project-development/references"
for pair in "brainstorming:08-brainstorming.md" "writing-plans:09-writing-plans.md" \
            "test-driven-development:10-test-driven-development.md" "systematic-debugging:11-systematic-debugging.md" \
            "verification-before-completion:12-verification-before-completion.md"; do
  u="${pair%%:*}"; c="${pair##*:}"
  sed -n '/^# /,$p' "$SK/$u/SKILL.md" > /tmp/up.txt
  head -1 /tmp/up.txt > /tmp/t.txt
  awk 'BEGIN{while((getline t < "/tmp/t.txt")>0) tgt=t} f{print} $0==tgt{f=1; print}' "$REF/$c" > /tmp/cp.txt
  diff -q /tmp/up.txt /tmp/cp.txt >/dev/null && echo "✅ $c" \
    || { echo "❌ $c 抄错了："; diff /tmp/up.txt /tmp/cp.txt | head; }
done
```

有输出就是抄错了 —— **逐行核对后把副本正文改回去，不要改上游。**

📌 **`07-writing-skills.md` 不在这条命令里** —— 它是 2026-09-20 手工建的（当时还没有 `make-copy.py`），
正文已用同法验过：684 行，逐个字节一致（那次抄错的一行就是这么抓出来的）。要用 `--check` 核它，
得先把它补进 `COPIES` 表，但那会**重新生成整个文件**（横幅文字必须一字不差地重录）—— 不划算，就让它手工维护。

**什么时候跑**：新建副本、或大段改副本之后。日常改一两句横幅不用跑。

## 操作规程

### A. 新建一个副本

1. 去 `scripts/make-copy.py` 顶部的 `COPIES` 表加一条（**指纹它会自己算**，别手抄）。
2. `python "C:/Users/ROG/.claude/skills/fpga-project-development/scripts/make-copy.py"`
3. **跑独立 diff 复核**（上一节的 ②）—— **无输出**才算过。
4. 去 `SKILL.md` 的整合名单表 + 路由表各补一行。

### B. 改一个已存在的条目

0. **先找齐「同一条知识」在这个 skill 里有几份 —— 通常是 3 份，漏一份就是让另两份变成假话。**
   以存档规程为例（2026-09-26 实改过）：

   | # | 位置 | 那一份长什么样 |
   |---|---|---|
   | 1 | **`SKILL.md`** 的目录约定节 | 总入口 —— **每轮都读，最不能是假话的一份** |
   | 2 | **`references/XX.md` 的横幅** | 权威完整版（如 09 的「存什么 / ⛔ 绝不存」表） |
   | 3 | **`scripts/make-copy.py` 的 `COPIES` 表** | 生成源，与第 2 份**逐字相同**（下面第 1 步的要求） |

   一条命令找齐（在 `fpga-project-development/` 下跑）：
   `grep -rn "<这条规程里的一个独特短语>" .`
   —— 2026-09-26 实测：改前 3 命中、改后 0 命中，**命中数就是份数**。

1. **判断改的是横幅还是正文**（见上一节「横幅 vs 正文」）：
   - **横幅** → 改 `references/XX.md` **和** `make-copy.py` 里的 `COPIES` 表。**两边必须一致**，
     否则下次生成会被覆盖保护拦下（拦下了 = 你漏改了 `COPIES` 表）。
   - **正文** → ⛔ 不许改。
2. **判断要不要同步原版**：按上面的真值表。
3. **要动就立刻动** —— 同一个回合内改完，不隔夜、不记 TODO。
4. **刷新指纹**（**仅当上游真的变了**）：`python scripts/make-copy.py` —— 它重算指纹并写进头部。
   ⚠️ 这一步**覆盖整个文件**，所以第 1 步的横幅必须已经同步回 `COPIES` 表。
   ✅ **顺带：这一步同时就是横幅一致性检查** —— 两边不一致的文件会被 `⛔ 拒绝覆盖` 拦下并点名。
   **一个都没被拦 = 磁盘与 `COPIES` 表逐字一致。**（2026-09-20 改成 08/09/10 三份横幅时实测过。）
5. **跑 `sync-check.sh`** 确认全绿。

## 检查脚本

```bash
bash "C:/Users/ROG/.claude/skills/fpga-project-development/scripts/sync-check.sh"
```

三种文件类型、六种输出：

| 输出 | 类型 | 含义 |
|---|---|---|
| `✅ 一致` | 副本 | 整合版和原版没脱节 |
| `⚠️ 上游已变` | 副本 | **原版被改过，整合版没跟上**（也可能只是你改了原版忘了刷新指纹） |
| `❌ 上游缺失` | 副本 | 原版文件找不到了（被删/被改名） |
| `· 路由` | 路由 | 指针目标存在，正常 |
| `❌ 路由断链` | 路由 | 指针指向的目录不存在了 |
| `★ 自有` | 自有 | 本项目原创，无上游，跳过 |
| `❌ 头部格式错误` | ? | 三种标记一个都没有，无法判断该怎么处理 |

**文件头部的三种写法**（`<!-- -->` 注释里，位于文件最顶端）：

```html
<!-- 副本：来源 + 指纹 + 日期 -->
来源：C:\Users\ROG\.claude\skills\XXX\SKILL.md
上游指纹（sha256 前 16 位）：0123456789abcdef
同步日期：2026-09-20
```

```html
<!-- 路由：只写目标路径 -->
路由目标：C:\Users\ROG\.claude\skills\XXX\
```

```html
<!-- 自有：只写这一行 -->
类型：自有
```

**什么时候跑**：① 任何一次改了 `references/` 之后；② 每次要拿这个 skill 的结论去写正式文档之前（答辩材料、技术方案）；③ 隔一段时间没动这个项目，回来时。

⚠️ 脚本只比对**指纹**，只能告诉你"变了"，**不能告诉你变了什么**。报 `⚠️` 时去 `diff` 一下再决定怎么合。
