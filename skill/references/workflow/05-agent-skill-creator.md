<!--
类型：路由
路由目标：<本机 skill 安装目录>/agent-skill-creator/
⭐ 本文件【不是】整合副本，而是【路由】—— 所以没有"上游指纹"，只检查目标目录还在不在。
   原因：agent-skill-creator 是一个 40 KB 的工具箱 —— 20+ 个 Python 脚本、自带测试套件、
   registry、三个完整示例 skill。复制 SKILL.md 会让它变成读不了的死文本。
   要用时，回原地用。详见 06-sync-protocol.md 的"路由型条目"一节。

⚠️ 2026-11-03 随技能包合并补入：原包把它丢了，但 06-sync-protocol.md 的
   "路由型条目"一节正是拿它当例子讲的，不补上那段就变成了讲一个不存在的文件。
   路由目标是一个**第三方 skill 的本机安装**，不随本包分发 —— 外部读者读的是
   下面这套"什么时候该去调 / 不该建 skill 的情况 / 两条硬规则"，不需要那个目录。
-->

# 造技能（Skill Creation）

**本条目是路由，不是副本。** 需要新建或修改 skill 时，**回原地调用**：

| 要做什么 | 去哪 |
|---|---|
| 建一个完整 skill（含评估、打包、多平台导出、registry） | 本机 skill 安装目录下的 `agent-skill-creator/` |
| 只写/改一个 SKILL.md 的正文与 description | **读 [07-writing-skills](07-writing-skills.md)** —— 已是副本，不用回原地 |

`agent-skill-creator` **不在**整合名单里 —— 也就是说，**调用它不算违反"只用总 skill"的约定**。
（`writing-skills` 已在整合名单内，改读 [07-writing-skills](07-writing-skills.md)。）

## 什么时候该去调

- 用户说"创建一个 skill"、"做个 skill"、"改改这个 skill"
- 要写或修改任何 `SKILL.md`
- 要把一套反复用的流程固化下来

## 不要为了建 skill 而建 skill

`writing-skills` 明确列了**不该建**的情况：

- 一次性的解决方案
- 已有良好文档的标准做法
- **项目专属约定（那应该写进指令文件，不是 skill）**
- 能用正则/校验自动强制的机械约束

## ⚠️ 两条最容易违反的硬规则（先记住，再去看原文）

1. **description 只写"什么时候加载"，绝不写"做什么"。**
   已实测的教训：description 里概括了工作流，agent 会**照 description 做而不读正文** —— 一个写着"任务间做代码审查"的 description 导致 agent 只做了**一次**审查，尽管正文流程图明明白白画着**两次**。

2. **铁律：没有失败的测试，就没有 skill。**
   新建和**修改**都算。先跑基线（不给 skill，看 agent 怎么失败），记下它用的借口，再写 skill 去堵这些借口。
   ⚠️ 这一条与现实排期有张力 —— 若选择跳过，**必须明确告诉用户"这一步没做"**，不许假装做过。

## 本项目的一个具体约定

总 skill 自己就是一个 skill。**改它的时候，上面两条同样适用** —— 尤其是改 description 时，回去读一遍 [07-writing-skills](07-writing-skills.md) 的 SDO 一节。
