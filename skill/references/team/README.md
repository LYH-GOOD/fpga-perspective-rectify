# references/team/ —— 队友沉淀的六份参考（2026-11-01 合并）

> 本目录是另一路并行开发沉淀下来的文档，**2026-11-01 并入队级 `skill/`**。
> 保留独立文件而**不拆散改写**，是为了不丢失原文的因果链与案例数据；
> 与现有泛用文档的关系在下面这张表里写清 —— **用途是"互相引用"，不是"各说各话"**。

## 一、映射表：每一份对应我们的哪一篇

| 本目录文件 | 讲什么 | 与现有文档的关系 | 建议读法 |
|---|---|---|---|
| [`14-coding-pitfalls.md`](14-coding-pitfalls.md)（93 KB）| A–I 组编码与工程细节 + **45 个实测案例** | **案例明细**；`pitfalls/` 是**症状索引**（449 条）。两者互补：先按症状查编号，再来这里看完整复盘 | 排障时先查 `pitfalls.md`；需要看"当时到底怎么查出来的"再来这里 |
| [`15-measurement-and-comparison.md`](15-measurement-and-comparison.md) | 测量与对比的硬案例 | **`references/generic/07-measurement-discipline.md` 的案例集**。07 讲方法与判据，本文给本项目实测数据 | 读完 07 的 §七/§八/§十，用本文的例子校验自己是否真的理解了 |
| [`16-vivado-and-pl-build.md`](16-vivado-and-pl-build.md) | Vivado / HLS / BD / 交付主干 | 覆盖 `generic/02`（Verilog 与综合）、`generic/03`（工具链）、`generic/04`（DMA 与 BD）三篇的**实践侧** | 建工程 / 搭 BD / 出 bit 时当操作手册；原理与判据看 generic 三篇 |
| [`17-prompt-workflows.md`](17-prompt-workflows.md) | 按**任务类型**分的 5 个专项提示词模板 | **`references/generic/10-prompt-workflow.md` 的补充章节**（10 讲通用模式，本文给专项模板）| 两者合起来用：先用 10 的模板定框架，再用本文的专项模板补细节 |
| [`18-case-templates.md`](18-case-templates.md) | 案例模板（工程骨架 / 脚本 / 报告）| 与 `project/references/templates/` 同层 | 开新题时从这里起步 |
| [`19-pynq-runtime.md`](19-pynq-runtime.md) | PYNQ 运行时：Overlay 加载、`.hwh` 解析、`register_map` 范式 | **`references/generic/09-overlay-and-register-map.md` 的展开**。09 给判据与定位表，本文给 `.hwh` 的结构事实与实测细节 | 对应官方加分原文①「Overlay 加载与校验、register_map 使用范式」 |

## 二、为什么保留独立文件，而不是拆开揉进现有文档

| 理由 | 说明 |
|---|---|
| **因果链不能拆** | `14` 的每个案例是"现象 → 怎么查 → 根因 → 判据"，拆进症状索引后就只剩结论，**下次遇到变体会查不出来** |
| **避免制造第二份正本** | 揉进去就得维护两处；保留独立文件 + 映射表，改动只发生一次 |
| **体积** | `14` 有 93 KB；`generic/08` 现在 9 KB，硬并会让它变成 100 KB，违反"单篇可读" |

## 三、每一项的四元组

| 文件 | 适用范围 | 使用方法 | 已验证的效果 | 失效条件 |
|---|---|---|---|---|
| `14-coding-pitfalls` | 任何 Windows/Linux 上写 Python/脚本做 FPGA 工程的团队 | 排障时按 A–I 分组定位 | 45 个案例全部来自本项目实测失败 | 换语言栈（如全 C++）后 A/B/C 组部分失效 |
| `15-measurement-and-comparison` | 任何"拿数据做决策"的工程 | 与 `generic/07` 配合，作案例校验 | 见文内逐条实测数字 | — |
| `16-vivado-and-pl-build` | Vivado 2020.x+ / PYNQ 工程 | 建工程、搭 BD、出 bit 时对照 | 26 条板级 memory 收敛而来 | 非 AMD 工具链（如 Quartus）不适用 |
| `17-prompt-workflows` | 用大模型辅助做 FPGA 工程 | 与 `generic/10` 配合 | 模板均在实际对话中用过 | 模型无工具执行能力时效果减半 |
| `18-case-templates` | 新题目起步 | 改路径/改参数直接套 | 本仓库可复现 | 非 PYNQ 板卡需改地址与时钟 |
| `19-pynq-runtime` | 任何用 PYNQ `Overlay` 的项目 | 加载后校验、写寄存器前读 | 直接解析本项目真实 `.hwh` 得到 | 裸机 / 不用 PYNQ |

## 四、来源

这六份由**同一项目**（PYNQ-Z2 平面校正，2026-09 ~ 11）的另一路开发沉淀，
2026-11-01 随 `fpga-skill-package-2026-11-01` 交接包并入。
原始清单与逐文件 sha256 见该交接包的 `manifest.txt`。
