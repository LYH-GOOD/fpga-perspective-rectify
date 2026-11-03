# 技能包（Skill）· 人类阅读导航

> ⭐ **给 AI 智能体看的入口是 [`SKILL.md`](SKILL.md)**（官方 Skill 包格式，带 YAML frontmatter 与触发词）。
> **本文件是给人看的导航页** —— 两边的索引内容一致，只是详略和受众不同。
> **交付/评审视角的说明**（对应竞赛指南 3.3.5.2「技能包」、通用性加分怎么算、四类官方校验脚本在哪）见 [`PACKAGE-README.md`](PACKAGE-README.md)。
>
> 从"FPGA 平面图像自适应校正"这个题目的**真实开发过程**中沉淀的可复用经验。
>
> **评价标准是可复用性** —— 一支陌生队伍拿到这个目录，能不能直接用在自己的题目上。
> 所以每一项都写明：**适用范围 / 使用方法 / 失效条件 / 来源**。

---

## 目录结构（2026-10-02 改为官方 Skill 格式）

```
skill/
│  ── ① 通用层（换题换板仍可用）═══ 竞赛"通用 PYNQ Skill"加分主体
├── SKILL.md          ⭐ AI 入口（官方 format：frontmatter + 触发词 + When to Use/NOT）
├── README.md         本文件（人类导航）
├── pitfalls.md       ⭐ 踩坑清单**总索引**（按症状路由到 8 个分册）
├── pitfalls/         8 个主题分册，**449 条**（2026-11-01 从单文件 488 KB 拆出）
├── references/generic/   11 篇通用方法（FPGA / PYNQ 向）
├── references/workflow/  14 篇与大模型协作的方法论（非 PYNQ 专属）
├── references/team/      6 份并行开发沉淀（案例明细，与 generic 配对）
├── scripts/          **10 个可直接拿走用的脚本**（黄金参考 / 时序资源 / 可复现性 / 主机骨架 / DMA / 上板体检 / 帧率统计 / 综合日志 / 交付包）
├── examples/         可直接运行的样例输入 + 判据好坏对照
│
└── project/          ── ② 领域层（题型绑定，换题即失效）
    ├── SKILL.md      ⭐ 领域层入口
    ├── references/   domain/ prompts/ templates/
    └── pitfalls-domain.md   领域踩坑（与通用清单【编号连续】）
```

> ⭐ **两层是【单向依赖】**：`project/` **引用**通用层，**不复制**它 ——
> 避免"副本漂移"（`pitfalls.md` #93~#97）。

**为什么改成这个结构**：2026-10-01 AMD 发布 **ROSS** 套件（本地知识库 + 设计经验技能包 +
Vivado/Vitis MCP），老师明确要求**「个人写的 Skill 借鉴官方 Skill 包的写法」**。

**⚠️ 官方样例不在本交付包里**（它属于 AMD，不随本工程分发）。
**你如果要对照，去 AMD ROSS 官方渠道取**；本目录只保证**遵循同一套格式约定**：
YAML frontmatter（`name` / `description` 含 `Use when …` 触发词 / `argument-hint` /
`metadata.version`）+ `references/` + `examples/` + `scripts/` + 「When to Use / When NOT to Use」。
详见 [`SKILL.md`](SKILL.md)。

---

## 一、先看这里：这个技能包对你有什么用

本技能包**不是**"图像校正算法教程"。它是**做 FPGA 项目时那些会反复踩的坑**，
以及**能自动查出问题的脚本和方法**。

三类人可以直接拿去用：

| 你是 | 直接看 |
|---|---|
| 刚拿到板子，要建第一条上板通路 | `references/generic/03-vivado-toolchain.md` + `references/generic/04-axi-dma-and-bd.md` |
| RTL 综合通过了，但上板结果不对 | `references/generic/01-stream-handshake.md` + `references/generic/05-verification-method.md` |
| 要往 PS/PL 协同的项目上走 | `references/generic/06-ps-pl-and-delivery.md` + `templates/` |

**最快的一条路**：直接翻 [`pitfalls.md`](pitfalls.md) 的目录，
按关键词找你现在遇到的问题。**449 条分册在 [`pitfalls/`](pitfalls/)，编号到 #465**；
[`pitfalls.md`](pitfalls.md) 是总索引，按「症状 → 该看哪册」路由。

---

## 一之二、⭐ 近期主题索引（2026-10-15 → 10-17，19 篇）

> **想复现某条经验是怎么来的，按主题找这几篇。** 完整列表见 `report/llm_log/`。

| 主题 | 关键结论 | 记录 |
|---|---|---|
| **队友 v73 交接 / 工程接收** | 三套代码库怎么区分；同一个 bit 不等于同一条路径 | `2026-10-15_v73_handover` · `2026-10-15_vivado_project_intake` |
| **V1.1 上板基线** | 54 文件全平铺、`verify_package` 哈希校验、**改模块必须同步 manifest** | `2026-10-15_v11_folder` |
| **DMA 分块优化** | 逐块边际成本 ≈3.4 ms；proof 预算 12→24 ms ⇒ 分块 4~5→2、+8.5% fps | `2026-10-15_dma_tile_optimization` |
| **大目标第 0 步（可行性）** | 找四角 29.5 ms/帧；BRAM ① 档只要 1 个 RAMB36；**DDR 带宽只占 7.2%** | `2026-10-16_big_goal_step0_feasibility` · `..._q2_pixelpath` |
| **摄像头 OV5640** | 两档瓶颈不同（480p 是 PS、720p 是传感器）；**降速判别证明是信号完整性** | `2026-10-16_ov5640_fps_diagnosis` · `2026-10-16_camera_ov5640_diag` · `2026-10-16_camera_board_run_analysis` |
| **日志工具化** | 板上的日志要**自带结论**（跑完自动摘到末尾） | `2026-10-16_camera_log_autosummary` |
| **报告素材** | 补齐 EVIDENCE 的空缺 | `2026-10-16_report_gaps_filled` |
| ⭐ **动态卡顿（性能优化的完整案例）** | 见下 | 7 篇 |

**⭐ 动态卡顿那条线的 7 篇，正好演示了 `references/generic/07` §七/§八 的方法：**

| 步 | 做了什么 | 记录 |
|---|---|---|
| 1 | **先量**：按 `lk_trigger` 拆开，发现 `async_recovery` 占 26~39% 却只花 0.5 ms | `2026-10-17_lk_trigger_breakdown` |
| 2 | **加埋点（只读抄写）**：把已算好的时间抄进日志 | `2026-10-17_lk_instrumentation` |
| 3 | **拆账**：167 ms = LK 78 + LK 之外 89 | `2026-10-17_lk_timing_result` |
| 4 | **审查那段"LK 之外"**：产物下游全被 `gate['reliable']` 挡掉 ⇒ 白花 | `2026-10-17_boundary_research_audit` |
| 5 | **逐条门限验证**（rev6~8）：82.8% 的帧 support/rms 本来就合格 ⇒ 修错对象 | `2026-10-17_edge_rescue_instrumentation` |
| 6 | **A/B 三轮**（rev9~12）⇒ **采用**：尖峰 −28%、p90 −18%、中位持平、精度不变 | `2026-10-17_skip_research_ab_result` |
| 7 | 试"降找四角分辨率"⇒ **三档无差别，放弃** | `2026-10-17_quad_work_width` |
| 8 | **把第 6 步的成果合并进队友 V89（UI 版）**：先 diff 确认自动路径用的是 `v87_v74_tracking.py`，再把开关搬过去 | `2026-10-18_merge_v89_v11opt` |

---

## 一之三、⭐ 近期主题索引（2026-10-23 → 11-01，24 篇）

> 紧接上一节。同样只挑"能复现结论"的那几篇，完整列表见 `report/llm_log/`。

| 主题 | 关键结论 | 记录 |
|---|---|---|
| **OV5640 720p 线收尾** | 传感器端 21 MHz 上限，720p 只能到 5 fps ⇒ 放弃，改走 USB | `2026-10-23_ov5640_720p_5fps_analysis` |
| **零访存 vs 落 DDR** | 同板同尺寸：21.9 ms vs `cv2.remap` 68.9 ms（**2.2×**）| `2026-10-24_B1_zero_access_vs_ddr` |
| **YUYV 直接进 PL** | 色度转换搬进 PL，PS 只做行搬运 | `2026-10-24_c2_yuyv_pl` |
| **owner 段开销诊断** | 把 `owner_s` 拆成 dma_wait / input_copy / cache_sync / control | `2026-10-24_owner_overhead_diagnosis` |
| **行缓存"宽度换深度"** | `MAX_W 1024→512`、`ROWS 192→384` ⇒ 分块 4→1，帧时间 −38% | `2026-10-25_linebuf_width_to_depth` |
| **静态保持 + 手动模式** | 静止时复用几何结果换帧率；"手动固定"路线走不通的记录 | `2026-10-26_manual_static_hold` · `2026-10-26_manual_fixed_deadend` |
| **800×600 双档位** | 同 bit 切 480P/600P，切档要重开相机 | `2026-10-27_resolution_800x600` |
| **档位切换 UI** | 左下角点改帧率 → 弹窗选档；进度条校准到 1 s→95% | `2026-10-29_camera_profile_ui` |
| **显示加速** | NEON 5:4 多相替换标量双线性，`input_convert` 94→39.8 ms | `2026-10-29_v10_merge_display18` |
| ⭐ **换基线只 diff 软件** | 队友交接包硬件源码静默回退，核慢 1.53×；**必须同时 diff RTL** | `2026-10-30_v11_restore_fast_remap` |
| ⭐ **600P 预览 5:4 缩放** | 77.2 → **17.6 ms**（−77%），显示 10→15.5 fps，视野零损失；含"64 位除法让 ARM 慢 49%"的教训 | `2026-10-31_preview_5_4_nearest` · `2026-10-31_a_preview_scale_switch` |
| **静态保持参数** | 强制重测 0.8→2.0 s，`static_hold` 占比 87%→93% | `2026-10-31_b2_static_hold_max_s` |
| ⭐ **性能诊断四轮 / 用户指标** | 中位数≠帧率、排队≠开销、主机不外推 ARM、**内部指标变好≠观感变好** | `2026-10-31_static_service_breakdown` |
| **交接包交付** | 上板链四处咬合哈希；工程归档里可能是旧 RTL | `2026-10-31_handoff_package` |
| **报告性能章** | 数字全部换成可回溯的实测值 | `2026-10-31_report_performance_update` |

---

## 二、目录与索引

| 项 | 类型 | 适用范围 | 使用方法 | 失效条件 | 来源 |
|---|---|---|---|---|---|
| [`pitfalls.md`](pitfalls.md) | **踩坑清单总索引** | **全部 FPGA 项目** | 按「症状 → 该看哪册」路由 | 换了工具链版本后部分条目需重新确认 | 449 条真实失败 |
| [`pitfalls/`](pitfalls/) | 踩坑清单（8 分册） | **全部 FPGA 项目** | 按症状进对应分册，再按编号互相引用 | 同上 | 同上 |
| [`references/generic/01-stream-handshake.md`](references/generic/01-stream-handshake.md) | 踩坑+方法 | **任何 valid/ready 流式设计** | 写流控前先读 | 纯 AXI-Lite 无流式的设计 | 上板 3 次输出错误 |
| [`references/generic/02-verilog-and-synthesis.md`](references/generic/02-verilog-and-synthesis.md) | 踩坑+方法 | 任何 Verilog RTL | 写 RTL 时对照 | — | 综合/仿真不一致 |
| [`references/generic/03-vivado-toolchain.md`](references/generic/03-vivado-toolchain.md) | 踩坑+脚本 | Windows 上的 Vivado | 建工程前读 | Linux 下部分条目不适用 | 工具链报错 |
| [`references/generic/04-axi-dma-and-bd.md`](references/generic/04-axi-dma-and-bd.md) | 踩坑+方法 | 用 AXI DMA + Block Design | 搭 BD 时对照 | 不用 DMA 的项目 | 上板 DMA 报错 | 
| [`references/generic/05-verification-method.md`](references/generic/05-verification-method.md) | **方法论** | **任何有"黄金参考"的设计** | 建验证流程时读 | — | 3 个"上板才暴露"的 bug |
| [`references/generic/06-ps-pl-and-delivery.md`](references/generic/06-ps-pl-and-delivery.md) | 踩坑+方法 | PS+PL 协同的项目 | 交付前对照 | 纯 PL 项目 | 4 次"交付包在队友那边坏了" |
| [`references/generic/07-measurement-discipline.md`](references/generic/07-measurement-discipline.md) | **方法论** | **任何拿数据做决策的项目** | 优化前 / 报数字前读 | — | 指标口径差 5.9 倍、噪声底没量 |
| [`references/generic/08-mechanical-guards.md`](references/generic/08-mechanical-guards.md) | **方法论+踩坑** | **任何有配置/生成物/检查脚本的工程** | 加检查脚本前 / 换进程模型前读 | — | 配置三份拷贝、自检脚本自己卡死 |
| [`references/generic/09-overlay-and-register-map.md`](references/generic/09-overlay-and-register-map.md) | **方法论+踩坑** | **任何用 PYNQ Overlay 的项目** | 加载 overlay 后、写寄存器前读 | 裸机 / 不用 Overlay | 3 次"跑的不是我以为的那份硬件" |
| [`references/generic/10-prompt-workflow.md`](references/generic/10-prompt-workflow.md) | **提示词工作流** | **任何用大模型辅助做 RTL 的项目** | 开工前设约束 / 提问时套模板 | 无工具执行能力的纯聊天 | 自主执行踩坑、诊断被顺手改坏等 |
| [`references/workflow/`](references/workflow/) | **与大模型协作的方法论**（10 篇）| **任何用大模型做工程的项目** | 按需查阅，不是流程入口 | **不是 PYNQ 专属**；纯人工开发时用不上 | 并行开发那一路沉淀，2026-11-01 并入 |
| [`references/team/README.md`](references/team/README.md) | **并行开发沉淀**（6 份）| 与 `generic/07/08/09/10` 配对 | 先读映射表，再决定读哪份 | 见该 README 的四元组表 | `fpga-skill-package-2026-11-01` 交接包 |
| [`scripts/log_frame_stats.py`](scripts/log_frame_stats.py) | **校验脚本** | 任何有逐帧 JSONL 日志的项目 | `python3 scripts/log_frame_stats.py run.log --sample 4` | 日志非 JSONL | 复现人工核对的 30.73/24.34/20.8% |
| [`scripts/check_synth_log.py`](scripts/check_synth_log.py) | **校验脚本** | 任何 Vivado 工程 | `python3 scripts/check_synth_log.py runme.log` | 非 Vivado 日志 | 1850 行真实日志上命中 8 处+48 CW |
| [`scripts/verify_package.py`](scripts/verify_package.py) | **校验脚本** | 任何要打包交付的工程 | `--dir` 或 `--zip` + 清单 | 清单非"路径→sha256" | 真实交付 ZIP 369 项 0 不符 |
| [`examples/sample_frames.jsonl`](examples/sample_frames.jsonl) | **可运行样例** | 要算帧率 / 丢帧率 | 直接喂给 `log_frame_stats.py` | — | 合成两会话，输出 16.7% / 0% 丢帧 |
| [`project/references/prompts/ai-assisted-rtl-workflow.md`](project/references/prompts/ai-assisted-rtl-workflow.md) | 提示词工作流（**通用版见 generic/10**）| 用大模型写 RTL/PS 代码 | 提示词模板可直接套 | 模型换成非 Claude 需微调 | 本题全程 |
| [`project/references/domain/01-streaming-image-remap.md`](project/references/domain/01-streaming-image-remap.md) | 案例 | 流式图像几何变换 | 框图直接照搬 | **换题即失效** | 本题核心 |
| [`project/references/domain/02-single-view-geometry.md`](project/references/domain/02-single-view-geometry.md) | 案例+公式 | 单目视觉、平面测量 | 公式可直接用 | **换题即失效** | 4 个角度误差 24% |
| [`project/references/templates/`](project/references/templates/README.md) | 案例模板 | 新题目起步 | 脚本直接改路径就能用 | 非 PYNQ 板卡需改地址 | 本仓库可直接复现 |
| [`project/pitfalls-domain.md`](project/pitfalls-domain.md) | 领域踩坑 | 流式图像 / 单目几何 | 按"症状"列检索 | **换题即失效** | 与通用清单编号连续 |

---

## 三、通用性分级（这是加分项）

竞赛规则里有一条：**"通用 PYNQ Skill 单独加分：不与本队题目绑定，换一个题目、换一块板卡仍然可用"**。
所以本技能包把内容按通用性分了三层：

| 层 | 目录 | 换题还能用吗 | 换板还能用吗 |
|---|---|---|---|
| **① 通用** | **本目录**（`SKILL.md` + `references/generic/` + `pitfalls.md`） | ✅ 能 | ✅ 能（Vivado/Verilog 层面的经验） |
| **② 领域** | `project/` | ⚠️ 同类题能（流式图像/单目视觉） | ✅ 能 |
| **③ 项目** | 本仓库 `src/` `sim/` `build/` | ❌ 不能 | ❌ 不能 |

**`references/generic/` 这 11 篇 + `pitfalls.md` 是通用加分的主体** —— 它们讲的是
"流式握手怎么写才不死锁""怎么设计判据才能抓住真 bug""怎么量数据才不被骗"
"怎么用机械闸防止配置漂移"，**和"做图像校正"没有任何关系**。

> ⭐ **2026-10-03 拆分**：原来通用层和领域层混在一个 `SKILL.md` 里，
> **触发词里同时有"流式握手"和图像校正内容 ⇒ 一眼看过去就是"某个项目的 skill"**，加分点被稀释。
> 现在**分成两个 skill**：`SKILL.md`（通用，**全文不提图像校正**）+ `project/SKILL.md`（领域）。
> **两者单向依赖**（领域引用通用，不复制）。

---

## 四、每一项的来源与验证（"提炼过程"）

竞赛规则要求说明"从哪些失败或观察中总结、如何验证有效、边界如何确定"。逐项列在各自的
文件里，这里给一张总表：

| 项 | 从哪些失败总结 | 怎么验证有效 |
|---|---|---|
| `01-stream-handshake` | 上板输出**整体错位一格**、**下半个图拖影**、**DMA 永久挂起** 3 次 | 每次都在仿真里**复现**（构造必然触发的 TB），修复后回归 |
| `02-verilog-and-synthesis` | 综合 WNS -6.878 ns、多驱动网、乘法静默截断 | 综合报告 + 逐位比对 |
| `03-vivado-toolchain` | 工程重建脚本在队友机器上失败、top 被自动改写 | 从零跑一遍完整构建 |
| `04-axi-dma-and-bd` | `validate_bd_design` 返回 0 但 DMA 没地址；`transfer length 0?` | 上板实测 + 地址自查脚本 |
| `05-verification-method` | 3 个 bug **都躲过了全部既有测试** | 用"撤掉修复能否复现"来反向验证判据 |
| `06-ps-pl-and-delivery` | 交付包在队友那边**连坏 4 次** | 每次都在"干净解压"目录里重跑 |
| `domain/01` | 行缓存深度按"倾角"估 → 实测差 30 倍 | 离线测量脚本 + 上板死锁复现 |
| `domain/02` | 同一张纸 4 个角度算出 4 个长宽比 | 用"同一目标离散度"当判据 |

> **共同点：每一条都是"先出问题 → 复现 → 定位 → 修 → 加回归用例"**，
> 没有一条是"想出来的最佳实践"。

---

## 五、边界：这个技能包**不能**帮你什么

诚实说明，免得误用：

- ❌ **不含完整的算法实现**（比如"怎么做一个图像校正器"）—— 那是 `src/` 的事
- ❌ **不含 HLS**：本项目的 PL 是手写 Verilog，HLS 相关的坑没有覆盖
- ❌ **不含高速接口**（HDMI/PCIe/以太网）：本队评估过但没做到实操沉淀
  （评估记录在设计报告里，**不随技能包分发**）
- ❌ **不含多板卡/多厂商**：所有经验来自 Xilinx Zynq-7000 + Vivado 2025.2
- ⚠️ **工具链版本敏感**：Vivado 换大版本后，`03` 里的部分报错信息会变

---

## 六、文件命名规范

本仓库所有目录名/文件名使用**纯英文小写**（字母/数字/下划线/连字符），
中文只出现在**文件正文内容**中 —— 这是竞赛的硬性要求。

## 七  本次增补与直接复用

保留原有章节和文件主体，新增下列内容。第三方UI目录与本队提炼案例分别标注，不能把引入目录的规模当成原创或泛化验证。

| 项目 | 适用范围 | 使用方法 | 已验证效果 | 失效条件与来源 |
|---|---|---|---|---|
| [UI技能目录](ui-ux-pro-max/SKILL.md) | 通用UI设计与评审 | 在包根运行下方search命令 | 本包运行查询和目录完整性检查 | 原生渲染需自行适配；第三方MIT，LICENSE随目录保留 |
| [嵌入式触摸UI](references/generic/11-embedded-touch-ui.md) | PYNQ及实时设备界面 | 按步骤建立控件、命中与帧归属 | 声明自检、480P/600P映射用例 | 不检查实际像素/物理触摸；来自坐标偏移与进度卡住等问题 |
| [布局校验器](scripts/check-ui-layout.py) | 任意声明矩形的设备界面 | 下方命令与样例 | 正反例及源坐标用例，结果见examples/validation | 不含旋转/裁剪逆变换，不连接板卡 |
| [融合定位案例](project/references/domain/04-ai-traditional-tracking.md) | 平面目标定位跟踪 | 按候选、验证、跟踪划分 | 对应源码与既有主机回归 | 多书、同色背景仍需实测；来自真实故障 |
| [复核标注流程](project/references/domain/05-human-reviewed-labels.md) | 人工标注与增量训练 | 确认后训练、冻结原标注与评估划分 | 历史训练报告有数据，非本包重跑训练 | 不附训练集/权重，不将训练拟合写成泛化 |
| [持续计划与证据](references/workflow/14-file-planning-and-evidence.md) | 多版本迭代和技术报告 | 基线、约束、检查结果写入持久文件 | 本题交付校验与报告渲染案例 | 流程不保证性能收益；不复制私人聊天记录 |

在**提交包根目录**运行，Python3标准库即可：
```sh
python3 skill/scripts/check-ui-layout.py skill/examples/ui-layout.json
python3 skill/scripts/check-ui-layout.py --selftest
python3 skill/ui-ux-pro-max/scripts/search.py "touch target feedback" --domain ux
python3 skill/ui-ux-pro-max/scripts/search.py "loading progress feedback" --domain ux
```

安装为AI技能时可把skill/作为通用入口、ui-ux-pro-max/作为独立子技能；无需本机原来的用户路径。移植时修改分辨率、字体和目标矩形，重新渲染并上板核实吞吐。新增条目的测试结果见[验证索引](examples/validation/README.md)，格式对应见[AMD核对表](references/submission/amd-requirements.md)。
