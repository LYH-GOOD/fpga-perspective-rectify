# 工程包内容对照

**作品**：基于 FPGA 的实时视频平面自适应校正系统
**赛道**：2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道 · AMD 赛道 · 自主选题 · 初级组
**板卡**：PYNQ-Z2（`xc7z020clg400-1`，board_part `tul.com.tw:pynq-z2:part0:1.0`）
**打包日期**：2026-11-03

目录结构按指南 **3.3.5.4 推荐目录结构**组织（`src/` `sim/` `build/` `board/` `data/` `skill/` `report/`），
目录名与文件名全部为英文小写；中文只出现在文件正文里。

---

## 一、指南 3.3.5.1 的五项要求 → 包内位置

| 要求 | 包内位置 |
|---|---|
| **完整的工程文件与源码**（RTL、HLS、PS 侧软件） | `src/rtl/`（5 个 RTL/约束源）<br>`src/hls/`（三个 HLS 核的 C++ 源 + `hls_config.cfg`）<br>`src/ps/`（PS 侧 Python 软件，114 个模块）<br>`build/vivado/`（**PL 侧完整构建源**：BD 脚本 `system_light27.tcl` + 7 个 IP 的 `ip_repo/` + `rebuild.tcl`/`run_build.tcl`，可按 `build/vivado/README.md` 从零建出同一工程）<br>⚠️ 队友导出的整份 Vivado 工程 zip（142 MB，含 `.runs/`）**未入库** —— 超过 GitHub 单文件上限，且可由上述构建源复现，理由见 `build/vivado/README.md` 末尾「已知缺口」 |
| **仿真或验证结果** | `sim/rtl/`：RTL testbench + `logs_v2025_2/` 的 xsim 日志与通过判据<br>`sim/checks/`：PS 侧对标脚本<br>`sim/results/`：各版本 benchmark / validation 的 JSON 结果<br>`sim/reports/`：检查链输出 |
| **综合与实现报告** | `build/reports/` 下 7 份 `*_impl.rpt`：`utilization`（资源）、`timing`（时序）、`clocks`（时钟）、`drc`、`io`、`power`、`route_status`。全部由 **Vivado 2025.2** 产出 |
| **上板工程、运行脚本、实测输出与参考结果的比对数据** | `board/system.bit` + `board/system.hwh`：交付位流与硬件描述<br>`board/p11_start.ipynb`：板端唯一入口（Jupyter）<br>`board/logs/`：两次连续实测的完整 JSON 行日志<br>`release/p11_fps33_20261101_merged/`：114 文件运行包（含 `release_manifest.json` 逐文件 sha256 锁）<br>`data/`：测试数据与说明<br>`sim/results/`：参考结果 |
| **可复现的构建脚本** | 软件链：`build/build_merged_release.py`（一条命令从 `src/` 重建运行包并跑 10 道自检）<br>PL 链：`build/vivado/rebuild.tcl`（建工程）+ `run_build.tcl`（综合→实现→位流→报告）<br>详见 `README.md` 与 `build/README.md` |

另外两项（指南 3.3.5.2 / 3.3.5.3）：

| 要求 | 包内位置 |
|---|---|
| **技能包** | `skill/`，入口 `skill/README.md`（逐项写明适用范围、使用方法与失效条件） |
| **设计报告** | `report/design_report.pdf`（30 页，含大模型协作记录与复现说明）；迭代记录在 `report/releases/`；ROSS 套件的完整记录在 `report/ross_experience.md`，4.4 节重写稿在 `report/ross_section_4.4.docx` |

---

## 二、关键指纹

| 文件 | 大小 | sha256 |
|---|---|---|
| `board/system.bit` | 4,045,690 B | `aaa9f632d3f8a7a11db14ae36876f0d40fa9d7fa2666d8a4894c2ca14ddef3d0` |
| `board/system.hwh` | 853,392 B | `deb1f5a620a74bae0cd74b25a223c4ab2beb319877e2cc74b675e66ac6e83637` |
| `report/design_report.pdf` | 2,711,085 B | `a443741309b739f4b7a21d2dff2ec2927521434b6b3972e77e23f5742c469c84` |

位流这一对文件就是 `board/logs/` 里那两次实测所运行的位流（包内多处登记，可交叉核对：
`src/ps/core/p11_contract.py`、`src/ps/runtime/release_manifest.json`、`board/system.manifest.json`）。

## 三、关键指标

| 项 | 值 |
|---|---|
| EDA 版本 | **Vivado / Vitis 2025.2**（板上 PYNQ v3.1，pynq 3.1.1 / Python 3.10.4） |
| 目标器件 | `xc7z020clg400-1` |
| 资源占用 | LUT **17,569**（33.02%）、FF **24,135**（22.68%）、BRAM **121**（86.43%）、DSP **46**（20.91%） |
| 时序 | WNS **+0.650 ns**、TNS 0.000、WHS **+0.015 ns**、THS 0.000；失败端点 **0**（共 73,468 条） |
| 端到端实测 | 480P 静止场景 **22.73 fps**；相机 **30.72 fps**；单帧服务时间中位 **35.6 ms** |

⚠️ 帧率的唯一口径是 `HDMI_PROGRESS` 里 `frames` 累计值的**斜率**（在 `frames` 回退处切段），
**不要**取日志里的 `current_fps` / `hdmi_submit_fps` 等字段。读法见 `board/README.md`。

## 四、从零复现

```
# 1) 软件：从 src/ 重建运行包并跑全链自检（约 3 min）
python build/build_merged_release.py

# 2) PL：建工程 → 综合 → 实现 → 位流 → 报告（需要 Vivado 2025.2）
cd build/vivado
vivado -mode batch -source rebuild.tcl -nojournal -log rebuild.log
vivado -mode batch -source run_build.tcl   -nojournal -log run_build.log
```

上板操作见 `report/design_report.pdf` 第五部分「复现说明」（路径 A）与 `board/README.md`。

## 五、已验证的可复现性

| 对象 | 结论 |
|---|---|
| 三个 HLS 核 | 用 Vitis 2025.2 从 `src/hls/` 重跑，`hdl/` 与 `build/vivado/ip_repo/` 里的**逐字节相同**（`axis_sharp` 34/34、`color_convert` 14/14、`pixel_unpack` 25/25）；`component.xml` 除 `coreRevision`/`coreCreationDateTime` 两行生成信息外相同 |
| RTL 仿真 | `LIGHT27_PASS pixels=5311 cycles=10085`，与仓库原始日志逐字相同 |
| 运行包 | `release_manifest.json` 逐文件 sha256，113 条全部吻合（包内 114 个文件，多出的一个就是清单自己） |
| 位流 | **不是逐字节可重现**：同一份源在不同次实现里布线不同，sha256 必然不同。能对的是资源与时序档以及整机行为 —— 见 `build/vivado/README.md` |

## 六、怎么读这个包

先看根目录 `README.md`（项目简介 + 复现步骤），再看 `build/README.md`（构建链）与
`board/README.md`（上板与日志读法）。各子目录都有自己的 `README.md`，写的是"这一层为什么这么设计"。
设计报告在 `report/design_report.pdf`，其中第五部分是完整的从零复现步骤。
