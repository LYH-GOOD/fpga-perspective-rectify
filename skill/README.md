# FPGA 项目开发技能包 · 人类阅读导航

> **给 AI 智能体看的入口是 [`SKILL.md`](SKILL.md)**（带路由表与触发条件）。
> **本文件是给人看的导航页** —— 两边索引一致，只是详略和受众不同。
>
> 从「FPGA 平面图像自适应校正」这个题目的**真实开发过程**中沉淀的可复用经验。
>
> **评价标准是可复用性** —— 一支陌生队伍拿到这个目录，能不能直接用在自己的题目上。
> 所以每一项都写明：**适用范围 / 使用方法 / 已验证的效果 / 失效条件 / 来源**。

---

## 一、先看这里：这个东西对你有什么用

**它不是 FPGA 教程，也不是本队的算法实现。** 它是**做 FPGA 项目时那些会反复踩的坑**，
以及**能自动查出问题的脚本和方法**。

三类人可以直接拿去用：

| 你是 | 直接看 |
|---|---|
| 刚拿到板子，要建第一条上板通路 | [16](references/16-vivado-and-pl-build.md) 的 V/P 组 + [L 组](references/16-vivado-and-pl-build.md) |
| 综合通过了，但上板结果不对 | [19](references/19-pynq-runtime.md) 的第四节（出错定位表）+ [16](references/16-vivado-and-pl-build.md) 的 Q 组（构建三道门）+ [14](references/14-coding-pitfalls.md) 的 I 组（根本没跑） |
| 要报「快了 N%」，或要做 A/B | [15](references/15-measurement-and-comparison.md)，12 条规矩 |
| 要让大模型帮你干某类活 | [17](references/17-prompt-workflows.md)，5 个专项模板 |

---

## 二、每一项的四元组

### 通用层 —— 换题换板仍可用（这是「通用 PYNQ Skill」加分的主体）

| 项 | 类型 | 适用范围 | 使用方法 | 已验证的效果 | 失效条件 |
|---|---|---|---|---|---|
| [15-measurement-and-comparison](references/15-measurement-and-comparison.md) | **方法论** | 任何**拿数据做决策**的项目 | 报数前 / 做 A/B 前读 | 同一天四个矛盾帧率收敛成一个口径 | 日志里没有累计计数器 |
| [16-vivado-and-pl-build](references/16-vivado-and-pl-build.md) | **踩坑+方法** | 任何 Vivado / Zynq / PYNQ 项目 | 建工程、改 BD、写 HLS、出 bit 前对照 | 抓到过「bit 里是旧逻辑而构建报成功」；自查假阳性 76→0 | 换非 Xilinx 平台；Linux 下部分条目不适用 |
| [19-pynq-runtime](references/19-pynq-runtime.md) | **踩坑+范式** | 任何把 bit 拿到板上跑的 PYNQ / Zynq 项目 | 加载 bit、读写 HLS 寄存器、上 DMA 之前对照 | 从 `.hwh` 直接判出 write-only 寄存器；把「段错误」定位到失控的 VDMA | 非 Xilinx 平台；用中断而非轮询；Scatter-Gather |
| [17-prompt-workflows](references/17-prompt-workflows.md) | **提示词工作流** | 用大模型做 FPGA 工程 | 5 个模板直接替换 `<>` | 打开一个从没被执行过的开关，省 76.75 ms/帧 | 模板 3 需要缺陷能被人为制造 |
| [18-case-templates](references/18-case-templates.md) | **案例模板** | 任何 Vivado / HLS 项目起步、或要交结果给别人 | 换 `<>` 直接用；6 个模板 | 本队四代工程都按同一骨架；构建 Tcl 的 `PROGRESS` 门禁当场拦下过没跑完的综合 | 纯软件项目；GUI 手工构建 |
| [14-coding-pitfalls](references/14-coding-pitfalls.md) 的 **A–F / H / I 组** | **踩坑清单** | 任何 Python 脚本 / 工程脚本 | 写码前扫一遍清单 | 报告脚本不再「一个字节都不出」 | G 组和 17 个案例是领域层，见下 |
| [`scripts/preflight.py`](scripts/preflight.py) | **校验脚本** | 任何 Windows 上的 Python / `.bat` | `python scripts/preflight.py <文件或目录>` | 首版 448 条误报 ⇒ 修正后归零；首跑就查出两个真 bug | 纯 Linux 环境；只管 `.py` / `.bat` |
| [`scripts/check-timing.py`](scripts/check-timing.py) | **校验脚本** | 任何 Vivado 项目出 bit 之前 | `python scripts/check-timing.py <报告或目录>`；没有报告时 `--collect --dcp <design.dcp>` 让它自己驱动 Vivado 采 | 真报告 7 条判据全绿、12 个无关报告静默跳过；15 条自检含「负 WNS 必须判红且理由对」「退出码 0 但没报告必须判红」；2026-11-01 对真 routed DCP（`system_wrapper_routed.dcp`，20 MB）`--collect` 端到端 35.7 s，采到 WNS +0.488 / WHS +0.018 / BRAM 80.36%，7 条全绿 | HLS 的 `*_csynth.rpt` 不支持（已明确判红，不静默跳过）；`--collect` 需要本机装了 Vivado，且默认单线程（见 [16](references/16-vivado-and-pl-build.md) V9）；**`--xpr` 路径只验到 Tcl 生成，没对真工程跑过**（`--dcp` 路径已端到端跑通） |
| [`scripts/gen-host-skeleton.py`](scripts/gen-host-skeleton.py) | **代码生成 + 结构审查** | 任何 HLS + PYNQ 项目，进度到「bit 有了，要写主机侧调用」 | `python scripts/gen-host-skeleton.py <system.hwh> [--name N]` | 把 `.hwh` 里机器可判的三件事（write-only 寄存器、64 位要拆两次写、真实基地址）变成生成物里的强约束；11 条自检里 4 条**真的 exec 生成物** | 只认 HLS/BD 导出的 `.hwh`；不覆盖中断、Scatter-Gather |
| [`scripts/check-repro.py`](scripts/check-repro.py) | **校验脚本** | 交付前 / 换机器重建后 | `python scripts/check-repro.py a.bit b.bit [--allow=LO-HI]` | 真 3.86 MB 比特流：一致绿 / 改 1 字节红 / 区间内绿，0.04–0.10 s | 构建本身含真随机时，「逐字节一致」不成立 |
| [`scripts/check-golden.py`](scripts/check-golden.py) | **校验脚本** | 任何「先跑出正确结果、以后每次改动都要确认没改坏」的项目 | `python scripts/check-golden.py --ref <参考目录> --out <产出目录>` | 真 5712×4284 实拍照片：一致绿 / 100 px 不同红 / `--pct-tol=0.001` 放行；11 条自检含「同一个 pct-tol 必须能翻判定」 | 输出本身带随机性（不确定的采样、多线程浮点归约顺序） |
| [`scripts/dma_xfer.py`](scripts/dma_xfer.py) | **运行库（可 import）** | 任何用 AXI DMA 在 PS↔PL 之间搬数据的 PYNQ / Zynq 项目 | `from dma_xfer import DmaXfer`；换算一下 `x = DmaXfer(dma); x.transfer(src, dst)`；裸 numpy 走 `transfer_np(dma, frame)`；`python scripts/dma_xfer.py --selftest` | 把「顺序、超时、失败定位」三件事固化成库：`sync_to_device` → 双向 `transfer` → 等 MM2S 再等 S2MM → 后端 `sync_from_device`，**超时抛 `DmaError` 且绝不跑到后半段的 sync**；报错时直接说清是「错误位 / Halted / 还在跑」哪一类 | 只做 **Simple DMA**（Scatter-Gather、中断、多缓冲环未覆盖）；设备侧 `mmio` 必须是 PYNQ 的 `<dma>.mmio`；⚠️ **这份封装没有单独上板跑过**，只用假对象验过顺序与错误路径 |
| [01-chinese-transparent-workflow](references/01-chinese-transparent-workflow.md) | 流程 | 任何中文项目 | 多步任务开始时读 | 进度可见、不攒着报 | 非中文协作场景 |
| [02-ask-first](references/02-ask-first.md) | 流程 | 任何项目 | 动手前拿不准时读 | 95% 门槛，避免猜着写 | 无 |
| [03-anysearch](references/03-anysearch.md) | 检索 | 任何需要联网核实的项目 | 查资料时读 | **本包唯一被实际读过的 reference（7 次）** | 换检索工具 |
| [08-brainstorming](references/08-brainstorming.md) | 流程 | 需求模糊（「帮我做个 X」） | 先定设计再动手 | 把模糊需求变成定下来的设计 | 需求已经明确 |
| [09-writing-plans](references/09-writing-plans.md) | 流程 | 多步骤实现 | 拆成能照做的任务清单 | — | 一次性小改动 |
| [10-test-driven-development](references/10-test-driven-development.md) | 流程 | 写代码 / 写 RTL | 先红后绿 | — | 探索性脚本 |
| [11-systematic-debugging](references/11-systematic-debugging.md) | 流程 | 出错 / 报错 / 行为不符预期 | 动手改之前读 | 「显而易见的根因有 40% 是错的」 | 无 |
| [12-verification-before-completion](references/12-verification-before-completion.md) | 流程 | 要说「做完了」之前 | 完成前读 | 拦住过多次「自报成功、产物是错的」 | 无 |

### 领域层 —— 同类题能用，换题即失效

| 项 | 类型 | 适用范围 | 使用方法 | 已验证的效果 | 失效条件 |
|---|---|---|---|---|---|
| [14](references/14-coding-pitfalls.md) 的 **G 组**（图像与算法，69 条，分 G-1~G-8） | 踩坑清单 | 阈值 / 掩膜 / 几何 / 光照 | 写任何图像处理代码之前逐组扫一遍；真出错时按 G-4 给的**排障顺序**走，别跳 | 饱和度分离把 **27/27 帧救回、19/19 零伤**；`imencode`+`tofile` 让中文路径读写不再静默失败 | **不做图像的题目完全不适用** |
| [14](references/14-coding-pitfalls.md) 的**第二部分 17 个案例** | 案例 | 想理解某条规矩「为什么存在」时 | 先读规矩、再用案例自查「我是不是正在犯同一个错」 | 案例 1 量出 Otsu 选的 132 与真正需要的 170~190 差着整条边界；案例 9 揭出一条**空判据**（反向验证的靶子选错了） | 换题后案例场景不复现 |
| [13-word-doc-writing](references/13-word-doc-writing.md) | 规范 | 要产出中文 `.docx` | 写 `<文档名>_source.md` → `python tools/render_docx.py <源.md>` | 用户「写得很乱」的根因是直接拼 `add_paragraph`；改走「md 源 → 渲染器」后排版统一 | 换语种 / 换排版规范 |

### 项目层 —— 本包自己的工具（换项目不可移植）

| 项 | 类型 | 适用范围 | 使用方法 | 已验证的效果 | 失效条件 |
|---|---|---|---|---|---|
| [06-sync-protocol](references/06-sync-protocol.md) | 规程 | **只管本包**（副本 / 路由 / 自有三种形态）；别的技能包不适用 | 改了 `references/` 里任何文件之后读 | 11 份 reference 的头部指针一致；`sync-check.sh` 全绿 | 不做副本机制、或上游不可达 |
| [`scripts/make-copy.py`](scripts/make-copy.py) | 工具 | 只对本包 `COPIES` 表里登记的那几份 | 去 `COPIES` 加一条（指纹它自己算），跑 `python scripts/make-copy.py`；`--check` 只校验不写 | 拦下过「684 行抄错 1 行而校验报一致」 | 上游文件改名 / 删除 |
| [`scripts/sync-check.sh`](scripts/sync-check.sh) | 工具 | 只对本包 06 登记的上游 | `bash scripts/sync-check.sh` | 每次打包前跑一遍，`[OK] 全部同步` | 上游不可达 |
| `references/04` / `05` / `07` | — | **已退役**，文件留档不删 | 不用读 | 12,000+ 条消息里 0 次被读过 | 另有 reference 指向它们，删了要连上游一起改 |

---

## 三、通用性分级（这是加分项）

竞赛规则有一条：**「通用 PYNQ Skill 单独加分：不与本队题目绑定，换一个题目、换一块板卡仍然可用」**。

| 层 | 换题还能用吗 | 换板还能用吗 | 含什么 |
|---|---|---|---|
| **① 通用** | ✅ 能 | ✅ 能（Vivado/Verilog 层面） | `15` 测量纪律、`16` 的 V/P/B/L/D/Q、`19` 的 PYNQ 运行时（Overlay/register_map/DMA/出错定位）、`17` 五个模板、`18` 六个模板、`14` 的 A–F/H/I、`preflight.py`、`check-timing.py`、`check-repro.py`、`check-golden.py`、`gen-host-skeleton.py`、`dma_xfer.py` |
| **② 领域** | ⚠️ 同类题能 | ✅ 能 | `14` 的 G 组 + 17 个案例、`13` Word 写作 |
| **③ 项目** | ❌ 不能 | ❌ 不能 | `06` 同步规程、`make-copy.py`、`sync-check.sh` |

> **一句话**：`15` / `17` 和 `16` 的大部分，**换任何 FPGA 项目都能用**；
> 它们约束的是「怎么问、怎么量、怎么构建、怎么交付」，**和「做图像校正」没有任何关系**。

---

## 四、每一项的来源与验证（「提炼过程」）

> **共同点：没有一条是「想出来的最佳实践」。每一条都是「先出问题 → 复现 → 定位 → 修 → 加回归用例」。**

| 项 | 从哪些失败总结 | 怎么验证有效 |
|---|---|---|
| `15` 测量 | 同一天报过 5.85 / 11.9 / 21.25 / 22.7 四个帧率；台架 30.4 ms 而整机边际 66.1 ms | 改用单一累计计数器斜率后，跨版本比较第一次成立 |
| `16` 构建 | 16:43 出的 bit 里是 13:58 的旧逻辑，而构建全程报成功 | 三道门实现后，同类问题当场判红 |
| `16` 工具链 | 主机名非 ASCII ⇒ 综合 100% 崩（`0xC0000374`） | 改名后同一工程 0 崩 |
| `19` 运行时 | ① 地址寄存器没写进去，kernel 照样正常置 `AP_DONE`，四条观测全"正常"、只有输出是垃圾；② 脚本被 `SIGKILL` 后采集 VDMA 还往已释放的物理内存写，症状全指向「Python 环境坏了」；③ 扁平正则扒 `.hwh` 扒出两个寄存器同偏移 | 把判据落到寄存器上：`ACCESS="write-only"` 从 `.hwh` 直接判、`S2MM_SR` 的 Halted 位判 VDMA 还在不在跑、解析结果用「偏移必须单调递增」自检 |
| `17` 划分 | 「mask 前端搬 PL」被排优化第一名，实际只在启动跑 | 把分母写出来后，PL 只占整帧 **1%** |
| `17` 综合报告 | 加宽/提频/压并行三个方向「听起来都对」 | 加宽实测只降 6.55%、端到端 0.33% |
| `17` 判据做红 | 一天抓到两个空转门；`114 passed` 是逐字节相同的假绿 | 每个检查器都做「造缺陷→必须红→撤掉→必须绿」 |
| `14` 写码 | v1~v7 的实战失败记录 | 见各组的「实测」标注 |
| `preflight.py` | 首版 448 条误报（天天喊的检查器会被无视） | `--selftest` 塞 4 个 fixture，要求**零发现** |
| `gen-host-skeleton.py` | 地址寄存器「写了没用」而 kernel 照样置 `AP_DONE`；扁平正则扒 `.hwh` 扒出两个寄存器同偏移（`<FIELD>` 的 `ADDRESS_OFFSET` 是**位号**不是字节偏移）；Windows 路径的 `\U` 把生成物的 docstring 变成非法转义 | 生成物里 `r()` 读 write-only 直接抛、`w_u64()` 先低后高；自检 4 条臂**真的 exec 生成物**——第一版生成的字典漏冒号就是这么抓出来的（只判字符串的臂当时全绿） |
| `check-golden.py` | 本项目的逐张比对把「量不了」算进了分母，通过率被稀释；改版后只看自报、没跟上一版比，v7 自报「失败 0」而 48 帧里 13 帧错 164~176 px | 改成三态 + 分母只算真判过的；`--selftest` 11 条，其中一条专门证明 `--pct-tol` 能翻判定（第一版它是死开关，而自检 10 条全绿） |
| `check-timing.py` | ① 报告里 `WNS -0.031` 被目测当成「基本没问题」放过；② 解析器遇到不认识的行就跳过 ⇒「一个数都没解析到」也报绿；③ 2026-11-01 本机 `report_timing_summary` 在默认多线程下必崩 `0xC0000374` | `--selftest` 15 条臂：负 WNS 判红且**理由必须是 WNS 那一条**、Vivado 退出码 0 但没出报告判红、`dry-run` 报 SKIP 而不是绿；5 次注入缺陷 5/5 判红；真 routed DCP（20 MB）`--collect` 端到端 35.7 s |
| `check-repro.py` | 换机器重建后 bit 不同，分不清是「构建不确定」还是「真改坏了」；而位流里确实有几个字节（用户 ID、构建时间戳）**本来就该不同** | 真 3.86 MB 比特流：一致绿 / 改 1 字节红 / 区间内绿；**没写 `--allow=LO-HI` 一律判红**，逼人先想清楚哪几个字节允许不同，而不是出了差异再补豁免 |
| `18` 案例模板 | 四代工程各自重写一遍目录骨架、构建 Tcl、单文件报告脚本；每次都在同几个地方重犯（`PROGRESS` 门禁没设、`_open_log` 忘了 flush） | 本队四代工程 + 交付给队友的 P1 工程都按同一骨架；构建 Tcl 的 `PROGRESS` 门禁**当场拦下过没跑完的综合** |
| `dma_xfer.py` | ① 忘 `sync_to_device()` / `sync_from_device()` **两端都不报错**，只有结果是错的；② pynq 的 `wait()` **没有超时参数**，DMA 一卡住脚本就永久挂死；③ 采集脚本被 `SIGKILL` 后 VDMA 还在往已释放的物理内存写 | `--selftest` 12 条臂，覆盖调用顺序、超时抛 `DmaError`、**超时后绝不执行 `sync_from_device`**、错误消息带 SR 原值与判读；7 次注入缺陷 7/7 判红。⚠️ **这份封装本身没有单独上板跑过** —— 自检用假对象，验的是顺序与错误定位，不是硬件行为 |

---

## 五、边界：这个技能包**不能**帮你什么

诚实说明，免得误用：

- ❌ **不含本队的算法实现**（四角点检测、几何校正、光照补偿）—— 那是项目代码的事
- ❌ **不含手写 Verilog 的流式握手细节** —— 本队 PL 侧主要用 HLS；手写 Verilog 的经验在**队内另一份技能包**里
- ❌ **不含 HDMI / 高速接口的完整链路**
- ❌ **不含多板卡 / 多厂商** —— 所有经验来自 Xilinx Zynq-7000 + Vivado 2026.1
- ⚠️ **工具链版本敏感**：Vivado 换大版本后，`16` 里的部分报错信息与路径会变
- ⚠️ **`14` 的 G 组换题即失效**，别当成通用算法经验

---

## 六、现状与缺口（截至 2026-11-01，如实写）

| 竞赛要求的四种形态 | 现状 |
|---|---|
| 提示词工作流 | ✅ [17](references/17-prompt-workflows.md)（5 个模板） |
| 踩坑清单 | ✅ [14](references/14-coding-pitfalls.md) + [16](references/16-vivado-and-pl-build.md) |
| 校验脚本 | ✅ 四个，都带 `--selftest`：[`preflight.py`](scripts/preflight.py)（写码机械项）、[`check-timing.py`](scripts/check-timing.py)（资源与时序，含 `--collect` **自动采集**）、[`check-repro.py`](scripts/check-repro.py)（构建可复现性）、[`check-golden.py`](scripts/check-golden.py)（黄金参考比对） |
| 运行时封装 | ✅ 两个，都可 `import` 或直接跑：[`gen-host-skeleton.py`](scripts/gen-host-skeleton.py)（从 `.hwh` 生成主机侧骨架：基地址 / 偏移 / write-only 名单 + `r()`/`w()` 强约束）、[`dma_xfer.py`](scripts/dma_xfer.py)（DMA 搬运与缓存一致性封装，带超时与出错定位）—— 对应加分项第 ② ③ 条 |
| 案例模板 | ✅ [18](references/18-case-templates.md) — 工程骨架 / `.tcl` 构建驱动 / 单文件报告 Python / HLS 核骨架 / 报告格式 / 可复现性校验 |

**其它未完成项：**

- 与队内另一份技能包（手写 Verilog 方向，含 364 条通用踩坑）**尚未合并** —— 合并后本包作其补充，不重复其内容
- **校验脚本第三类补上了**（2026-11-01）：`check-golden.py` = **自动比对黄金参考**，通用、可配置。它**没有**搬本项目的逐张比对 `_eval\verify_photos.py` —— 那份的判据（E 字方度、栅格 RMS）换题即失效；搬过来的是它背后 **4 条纪律**（三态 / 分母只算真判过的 / 缺文件必红 / 非 ASCII 路径走 `np.fromfile`）。
⚠️ 它是一条**比对**脚本，自己不产出图片，所以 `verify_photos.py` 里「存盘后回读复核」那条在这份上**不适用、也没实现**
- **文件名已全部改成纯英文小写**（2026-11-01）—— 规则 3.2.5 / 3.3.5.4 原文要求。
  仅 `README.md` / `SKILL.md` 保持大写：前者是规则 3.3.5.2 亲自点名的文件名，后者是技能包的事实标准。
- `references/01–04`、`07–12` 是从公开 skill 复制来的**副本**，**不是本队沉淀的经验**，不应计入提交包的成果
- ⚠️ **已知偏差**：`01` / `02` / `03` / `04` 四份副本的正文**早已被人工改编**（`skill`→`文件`、删了 graphviz 块、
  改成指向本整合版的链接），与「副本正文一字不改」的规程不符。这是 2026-11-01 打包体检时才量出来的既有状态，
  **本次没有改动它们**（只替换了文件名）。`07`–`12` 六份经逐字比对确认与上游完全一致
