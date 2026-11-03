# FPGA 技能包（skill/）提交说明

对应竞赛《选题指南（AMD）》3.3.5.2「技能包」。内容全部位于 `skill/`。

- **给人看的导航**：`skill/README.md` —— 每一项的适用范围 / 使用方法 / 已验证的效果 / 失效条件 / 来源
- **给智能体看的入口**：`skill/SKILL.md` —— 路由表与触发条件
- **可执行脚本**：`skill/scripts/` —— 10 个，7 个带 `--selftest`
- **文件清单**：`MANIFEST.txt`（逐文件 sha256，163 条；Linux 上大小写敏感，别写成小写）

## 通用性（竞赛加分主体）

`skill/references/generic/`（11 篇）、`skill/scripts/`（10 个）、`skill/pitfalls/`（449 条）——
**不限题目、不限板卡**：换一个 FPGA 题目、换一块板仍然可用。

`skill/references/workflow/`（14 篇）是与大模型协作的方法论，通用但并非 PYNQ 专属。
`skill/ui-ux-pro-max/` 是**第三方 MIT 界面设计目录**（配色/字体/图标/动效/评审清单 + 检索脚本），
随附 LICENSE，**不计入本队原创**。

`skill/references/team/`（6 份）与 `skill/project/`（领域层）与本题绑定，**不参与通用加分**。

## 覆盖官方点名的四类校验

| 官方举例 | 脚本 |
|---|---|
| 黄金参考比对 | `skill/scripts/check-golden.py` |
| 检查资源与时序 | `skill/scripts/check-timing.py` |
| 验证工程可复现性 | `skill/scripts/check-repro.py` |
| 从接口契约生成主机侧代码 | `skill/scripts/gen-host-skeleton.py` |

## 本次合并

并入两份并行交接包的全部内容：

- `fpga-skill-package-2026-11-01`（6 个脚本 + 6 份自有沉淀 + 10 篇外部工作流）
- `fpga-skill-package-2026-11-01-amd-ui`（第三方 UI 目录 + 嵌入式触摸 UI + 布局校验器 +
  AI 与传统协作案例 + 标注复核流程 + 提交要求对照）

**原有内容一条未删。** 七个脚本的 `--selftest` 与新增的 UI 布局自检均已在本机跑通。

---

## 并入交付仓库时的改动（2026-11-03）

原交接包 `fpga-skill-package-2026-11-02.zip`（sha256 前 16 位 `7a854f97bd34a216`，162 条清单）
**内容全部保留**，另做 6 处修补 —— 起因都是一个：有几份文件被正文引用，原包却没带上。

| # | 改动 | 为什么 |
|---|---|---|
| 1 | 补 `references/workflow/05-agent-skill-creator.md` | `06-sync-protocol.md` 的「路由型条目」一节正是拿它当例子讲；缺了它，那一段在讲一个不存在的文件 |
| 2 | `references/workflow/README.md` 标题 13 篇 → **14 篇**，导航表与四元组表补 `05`、`14` 两行 | 原表漏了这两篇，而正文说明里又写着「当前共 14 篇」 |
| 3 | 同上，§三「已知的断链」补 `06-sync-protocol.md` → `scripts/make-copy.py`、`scripts/sync-check.sh` | 这两个维护脚本绑本队本机的 skill 安装，**未随包分发**；照抄命令会全线报 `上游缺失` |
| 4 | `SKILL.md` 目录索引：`references/workflow/` 由「10 篇」改为「14 篇」并补齐清单 | 与第 2 条对齐 |
| 5 | `references/team/14-coding-pitfalls.md` 自查清单里给 `sync-check.sh` 加一句「未随包分发」 | 同第 3 条，避免读者去跑一个不存在的脚本 |
| 6 | 本文件由包根的 `README.md` 改名为 `PACKAGE-README.md` | 本目录已有一个 `README.md`（给人看的导航），同名会撞 |

`MANIFEST.txt` 按改完后的实际文件**重算**（头部注明了原包来源与改写原因）。
本目录全部 Markdown 相对链接已逐条试解析，**0 处断链**。

> 核对方法（两条命令，只依赖标准库）：
> `grep -o '\]([^)]*)'` 抽链接后逐个 `test -e`；清单则是逐文件
> `sha256sum` 与 `MANIFEST.txt` 比。两者都能判红 —— 故意写坏一个链接、改一个字节，
> 都会报出来。
