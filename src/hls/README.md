# hls —— 三个 HLS 核的 C++ 源码

设计里用到三个 HLS 核，交付时以**打包好的 IP** 形式放在
[`build/vivado/ip_repo/`](../../build/vivado/ip_repo/)（含 `hdl/` 与 `component.xml`）。
本目录存放它们的 C++ 源，供核对与重建。

## 对应关系

| 源 | 打包 IP | 配置里的 `clock` | 说明 |
|---|---|---|---|
| `axis_sharp/axis_sharp.cpp` | `xilinx_com_hls_axis_sharp_1_0` | 100 MHz | 锐化；`tb_axis_sharp.cpp` 是 C 仿真测试台 |
| `color_convert/color_convert.cpp` | `xilinx_com_hls_color_convert_1_0` | 7 ns | RGB ↔ 色彩空间转换；带 `.hpp` |
| `pixel_unpack/pixel_unpack.cpp` | `xilinx_com_hls_pixel_unpack_1_0` | 7 ns | 像素解包；带 `.hpp` |

**这确实是产出交付 IP 的那份源。** `ip_repo/` 里的三个 IP 就是用这里的源码与配置生成的，
判据不是"看起来像"，而是逐文件比对的字节级复现（见下一节）。

⚠️ `axis_sharp` 的配置文件原名就是 `hls_config_axis_sharp.cfg`（当时该目录里还有别的工程），
未改名，以免与历史记录对不上。另两个是 `hls_config.cfg`。

## 怎么重建

每个配置里已有 `part` / `[hls] clock` / `flow_target` / `syn.file` / `syn.top`，
按下面跑即可（Vitis 2025.2）：

```
F:\vivado\2025.2\Vitis\bin\v++.bat -c --mode hls --config <cfg> --work_dir <dir> --part xc7z020clg400-1
```

- **工程路径必须纯 ASCII**：中文路径下 `v++ -c --mode hls` 会直接失败
  （`set_msg_logfile` 失败 + protobuf 报 `invalid UTF-8`）。
- `--work_dir` 指向一个空目录，跑完在 `<work_dir>/hls/impl/ip/` 出 `component.xml` 与 `hdl/`。

**2026-11-03 实测（Vitis 2025.2，从本目录跑了两遍）**：

| 核 | 重跑出的 `hdl/` 与 `ip_repo/` 逐字节比对 | 单次耗时 |
|---|---|---|
| `axis_sharp` | **34/34 相同** | 40 s |
| `color_convert` | **14/14 相同** | 46 s |
| `pixel_unpack` | **25/25 相同** | 36 s |

`component.xml` 除两行生成信息（`coreRevision`、`coreCreationDateTime`）外逐字节相同 ——
第二次重跑与第一次只差这两行。⇒ 本目录的源能**原样重建**出 `ip_repo/` 里的三个 IP。
