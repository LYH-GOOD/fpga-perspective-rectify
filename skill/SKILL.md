---
name: fpga-pynq-engineering
description: >
  Board-agnostic FPGA / PYNQ engineering skill — verified practices and failure modes
  for AXI-Stream handshake deadlocks, Verilog that synthesizes but simulates wrong,
  Vivado project automation on Windows, AXI DMA + Block Design bring-up,
  golden-reference bit-exact verification methodology, performance-measurement
  discipline, and mechanical guards against configuration drift.
  Use this skill whenever the user asks to "写流式握手", "valid/ready 反压",
  "AXI-Stream 死锁", "综合能过仿真不过", "上板结果不对", "Vivado 建工程",
  "Vivado 脚本", "XSim 报错", "AXI DMA 报错", "BD 搭不起来", "交付包在队友那边坏了",
  "行缓存", "时序约束", "性能怎么测", "指标口径", "账对不上", "噪声底", "控制组",
  "配置不一致", "自检脚本坏了", "检查通过了但不放心", "副本漂移",
  or mentions "stream handshake", "AXI-Stream backpressure", "Vivado on Windows",
  "AXI DMA", "Block Design", "golden reference", "bit-exact verification",
  "PYNQ overlay", "line buffer", "simulation/synthesis mismatch", "delivery package",
  "timing constraints", "performance measurement", "measurement noise floor",
  "优化哪一段", "这段是不是白花的", "A/B 怎么做", "开关有没有生效", "埋点怎么加",
  "日志里看不出来", "这个参数到底生效没", "改了反而更慢", "帧率上不去",
  "帧率差的不是几毫秒", "中位数还是均值", "分项加起来对不上", "排队还是计算",
  "图像缩放很慢", "最近邻", "双线性", "ARM 上比 PC 慢", "64 位除法",
  "主机测了但板上不一样", "显示帧率", "观感没变好", "内部指标变好但看着更卡",
  "instrumentation", "A/B experiment", "is this step dead weight",
  "flag not taking effect", "logging does not tell me",
  "control group", "mechanical guard", "self-test failure", "copy drift",
  "single source of truth", "median vs mean", "queue wait is not cost",
  "host benchmark does not transfer to ARM", "user-visible metric",
  "Overlay 加载失败", "ip_dict 为空", "找不到 IP", "register_map", "寄存器读回不对",
  "DMA 数据偶尔错一格", "缓存一致性", "flush invalidate",
  "帧率怎么算", "丢帧率", "日志怎么统计", "提示词怎么写", "让 AI 改代码",
  "触摸屏界面", "UI 布局", "按钮点不到", "字体太小", "配色", "界面评审",
  "嵌入式 UI", "FPS 显示", "进度条卡住", "AI 与传统方法怎么配合",
  "标注复核", "版本计划", "交付证据", "竞赛提交要求",
  "embedded touch UI", "UI layout check", "hit target", "submission requirements".
  Also use when setting up an FPGA project from scratch, writing synthesis-safe
  Verilog HDL, designing a verification criterion that can actually catch bugs,
  deciding what to optimize next, tracking down why a check script passes when it
  shouldn't, or packaging a reproducible Vivado build for someone else's machine.
  ⚠️ Deliberately NOT tied to any particular problem or board: the content is
  stated so it transfers to a different题目 or a different FPGA board unchanged.
  For the topic-specific companion (single-view plane geometry / streaming image
  remapping), see `project/SKILL.md`.
  Do NOT use for pure algorithm/software work with no RTL or board involvement.
argument-hint: "[症状关键词或主题，例如 \"上板结果不对\" / \"AXI DMA\" / \"账对不上\"]"
metadata:
  version: "2.1.0"
  layer: "generic (换题换板仍可用)"
  upstream-style: "AMD ROSS official skill format (2026-09); the official samples themselves are not redistributed here"
---

# FPGA / PYNQ Engineering Skill（通用层）

## Purpose

**与题目、与板卡无关**的 FPGA 工程经验：那些**会反复踩的坑**，以及**能自动查出问题的方法**。

**Expected outcome：** 拿一份按"症状"可检索的踩坑清单 + 11 篇通用方法 + 可执行脚本索引 +
真实样例，**换一个题目、换一块板卡仍然可用**。

**Prerequisites：** 无。只读文档 + 独立 Python 脚本，不依赖本仓库的 RTL 或板卡。

> ⚠️ **本层刻意不提具体题目。** 它是从真实项目里提炼的，但**每一条都写成"换题仍成立"的形式**。
> 与某个题目绑定的领域知识在 [`project/SKILL.md`](project/SKILL.md)（**单向依赖**：那边引用这边，不复制）。

---

## When to Use

- **刚拿到板子**，要建第一条上板通路（`references/generic/03` + `04`）
- **RTL 综合过了但上板结果不对**（`references/generic/01` + `05`）
- **要往 PS/PL 协同的项目走**（`references/generic/06` + `project/references/templates/`）
- **撞到某个具体报错/异常** ⇒ 直接翻 `pitfalls.md`，按"症状"列对号入座
- **要拿数据做决策**（优化前 / 报数字前）⇒ `references/generic/07`
- **要加检查脚本 / 换进程模型 / 一个参数出现在多处** ⇒ `references/generic/08`
- 写 RTL / 搭 Vivado 工程 / 设计验证判据 / 打包交付物之前

## When NOT to Use

- **纯算法/纯软件**工作，不涉及 RTL 或板卡 ⇒ 用不着
- **想查某个题目的领域算法**（如单应矩阵、图像几何变换）⇒ 看 [`project/SKILL.md`](project/SKILL.md)
- **知道项目现在做到哪了** ⇒ 看项目 `README.md` 和 `report/`，不是本 Skill
- **要用 Vivado 执行具体命令**（建工程/综合/实现/烧录）⇒ 用 **Vivado MCP 工具**，不是本 Skill（见下）

---

## ⭐ 本 Skill 与官方 MCP 的分工

| 干什么 | 用什么 |
|---|---|
| **执行**命令（建工程 / 综合 / 实现 / 时序 / 烧录） | **官方 Vivado MCP**（`vivado_start` / `vivado_execute` / … 11 个工具） |
| **怎么设计、写什么代码、为什么这么写、踩过什么坑** | **本 Skill** |
| 静态检查（XDC lint / 语法 / 离线解析工程） | **`vivado-kit` MCP**（`xdc_lint` 等，不启动 Vivado） |

> **本 Skill 存在的意义**：MCP 能替你敲命令，**但它不知道你的设计该怎么写**。
> 那部分经验在这里。

---

## 目录索引

| 项 | 类型 | 适用范围 | 失效条件 |
|---|---|---|---|
| [`pitfalls.md`](pitfalls.md) | **踩坑清单总索引**（按症状路由）| **全部 FPGA 项目** | 换工具链版本后部分条目需重新确认 |
| [`pitfalls/`](pitfalls/) | **8 个主题分册，449 条**（测量 / 守卫 / 验证 / 工具链 / 交付 / 综合 / 杂项 / 复盘）| **全部 FPGA 项目** | 同上 |
| [`references/generic/01-stream-handshake.md`](references/generic/01-stream-handshake.md) | 踩坑 + **5 条铁律** | **任何 valid/ready 流式设计** | 纯 AXI-Lite 无流式的设计 |
| [`references/generic/02-verilog-and-synthesis.md`](references/generic/02-verilog-and-synthesis.md) | 踩坑+方法 | 任何 Verilog RTL | — |
| [`references/generic/03-vivado-toolchain.md`](references/generic/03-vivado-toolchain.md) | 踩坑+脚本 | **Windows 上的 Vivado** | Linux 下部分条目不适用 |
| [`references/generic/04-axi-dma-and-bd.md`](references/generic/04-axi-dma-and-bd.md) | 踩坑+方法 | 用 AXI DMA + Block Design | 不用 DMA 的项目 |
| [`references/generic/05-verification-method.md`](references/generic/05-verification-method.md) | **方法论** | **任何有"黄金参考"的设计** | — |
| [`references/generic/06-ps-pl-and-delivery.md`](references/generic/06-ps-pl-and-delivery.md) | 踩坑+方法 | PS+PL 协同的项目 | 纯 PL 项目 |
| [`references/generic/07-measurement-discipline.md`](references/generic/07-measurement-discipline.md) | **方法论**（**§七 优化三步法** / **§八 A/B 纪律** / **§十 统计口径·等待vs开销·主机不外推·用户指标**）| **任何拿数据做决策的项目** | — |
| [`references/generic/08-mechanical-guards.md`](references/generic/08-mechanical-guards.md) | **方法论+踩坑** | **任何有配置/生成物/检查脚本的工程** | — |
| [`references/generic/09-overlay-and-register-map.md`](references/generic/09-overlay-and-register-map.md) | **Overlay 加载校验四层 + register_map + 缓存一致性** | **任何用 PYNQ Overlay 的项目** | 裸机或无 Overlay |
| [`references/generic/10-prompt-workflow.md`](references/generic/10-prompt-workflow.md) | **提示词工作流**（从算法描述到 RTL、从综合报告定位瓶颈）| **任何用大模型辅助做 RTL 的项目** | 不用大模型 |
| [`references/workflow/`](references/workflow/) | **14 篇与大模型协作的方法论**（中文透明流程 / 先问再做 / 检索 / 路由 / 头脑风暴 / 写计划 / TDD / 系统化排查 / 完成前验证 / Word 排版 / 同步规程 / 版本计划与证据）| **任何用大模型做工程的项目**；**不是 PYNQ 专属** | 不用大模型辅助时用不上 |
| [`references/generic/11-embedded-touch-ui.md`](references/generic/11-embedded-touch-ui.md) | **嵌入式触摸 UI**：控件/命中矩形/帧归属、字体与配色、进度反馈 | **任何 PYNQ 或实时设备的触摸界面** | 不检查实际像素与物理触摸；需真机验收 |
| [`references/team/`](references/team/README.md) | **6 份并行开发沉淀**（编码踩坑 45 案例 / 测量硬案例 / Vivado 与 PL 构建 / 专项提示词 / 案例模板 / PYNQ 运行时）| 与 `generic/07/08/09/10` **配对使用**：那几篇给判据，这里给案例 | 见 `references/team/README.md` 映射表 |
| [`references/workflow/14-file-planning-and-evidence.md`](references/workflow/14-file-planning-and-evidence.md) | **多版本计划与交付证据**：基线、约束、检查结果写入持久文件 | **任何多轮迭代的工程** | 流程不保证性能收益 |
| [`ui-ux-pro-max/`](ui-ux-pro-max/SKILL.md) | **第三方 MIT 界面设计目录**（配色/字体/图标/动效/评审清单）+ 检索脚本 | **任何要做界面的项目** | **第三方素材，非本队原创**；不能算作泛化验证 |
| [`references/submission/`](references/submission/amd-requirements.md) | **竞赛提交要求对照**与本次抓取证据 | 提交前核对 | 以赛道官方指南为准 |
| [`scripts/`](scripts/README.md) | **10 个可直接拿走用的脚本**（黄金参考比对 / 时序资源检查 / 可复现性 / 从 .hwh 生成主机骨架 / DMA 封装 / 上板前体检 / 日志帧率统计 / 综合日志体检 / 交付包三方校验 / 嵌入式 UI 布局检查），只用标准库 | **任何 FPGA 工程**，换字段名与关键字即可 | 见各脚本头部注释与 `--selftest` |
| [`examples/`](examples/README.md) | **可直接运行的样例输入**（合成逐帧日志）+ 判据好坏对照 | **任何要算帧率 / 设计判据的项目** | — |
| [`project/SKILL.md`](project/SKILL.md) | **领域层**（题型绑定） | 流式图像几何变换 / 单目视觉平面测量 | **换题即失效** ⇒ 不在通用加分范围 |

**最快的一条路**：直接翻 [`pitfalls.md`](pitfalls.md)，按关键词找你现在遇到的问题。

---

## 通用性分级（竞赛加分项）

竞赛规则有一条：**"通用 PYNQ Skill 单独加分：不与本队题目绑定，换一个题目、换一块板卡仍然可用"**。

| 层 | 目录 | 换题还能用吗 | 换板还能用吗 |
|---|---|---|---|
| **① 通用** | **本目录**（`SKILL.md` + `references/generic/` + `pitfalls.md`） | ✅ 能 | ✅ 能 |
| **② 领域** | [`project/`](project/SKILL.md)（`references/domain/` + `pitfalls-domain.md`） | ⚠️ 同类题能 | ✅ 能 |
| **③ 项目** | 仓库 `src/` `sim/` `build/` | ❌ 不能 | ❌ 不能 |

**⇒ ① 是本 Skill 作为"通用加分项"的主体。** 它讲的是
"流式握手怎么写才不死锁""怎么设计判据才能抓住真 bug""怎么量数据才不被骗"
"怎么用机械闸防止配置漂移" —— **和具体做什么题目没有任何关系**。

---

## 评价标准

**可复用性。** 一支陌生队伍拿到这个目录，能不能直接用在自己的题目上。
所以每一项都写明：**适用范围 / 使用方法 / 失效条件 / 来源**。

---

## 来源与版本

| 项 | 值 |
|---|---|
| 来源 | 一个真实的 PYNQ-Z2 项目（2026-09 起）的**开发过程** —— 但**本层内容与该项目题目解耦** |
| 沉淀方式 | 每次解决问题写协作记录，阶段结束提炼进本目录 |
| 格式对标 | **AMD ROSS 官方 Skill 包**（2026-09 发布，50 个样例）—— `description` 写显式触发词、`When to Use` / `When NOT to Use` 分节 |
| 本版 | v2.1.0（2026-11-01）。上次更新 2026-10-22；本次补 `pitfalls/` 的 449 条计数（编号到 #465，编号上限 ≠ 条目数）、新增触发词、`references/generic/07` 增加 §十「连续四轮量错了」|
