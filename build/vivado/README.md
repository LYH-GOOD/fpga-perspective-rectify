# vivado —— PL 侧的可复现构建源

本目录回答一个问题：**交付的 `system.bit` 是从这些源文件建出来的吗，别人能不能再建一遍？**

`build/` 的其它内容是**软件**构建链（合并、自检、上板）；这里只放 **PL**：
Block Design 源、RTL、IP 仓库、约束。

## 目录

| 路径 | 内容 |
|---|---|
| `rebuild.tcl` | 建工程（**只建目标，不跑流程**） |
| `system_light27.tcl` | Block Design 源，IP Integrator 导出（1400+ 行） |
| `run_build.tcl` | 跑综合 → 实现 → 写位流，导报告与 XSA |
| `contract.md` | AXIS / AXI-Lite 接口契约：保留了什么、新增的一级挂在哪、数据格式怎么走 |
| `ip_repo/` | 7 个自定义 IP（11 MB），每个带 `component.xml` |
| `../../src/rtl/` | 5 个 RTL/约束文件（`rebuild.tcl` 直接引那里，不在此另存一份） |

`ip_repo/` 里的 7 个 IP：

| IP | 作用 |
|---|---|
| `remap_ip` | **重映射核**（本设计的主角，含 `remap_core.v` / `line_buf.v` / `coord_gen.v`） |
| `axi_dynclk_v1_0` | 动态像素时钟 |
| `rgb2dvi_v1_2` | RGB → TMDS/DVI 输出 |
| `color_swap_1.1` | 通道交换 |
| `xilinx_com_hls_axis_sharp_1_0` | HLS 锐化 |
| `xilinx_com_hls_color_convert_1_0` | HLS 色彩转换 |
| `xilinx_com_hls_pixel_unpack_1_0` | HLS 像素解包 |

三个 HLS IP 的 C++ 源与重建配置在 [`src/hls/`](../../src/hls/) —— 2026-11-03 用 Vitis 2025.2
从那里重跑，产物 `hdl/` 与这里的 IP 逐字节相同。

## 怎么跑

```tcl
# 在 build/vivado/ 下，Vivado Tcl 控制台或 -mode batch
source rebuild.tcl      # 建工程 → build/p11_light27.xpr，不启动综合
source run_build.tcl    # 综合 → 实现 → 位流 → 报告 → XSA
```

`rebuild.tcl` 会在 `build/vivado/build/` 建工程，**该目录已存在时直接报错退出**——
这是刻意的：要重来就换个干净的副本目录。

流水线命令（无 GUI）：

```
vivado -mode batch -source rebuild.tcl -nojournal -log rebuild.log
vivado -mode batch -source run_build.tcl -nojournal -log run_build.log
```

## ⚠️ 相对队友原版改了两处（务必知情）

| 改了什么 | 原版 | 本仓库 | 为什么 |
|---|---|---|---|
| BD 版本闸 | `system_light27.tcl` 版本不等就 `return 1` | 改为只告警 | 原写法会在 `source` 处静默结束，BD 一个 cell 不建，直到 `validate_bd_design` 才报错，极难定位 |

另外 RTL 源不再在 `vivado/` 下另存一份，直接指向仓库唯一的 `src/rtl/`
——否则 `axis_light27.v` 会有两份，迟早漂移。

## ★ 一个坑：缺 `digilentinc.com:interface:tmds_rtl:1.0` 的接口定义

**症状**（2026-11-02 实测）：

```
CRITICAL WARNING: [BD 41-52] Could not find the abstraction definition specified by the vlnv:
                  digilentinc.com:interface:tmds_rtl:1.0
CRITICAL WARNING: [BD 41-181] Type specified by the VLNV: 'digilentinc.com:interface:tmds_rtl:1.0',
                  cannot be found. Interface port: 'TMDS_out' cannot be created
ERROR: [BD 5-11] Error: running create_bd_intf_pin, not found intf_pin /video/TMDS_out
```

**根因**：`rgb2dvi_v1_2/component.xml` 只**引用**了 `abstractionType=tmds_rtl`，
接口定义本体（bus definition + abstraction definition）在队友的导出里**丢了**。
`source_sha256.json` 的 398 条清单里也没有它 —— 不是本仓库漏拷，是源头就没有。

**这不是版本问题**：队友原版 `rebuild.tcl` 拿去 **Vivado 2025.2 原样跑，同一个错、同一行**。
也就是说这个脚本**从来没能从零建出工程**，队友的工程来自 `p11_light27_vivado_project_full.zip`。

**修法**：按 Vivado 自带样例补两份 IP-XACT 定义，放在 `ip_repo/rgb2dvi_v1_2/interfaces/`：

| 文件 | 定义 |
|---|---|
| `tmds.xml` | `digilentinc.com:interface:tmds:1.0`（Bus Definition） |
| `tmds_rtl.xml` | `digilentinc.com:interface:tmds_rtl:1.0`（Abstraction Definition，4 个端口） |

端口照 `rgb2dvi_v1_2/src/rgb2dvi.vhd` 的 entity 逐条写：
`TMDS_Clk_p`/`TMDS_Clk_n`（1 位）、`TMDS_Data_p`/`TMDS_Data_n`（3 位），master 侧 direction=out。
元素结构照 Vivado 自带的 `data/ip/xilinx/an_lt_v1_0/interfaces/statistics_ports.xml`
（abstraction 里端口名用 `spirit:logicalName`，不是 `spirit:name`；顺序是
`presence → width → direction`）。

**验收标准**：重建出的 `system_wrapper.v` 端口表必须与参考工程**逐条相同**（26 个端口，含
`hdmi_out_clk_p/n`、`hdmi_out_data_p/n[2:0]`、`hdmi_out_hpd`）。2026-11-02 实测：逐条相同。

## ⛔ 别走这条捷径：直接拿 `.bd` 当源

把工程里的 `system.bd` 抽出来 `add_files` 也能「建成功」，但**是假成功**：

```
WARNING: [BD 41-2671] The dangling interface net <video_TMDS_out> will not be written out to the BD file.
```

它不报错，只是把 `hdmi_out` / `TMDS_out` 两个接口**静默丢掉**，生成的网表缺 HDMI 输出。
端口表会少 6 个 —— 每个 `.bit` 都能写出来，但 HDMI 出不来。
**判据**：看 wrapper 端口数是不是 26，少一个就是这条坑。

## ⚠️ 并发 OOC 综合会撞 tclapp 竞态（2026-11-02 实踩）

`launch_runs synth_1 -jobs 8` 会同时起 38 个 OOC 子 run，其中偶有一两个这样死：

```
ERROR: [Common 17-1257] Failed to create directory 'C'.
ERROR: [Common 17-354] Could not open 'C' for writing.
ERROR: [Common 17-39] 'tclapp::load_apps' failed due to earlier errors.
ERROR: [Common 17-39] 'wait_on_runs' failed due to earlier errors.
```

**不是设计问题、不是 IP 问题**：根因是 `%APPDATA%` 下的 `tclapp\manifest.tcl` 被并发子进程
互相踩。处理办法是**串行重试**，不要重建工程：

```tcl
# 复位出错/取消的 run 和父 run，再 -jobs 1 重跑
reset_run <失败的子 run>; reset_run synth_1; reset_run impl_1
launch_runs synth_1 -jobs 1
```

父 run 也会被标失败，**只复位子 run 是不够的** —— 会直接报
`Run 'synth_1' needs to be reset before launching`。

`NPROC` 环境变量控制并发度（默认 8）：`NPROC=1 vivado -mode batch -source run_build.tcl`。

## 产物与指纹

| 产物 | 路径 |
|---|---|
| 位流 | `build/p11_light27.runs/impl_1/system_wrapper.bit` |
| 报告 | `reports/*.rpt` |
| 硬件平台 | `p11_light27.xsa` |

## 重建验证

交付位流由 **Vivado 2025.2** 建出，综合与实现报告在 [`../reports/`](../reports/)
（LUT 17,569 / FF 24,135 / BRAM 121 / DSP 46 / WNS +0.650 ns，DRC 与布线错误均为 0）。

本目录的脚本与 `system_light27.tcl` 是那个工程的导出源；按上面的两条命令即可重建同一设计。
三个 HLS IP 的源与重建方式见 [`src/hls/README.md`](../../src/hls/README.md)：
用 Vitis 2025.2 重跑，`hdl/` 与 `ip_repo/` 逐字节相同（`component.xml` 除两行生成时间外相同）。

⚠️ 位流**不是逐字节可重现**的：同一份源在不同次实现里布线不同，sha256 必然不同。
能对的是资源与时序档，以及整机行为。

## 已知缺口

- 完整的 Vivado 工程（含 `.runs/impl_1`）142 MB，超出 GitHub 单文件上限，**不入库**。
  本目录的 `system_light27.tcl` + `ip_repo/` + `src/rtl/` 就是它的可复现来源。
- 交付位流 sha256 `aaa9f632d3f8a7a11db14ae36876f0d40fa9d7fa2666d8a4894c2ca14ddef3d0`，
  2026-10-30 23:11 由 Vivado 2025.2 建出。
