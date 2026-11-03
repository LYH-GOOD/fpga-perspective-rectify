# rtl —— PL 核的 RTL 仿真证据

被测对象在 `src/rtl/`：`axis_light27.v`（被测核）+ `tb_light27.sv`（testbench）。
本目录只放仿真日志和契约文档，**日志一个字节都没改**。

| 文件 | 内容 |
|---|---|
| `light27_contract.md` | 被测核的 AXI4-Lite 寄存器 / AXIS 时序契约——testbench 逐条照它验 |
| `logs_v2025_2/` | 仿真日志（Vivado Simulator v2025.2） |

## 结论

```
LIGHT27_PASS pixels=5311 cycles=10085, grayscale/colors/stalls/midpacket/reset/II1
```

覆盖六项：灰度、彩色、反压停顿、包中途参数、复位、II=1（初始间隔 1 拍）。
2026-11-03 用 Vivado 2025.2 从本仓库源码复跑，`LIGHT27_PASS` 行与 `$finish` 时间（121128 ns）逐字相同。

## 被测源码与日志的对应关系（已核对 sha256）

| 文件 | sha256 |
|---|---|
| `src/rtl/axis_light27.v` | `d3d883fa2a78d9a06f809a3d6ed513e2a17e4548db58db9a81f0595cde17a726` |
| `src/rtl/tb_light27.sv` | `c4ffa21ac3a0351a32fc6cff251b2c9161c16b0e1f42862e53ce37fa7fc62653` |

两套日志产生时所用的两份源文件，与仓库 `src/rtl/` 下的对应文件**逐字节相同**（sha256 已比对）。
所以这不是"另一版代码的仿真结果"，就是本仓库这版代码的。

## 怎么重跑

在任意空目录里（`<repo>` 换成仓库根路径）：

```
xvlog -sv <repo>/src/rtl/axis_light27.v <repo>/src/rtl/tb_light27.sv
xelab tb_light27 -s light27_sim
xsim  light27_sim -runall
```

看到 `LIGHT27_PASS ...` 即通过；`$finish` 出现在 `tb_light27.sv` 第 100 行。

⚠️ **`-sv` 不能省。** 不加 `-sv` 时 `tb_light27.sv` 会被当成普通 Verilog 解析，
报 `ERROR: [VRFC 10-4982] syntax error near '''`（第 79 行的 `8'(i)` 是 SystemVerilog 尺寸转换语法），
并连带 `module 'tb_light27' is ignored`。这是**语言模式问题，不是代码问题**。

复现环境：Vivado 2025.2（`F:\vivado\2025.2\`），2026-11-03 本机实测通过。
