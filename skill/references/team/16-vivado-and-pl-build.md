<!--
类型：自有
本文件是 fpga-project-development 自有的规范 —— 既没有上游副本，也不是路由。
素材全部来自本项目 2026-09~11 的真实踩坑记录（memory：vivado-toolchain-layout /
vivado-hostname-nonascii-crash / vivado-ooc-parallel-tclapp-race / vivado-bd-pin-query-semantics /
vivado-bd-ooc-stale-dcp / vivado-try-picture-project-series / hls-csim-cwd-and-stale-gate-traps /
pynq-hwh-requirements 等），以及 vivado-mcp 官方服务端自带的用法约束。

⚠️ 2026-11-01 按竞赛 §3.3.5.2 改写：每条补「失效条件」，全文按
「陌生队伍能不能直接用」重写。合并进队级 skill/ 时，本文件按下方分层表拆进 generic/。
-->

# Vivado 与 PL 构建

## 为什么有这一份

**这是本项目的主干 —— 却一直是 skill 里唯一没有家的部分。**
2026-11-01 盘点：26 条 memory 在讲 Vivado / HLS / BD / 交付，`references/` 里 **0 条**；
`SKILL.md` 只有 3 行工具链路径。每次建工程、改 BD、出 bit，能依靠的只有「我还记不记得」。
这份文件就是把那 26 条收成一份**照着做就不会重踩**的东西。

## 每一项的四元组

| 项 | 类型 | 适用范围（什么时候读） | 已验证的效果 | 失效条件 |
|---|---|---|---|---|
| 一、vivado-mcp 用法 | **通用** | 用 vivado-mcp 驱动 Vivado 时 | 本队 2026-10 起的全部构建都走它，全程未再出现「launch 完没 wait 就以为在跑」 | MCP 换成非官方 Go 版（旧 Python 版工具名完全不同）；不用 MCP 而直接跑 `vivado -mode batch` |
| 二、V 组 工具链与环境 | **通用**（V5 绑 Xilinx 板卡） | 在 Windows 上建/跑 Vivado 工程之前 | 主机名改 ASCII 后，原本 100% 崩的综合变成 0 崩 | Linux 主机（见 V2）；Vivado 2024 及以前（路径与版本号不同） |
| 三、P 组 工程与复制 | **通用** | 复制/改名一个已有 Vivado 工程时 | 改名后的工程一次构建通过，产物与日志未被污染 | 工程从未构建过（没有产物目录可分类） |
| 四、B 组 BD 与 Tcl | **通用** | 写 BD 自查脚本、或查某个脚连没连之前 | 自查脚本假阳性从 76 条降到 0 | 用图形界面手工连线（不写 Tcl 自查） |
| 五、L 组 HLS | **通用** | 写或改 HLS 核、跑 csim/csynth 时 | 四条硬约束全部踩过一次并修好；csim 反空转判据已证明能判红 | 不用 HLS、手写 Verilog；或改用 Vitis 统一 IDE 流程（cfg 写法不同） |
| 六、D 组 交付到 PYNQ | **通用**（D4 用本工程举例） | 把 `.bit`/`.hwh` 交给 PYNQ 之前 | 改名 + 按 `.hwh` 查地址后，`Overlay()` 一次成功 | 不用 PYNQ（裸机/其它 SoC）；PYNQ 4.x 若改解析器（未验证） |
| 七、Q 组 构建正确性 | **通用** | 每次出 bit 之后、说「构建好了」之前 | **抓到过一次「16:43 的 bit 里是 13:58 的旧逻辑、构建全程报成功」** | 纯仿真、不出 bit 的流程 |

> **换题换板能不能用**：一、三、七 换任何 Vivado 项目都能用；二、四、五、六 换到**任意 Zynq/PYNQ 项目**都能用，换到非 Xilinx 平台不适用。
> **本文件不含**：本队的平面校正算法、四角点检测、HDMI 链路 —— 那些在领域层。

## 什么时候用

- 要**建 / 复制 / 改名**一个 Vivado 工程
- 要用 **vivado-mcp** 驱动 Vivado（跑 Tcl、看状态、看日志）
- 要**改 Block Design**、写 BD 自查
- 要**写或改 HLS 核**
- 要**综合 / 布线 / 出比特流**
- 要**交付到 PYNQ**（`.bit` + `.hwh` + PS 侧）

---

## 一、vivado-mcp 怎么用（官方 Go 版，2026-10-05 起）

| 规矩 | 细节 |
|---|---|
| **`session_id` 是必填的** | 除 `vivado_list_sessions` / `vivado_start` 外，所有会话类工具都要带它 |
| **默认 TCL 模式** | 不给 `gui_mode` 就是 Tcl；GUI 只在明确要图形界面时才开 |
| **一个会话一次只能跑一条** | Tcl 是单线程。批量 setup 命令用 `;` 串成一次调用，能少几次往返 |
| **下列命令必须单独一次调用** | `synth_design` `place_design` `route_design` `opt_design` `phys_opt_design` `write_bitstream`；`launch_runs` `wait_on_run` `reset_runs`；`open_project` `close_project` `open_checkpoint` `read_checkpoint` `source`；`start_gui` `stop_gui` —— 服务端钩子要求它们出现在字符串最前面 |
| **`launch_runs` 必须配 `wait_on_run`** | 只 launch 不 wait ⇒ 你以为在跑，其实早退出了 |
| **长命令会返回 `status: running`** | 这不是失败，是移交。接着 `vivado_status` 轮询，不要当报错重发一遍 |
| **看状态用对 action** | 进度 `action="runs"`（30–60 秒轮一次）；卡死排查 `action="health"`；单个 run 卡了 `action="reset_run"`（要带 `run_name`） |
| **解析日志用 `vivado_log_messages`** | 别自己 grep 几 MB 的 `runme.log` |
| ⛔ **旧 Python 版的工具名已消失** | `run_tcl` / `xdc_lint` / `parse_xpr` 在 2026.10 之后**不存在**。见到旧笔记写这些名字，是过期资料 |

**常驻守护**：注册串里带 `--stdio-bridge` ⇒ 服务端常驻 `127.0.0.1:18090`，跨客户端存活。
要全杀干净用 `--kill-all`。会话存档在 `C:\Users\ROG\.vivado-ai\data\session_store_<主机名>.json`。

**改 `.claude.json` 的 MCP 段 ⇒ 必须重启 Claude Code 才换工具集**（本会话不生效）。

**失效条件**：这套写法只对 **2026-10-05 之后的官方 Go 版**成立。旧 Python 版（`F:\vivado\tools\vivado-mcp\`，已从注册表摘掉但未删）的工具名、参数、session 机制全部不同。

---

## 二、V 组：工具链与环境

| # | 规矩 | 失效条件 | 为什么（来源 + 已验证效果） |
|---|---|---|---|
| V1 | **一律 Vivado / Vitis 2026.1**：`F:\vivado\2026.1\` | 换 Linux、换非 PYNQ 板卡时本条不适用；2025.2 之外版本的行为未验证 | ⛔ **不要推荐 2025.2**。2026-09-26 用户实测发现 2025.2 与 PYNQ 不兼容，为此**卸载重装 2026.1**。（具体症状未记录，**别编**。）「IP 与 Vivado 同版本对齐」这类一般常识已被这条实测推翻 |
| V2 | **主机名必须是纯 ASCII，判据是「三种编码长度相等」** | **只在 Windows 成立**；Linux 主机名不走这条路径（未验证） | 本机曾名「怡宝矿泉水」：宽字符 10 / UTF-8 15 / ANSI 10。`synth_design` 按一种长度分配、按另一种拷贝 ⇒ 堆越界，退出码 `0xC0000374`，**100% 崩**。改名 `liheng` 后三处都是 6，**综合从必崩变成 0 崩** |
| V3 | **2026.1 目录对普通用户只读** ⇒ 写操作要 UAC；**提权进程的 stdout 拿不到** | Vivado 装在用户可写目录（如 D 盘自选路径）；以管理员常驻的会话 | 必须 `Start-Process -Verb RunAs -Wait -WindowStyle Hidden` 把输出写进 log 再读回 |
| V4 | **`Vivado\data` 是符号链接**，真身只有一份 | 离线包解压安装可能不是符号链接 —— 先 `dir /AL` 确认再动手 | 往 `Vivado\data\` 写 = 往 `data\` 写，**只写一次**，不要以为要写两处 |
| V5 | **板卡文件位置固定**：`F:\vivado\<ver>\data\xhub\boards\XilinxBoardStore\boards\Xilinx\<board>\A.0\`（`board.xml` `part0_pins.xml` `preset.xml`） | Vivado 2024 及以前路径不同；非 Xilinx 板卡不适用 | PYNQ-Z2 的 `board_part = tul.com.tw:pynq-z2:part0:1.0`，`part = xc7z020clg400-1`。2026.1 商店里**本来就有** pynq-z2，别再说「被删了」 |
| V6 | **已被实验排除的，别再回头查**：Vivado 版本 / 工程路径长度 / 路径含中文 / 器件库 / 并行旋钮（`general.maxThreads`、`synth.maxThreads`、`synth.maxClusterJobsRunCount`）/ 覆写 `COMPUTERNAME`（Vivado 走 `GetComputerNameW()`，环境变量盖不住）/ `nimdnsNSP.dll` / `-notrace` / VC++ 运行库 / 杀毒 / 注入 DLL | 升级 Vivado 大版本后部分假设需重新验证 | 这一整轮十几个假设都是白跑的。**判据只有 V2 那一条** |
| V7 | **定位手段：二分切三段** | 基本无（这是通用手法） | `H1 只启动` → 0；`H2 加 read_verilog` → 0；`H3 加 synth_design` → 必崩。⇒「启动干净、读文件干净、故障只在 synthesize 内部」，范围立刻缩小一个数量级 |
| V8 | **并发 OOC 综合会撞 `tclapp` 竞态**，修法是**串行重试**，不是重建工程 | **只在 Windows**（根源是 `%APPDATA%` 路径）；`-jobs 1` 时不触发 | 症状：`create_project -in_memory` 报 `Could not open 'C' for writing`（那个 `'C'` 是乱码，别追它），或日志停住**无声死亡**。根因：每个子进程都在重写 `%APPDATA%\Xilinx\Vivado\tclapp\manifest.tcl`。修法：`reset_run <失败的 ooc>` + `launch_runs <ooc> -jobs 1`；**先 `reset_run synth_1` 再 launch**（否则报 `17-69`）。日常 `-jobs ≤ 2`。**实测 2/2 恢复**。缓解旋钮 `XILINX_LOCAL_USER_DATA=no` **尚未实测** |
| V9 | **批量跑 `report_timing_summary` 前先 `set_param general.maxThreads 1`** | 大设计上单线程会明显变慢；仅在「默认线程下不崩」的机器上无必要 | 2026-11-01 实测（对真 routed DCP `system_wrapper_routed.dcp`）：默认线程下 `open_checkpoint` **正常完成**，随后 `report_timing_summary` 一开始就崩 —— 退出码 `0xC0000374`（又是堆损坏），日志**恰好停在** `INFO: [Timing 38-191] Multithreading enabled for timing update using a maximum of 2 CPUs`，之后再无任何输出。同一条 Tcl **只加 `set_param general.maxThreads 1`** 就正常出 95 KB 报告（13 s）。⚠️ **两臂各跑一次、死点逐字相同**，但**根因未查**（V2 那条主机名原因不适用，本机主机名已是 ASCII `LIHENG`）。⚠️ **V6 里「`general.maxThreads` 已排除」只针对 `synth_design`，不要外推到本条**。另：`.bat` 包装层有时把崩溃吞成退出码 0 ⇒ **别拿退出码当判据，要看报告在不在、能不能解析** |

---

## 三、P 组：工程与复制

| # | 规矩 | 失效条件 | 为什么（来源 + 已验证效果） |
|---|---|---|---|
| P1 | **复制改名绝不能全目录文本替换** | 工程从未构建过（没有产物目录，无需分类） | 三类文件待遇完全不同：**源文件**（`.xpr .bd .xci .xdc .tcl .bat .py .ipynb`）必须改；**构建产物**（`.runs/ .gen/ .cache/ .hw/ .sim/ .ip_user_files/`）绝不碰；**历史日志**（`runme.log` `vivado.jou` `.vds` `.vdi` `flow.out`）绝不碰 —— 改了就是伪造历史。现成工具：`tools\rename_vivado_project.py <dir> <old> <new>`。**验证：改名后工程一次构建通过** |
| P2 | **`.xpr` 里只有工程自己那行 `Path=` 是绝对路径** | 有人手工编辑过 `.xpr`（可能引入了硬编码） | 源文件走 `$PSRCDIR` / `$PGENDIR` 宏；run 目录**没有硬编码路径**（Vivado 按 `<工程名>.runs/<run名>` 自己推导）。别做多余的替换 |
| P3 | **改 `.xci` 的 `gen_directory` 会产生 5 条 `IP_Flow 19-12246` 警告 —— 这是预期代价** | 改用 IP 大版本整体重生成（`.xci` 被重写）时不适用 | 不改反而更糟：会指向副本里不存在的旧 `.gen`，Vivado 就在新工程里创建**旧名字**的目录 |
| P4 | **`get_property IP_STATUS` 不存在**（`Vivado 12-1341`） | 未来版本可能新增该属性 | 查 run 状态用 `get_property STATUS [get_runs]` |
| P5 | **`.xpr` 是单行文件** ⇒ `grep -c` 报的是**行数**不是匹配数 | Vivado 改格式后可能变成多行 | 权威数字只能用 `data.count()`。这是「统计口径」的老坑，见 [15](15-measurement-and-comparison.md) M12。**实测：真实 2 处，`grep -c` 报 1** |

---

## 四、B 组：Block Design 与 Tcl 查询语义

> 这一组全部是 Vivado 2026.1 batch Tcl 实测。**旧自查脚本 76 个假阳性就是因为不懂 B1–B3**；按 B5 改写后降到 **0**。

| # | 规矩 | 失效条件 | 为什么（来源 + 已验证效果） |
|---|---|---|---|
| B1 | **裸名只对顶层 cell 有效；`*` 不跨 `/`** | 基本无 | P1 HDMI 链整包在一个层次壳 `video` 里 ⇒ 真路径 `video/axi_vdma_disp`。`get_bd_cells -quiet axi_vdma_disp` 返回**空**；`get_bd_cells -quiet`（**不带任何 pattern**）才列出全层次（~35 个，vs 顶层的 12 个）。写自查前先问一句「这个 cell 在层次里吗」 |
| B2 | **成员脚查 net 是死路** | Vivado 若修复该缺陷则可查（未发生） | 连着的接口成员脚（如 `s_axi_lite_awaddr`）：`get_bd_nets` 和 `get_bd_intf_nets` **都返回空**。正确查法二选一：①接口脚级 `get_bd_intf_nets -of_objects <S_AXI_LITE>`；②成员枚举 `get_bd_pins -of_objects <S_AXI_LITE>`。**标量脚**的 `get_bd_nets -of_objects` 是可靠的 |
| B3 | **`get_property IS_CONNECTED` 废** | 同上 | 2113 个 pin **全返回空串**。别拿它当判据 |
| B4 | **有合法悬空，别一刀切** | **VDMA 的 `fsync` 不为 0 时必须有连接**，此时白名单不成立 | 板上验过的 P1：`video/axi_vdma_disp/mm2s_frame_ptr_in`（dir=I）**就是悬空的**。`fsync=0` 时 `*_frame_ptr_in` 悬空合法 ⇒ 白名单放行。**该 bit 实测 55.3 fps 正常出图** |
| B5 | **自查谓词要分方向** | 成员接在自定义 IP 的非常规脚上时需人工确认 | 接口脚**有** intf net ⇒ 跳过；**没有** ⇒ 回退查成员：**I 无 net → FAIL、IO 无 net → WARN、O 跳过**。实测：接口脚无 intf net 但成员已接 = 合法（`validate_bd_design` 返回 `VALIDATE_OK`） |
| B6 | **IP 的成员脚数量/方向要现查，别记** | IP 配置不同则成员不同（如 `C_ALL_OUTPUTS=0`） | `C_ALL_OUTPUTS=1` 的 GPIO 只剩 `gpio_io_o` / `gpio2_io_o`（均 dir=O），`gpio_io`/`gpio2_io`/`gpio_io_t` **NOT_FOUND**（旧笔记「gpio_io 是 IO 向」**已证伪**）。IIC 成员 6 个：`scl_i`(I) `scl_o`(O) `scl_t`(O) `sda_i`(I) `sda_o`(O) `sda_t`(O) |
| B7 | **`save_project` 不存在** | GUI 里手动保存不受影响 | `info commands save_project*` 只有 `save_project_as`（= **另存为新工程**，不能原地保存）。**batch 下 `close_project` 就是保存退出**，异常退出 Vivado 也会自动保存。⇒ 跨会话落盘：流程末尾 `close_project` 或让它自然退出，别再写 `save_project` |
| B8 | **改 BD module reference 的 RTL 后，`reset_run synth_1` 不会重置它的 OOC 子 run** | BD 自身有改动时 `create_bd` 会重建，不触发 | 跳过 `create_bd` 时，synth 直接读 IP 目录下**旧的** `.dcp` ⇒ 出的是旧逻辑。构建脚本里要显式 `reset_run <模块名>_synth_1`，并加 Q1 的门禁。**实测抓到过一次**（见 Q1） |

---

## 五、L 组：HLS

| # | 规矩 | 失效条件 | 为什么（来源 + 已验证效果） |
|---|---|---|---|
| L1 | **工程路径必须纯 ASCII** | **只在 Windows 上踩过**；Linux 下是否同样失败未验证（大概率不会） | 中文路径下 `v++ -c --mode hls` 直接挂：`set_msg_logfile` 失败 + protobuf 报 `invalid UTF-8`。本项目的 `_refs\`、`_pynq_pl\` 就是为此保持纯 ASCII |
| L2 | **源文件不接受位置参数，必须写 `hls_config.cfg`** | Vitis 统一 IDE 流程里 cfg 写法不同 | 见下方模板。跑法：`v++.bat -c --mode hls --config <cfg> --work_dir <dir> --part xc7z020clg400-1`。**已实测跑通 `v++ v2026.1`** |
| L3 | **`m_axi` 指针必须额外补一条 `s_axilite` 声明** | 核里不用 `m_axi` 时不涉及 | 少那一行就多开一个 `s_axi_control_r`，板上变成两个基地址。**2026-09-27 A/B 实测：A 组有该接口、加行后消失** |
| L4 | **csim 的 cwd 猜不准 —— 不要猜** | 换 Vitis 版本后可能修正（未验证） | `vitis-run --mode hls --csim` 打印 `Changing directory to <...>`，但 tb 真跑的 cwd **既不是脚本目录也不是那行说的目录**（把 `in.bin` 放过去照样 `cannot open`）。⇒ 让 tb 读**环境变量**拿绝对路径，`subprocess.run(env=...)` 直接给 |
| L5 | **反空转判据要指定「失败原因」** | 无（这是通用手法） | 第一版判据是「输出里有 `TB_FAIL`」，而两个方向都是 `TB_FAIL cannot open in.bin` ⇒ **空转门自己绿了**。改成：必须 `bad=N>0` **且**输出里**不含** `cannot open`。**已证明能判红** |
| L6 | **解析 EDA 报告前先 `head` 一眼真实格式** | 换 Vitis 版本后报告名/列宽可能变 | 顶层报告是 `<top>_csynth.rpt`，**不是**汇总版 `csynth.rpt`；两版列宽不同，第一版正则四个数字全解析失败。⇒ 判据：**解析不到 / 全 0 都判红** |

```ini
part=xc7z020clg400-1
[hls]
clock=100MHz
flow_target=vivado
syn.file=<kernel>.cpp
syn.top=<kernel>
```

```c
#pragma HLS INTERFACE m_axi     port = p bundle = gmem depth = ...
#pragma HLS INTERFACE s_axilite port = p bundle = control   // ← 少这行就出双接口
```

---

## 六、D 组：交付到 PYNQ

| # | 规矩 | 失效条件 | 为什么（来源 + 已验证效果） |
|---|---|---|---|
| D1 | **`.hwh` 必须是 XML** | PYNQ 若换解析器（当前 3.1.1 用 ElementTree） | PYNQ 用 `ElementTree.parse` 读（`pynq/pl_server/hwh_parser.py`）。**不要去转 JSON** —— 曾差点因为「新版只认 JSON」这个错误假设把对的改错 |
| D2 | **`.hwh` 必须与 `.bit` 同名** | 无 | `get_hwh_name()` = `os.path.splitext(bitfile)[0] + ".hwh"`。Vivado 默认产 `system.hwh` ⇒ **上传前改名**。**改名后 `Overlay()` 一次成功** |
| D3 | **BOM 无害，别为它改文件** | 若用非 UTF-8 编码打开则另说 | Vivado 产的 `.hwh` 带 UTF-8 BOM，PYNQ 走 `read_text('utf-8')` 再 `ET.fromstring()`，本机复现整条路径实测**照样解析成功** |
| D4 | **基地址从 `.hwh` 现查，不照抄别人的** | 无（永远要现查） | `<MEMRANGE BASEVALUE="0x...">`。**示例：本工程是 `0x40000000`，不是到处抄来的 `0x43C00000`** —— 你的工程以自己 `.hwh` 里那个为准。⚠️ `FULLNAME` 里的实例名 **≠** OOC run 目录名（`axi_gpio_0` vs `system_axi_gpio_0_0_synth_1`） |
| D5 | **HLS 核的地址寄存器 `register_map` 写不了** | **非 HLS 生成的 IP**（AXI GPIO 等）不受影响，可直接用 `register_map` | `mask_1/_2`、`out_r_1/_2`、`w`、`h` 在 `register_map` 里**全是 write-only**（2026-09-27 板上实测）⇒ 写地址一律按字节偏移 `ip.mmio.write`；**64 位地址必须分两次写低/高 32 位**（`register_map` 不会合并成 64 位属性）。`register_map` 仍可用于**读** |

---

## 七、Q 组：构建正确性（别被「构建成功」骗）

| # | 规矩 | 失效条件 | 为什么（来源 + 已验证效果） |
|---|---|---|---|
| Q1 | **三道门，缺一不可**：① OOC 那个 `.dcp` 的 mtime **≥ 本次构建开始**；② 布线后网表里找得到**只有新版才有的单元**（如 `c_href_g_reg`）；③ 反面指纹为 0（如 `*d_iob_reg*` 单元数为 0、且引脚网直接挂在消费者 `xxx_reg[*]/D` 上 ⇒ 移位/滤波链根本没进网表） | 纯仿真、不出 bit 的流程 | **2026-10-21 实测：16:43 出的 bit 里是 13:58 的旧逻辑，而构建全程报成功。** 三道门全部实现后，同类问题当场判红 |
| Q2 | **WNS/TNS 判据必须能判红** | 无 | 正则写错就会「永远通过」。**2026-10-22 一天抓到两个空转门**（TB 的 C4/C5、构建的 WNS regexp）。先制造一次失败再相信它 |
| Q3 | **每次交付记 sha16，上板前逐文件核对** | 无 | `.bit` / `.hwh` / 交付包都记。别手抄 —— 用脚本比。**本队 `_board_vs_pkg.py` 因此抓出过一次「包内 sha ≠ 源 sha」** |
| Q4 | **「重跑结果 == 交付件」要写清哪几个字节允许不同** | Vivado 版本不同，日期串长度可能不同 | 本项目实测重建与交付只差 **5 字节**（构建日期）。不写清楚判别口径，每次都判红，最后就会被无视 |
| Q5 | **跳 `create_bd` 时 `reset_run synth_1` 不往下传** | BD 有改动时不触发 | 与 B8 同一件事的判据面：只看 `synth_1` 的 STATUS 会漏掉 OOC 子 run |

---

## 八、从零到能上板：顺序

1. **确认 V1 + V2**（2026.1；主机名三种编码长度相等）—— 这两条不成立，后面全是白干
2. **板卡文件在位**（V5）
3. **建工程或复制改名**（P1–P2，用 `rename_vivado_project.py`）
4. **HLS 核先单独跑通 csim**（L1–L6），再进 BD
5. **写 BD，跑悬空自查**（B1–B6），`validate_bd_design` 必须 `VALIDATE_OK`
6. **综合/布线**：`-jobs ≤ 2`；失败先串行重试（V8），别重建工程
7. **过 Q1 三道门** —— 不过就当没构建
8. **交付**：`.hwh` 改名（D2）+ 记 sha16（Q3）+ 上板前逐文件核对

> **一句话**：这个项目里「Vivado 报成功」和「bit 是新的」是两件事，「`.hwh` 在」和「PYNQ 认得出」也是两件事。
> 每一对之间都要有一道**能判红**的门。
