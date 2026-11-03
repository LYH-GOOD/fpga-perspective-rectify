# 基于 FPGA 的视频透视自适应校正系统

**Real-Time Adaptive Perspective Rectification System for Video**

---

## 项目简介

书本、纸张等平面目标在倾斜或旋转拍摄时会产生透视畸变，版面歪斜、文字拉伸，不能直接当作正视画面来阅读、归档或送入识别算法。而现有的"拍照后逐张处理"方式，在背景杂乱或目标移动时仍需人工框选四角，难以适应连续拍摄的场景。

本作品构建了一套基于 PYNQ 平台的实时图像自适应校正系统来解决这个问题。系统以目标的物理外边缘作为定位依据，把传统视觉和 AI 分成两个阶段配合使用：常规情况下先由传统算法检测轮廓、拟合四条边，并校验它们之间的几何关系。只有在常规搜索找不到有效目标时——比如目标边缘不清晰、颜色与环境接近，或边缘有轻微遮挡、反光——才调用轻量化分割 AI 模型给出候选区域和初始四角。候选四角通过当前帧验证之后，交由跟踪模块接管，此后不再逐帧运行神经网络。

在软硬件分工上，控制、定位和跟踪放在处理系统（PS）侧运行，像素重映射、锐化和分段线性光补则由可编程逻辑（PL）侧承担。系统还通过相机复用、帧序号校验、异步任务和单一显示提交者这几种机制，减少了模式切换时的重复初始化，也避免了多路输出造成的画面不一致。界面上提供自动定位、AI 校正、手动四角、分辨率选择和增强参数调节等操作。当定位短暂失效时，系统会在限定时间之内继续用最后可信的四角去处理当前相机画面，而不是把画面冻结在旧图上。

系统已在 PYNQ-Z2 上完成部署并通过板端实测，累计运行数十小时、经历千余次交互会话未出现崩溃，能够持续稳定地完成实时校正与显示。

---

## 复现步骤

两条路径，按要做的事选一条：

| 要做的事 | 走哪条 | 用时 |
|---|---|---|
| 把它跑起来、核对结果 | **A · 直接上板** | 约 15 分钟 |
| 从源文件重建整个工程 | **B · 从零重建** | 约 1 小时，另加 Vivado 跑流程的时间 |

**统一口径**：EDA 用 **Vivado / Vitis 2025.2**，板上镜像 **PYNQ v3.1**（pynq 3.1.1 / Python 3.10.4），
目标器件 `xc7z020clg400-1`。交付的 `system.bit` 由 Vivado 2025.2 完成综合、实现与位流，
报告见 [`build/reports/`](build/reports/)；三个 HLS IP 由 Vitis 2025.2 生成，
源与重建方式见 [`src/hls/`](src/hls/)。

---

### A · 直接上板

#### A1　上板的是哪些文件

上板的是**一个目录**：[`release/p11_fps33_20261101_merged/`](release/p11_fps33_20261101_merged/) ——
114 个文件 / 25.0 MB。顶层 97 个，另有 `ai/`（7 个文件）与 `ai_selftest/`（10 张图，
其中 9 张是自检用例）两个子目录。

| 顶层文件 | 个数 | 作用 |
|---|---|---|
| `system.bit` + `system.hwh` | 2 | 位流与硬件描述，必须同名同目录 |
| `release_manifest.json` + `system.manifest.json` | 2 | 逐文件 sha256 清单，启动时逐个核对 |
| `core.py` `geometry.py` `tracking.py` `display.py` `ai.py` `ui.py` | 6 | 全部运行逻辑 |
| `v99_ai_worker.py` + `v99_ai_selftest.py` | 2 | AI 子进程入口 |
| `p11_start.ipynb` + `ai_selftest.ipynb` | 2 | 板端入口 |
| `*.png` + `*.json` | 71 + 6 | 界面素材与布局表 |
| `*.cpp` | 6 | 板上首次运行时现场编译 |

启动时 `verify_package()` 核对顶层 97 个中的 94 个（两份 notebook 与 `release_manifest.json`
本身除外）；`ai/` 缺文件则在 AI 初始化时报错。

上板时把该目录**整个**传上去，不要只挑其中几个文件。

这个目录由仓库源码一条命令产出（重跑会先清空同名目录）：

```
python build/build_merged_release.py release/p11_fps33_20261101_merged
```

不带参数时默认输出到克隆目录同级的 `_runtime_build/`。约 3 min，结尾打印 PASS 才算成功。

#### A2　板端硬件（缺一不可）

| 项 | 要求 |
|---|---|
| 开发板 | PYNQ-Z2（`xc7z020clg400-1`），PYNQ v3.1 镜像 |
| 显示 | HDMI 显示器接 **HDMI OUT**，输出固定 1280×720 |
| 相机 | UVC 摄像头接 USB 口，固定 `/dev/video0`，工作档 640×480@30 |
| 触摸屏 | **支持绝对坐标的 USB 触摸屏**。`run_ui` 启动时先开触摸设备，没有会直接报 `RuntimeError: No readable absolute USB touchscreen` |

#### A3　上传

```
MSYS_NO_PATHCONV=1 python build/upload_merged.py release/p11_fps33_20261101_merged /home/xilinx/jupyter_notebooks/super/p11_fps33_20261101_merged
```

- 脚本默认连 `192.168.2.99`（`xilinx` / `xilinx`）；换板子就改 [`build/upload_merged.py`](build/upload_merged.py) 顶部的 `HOST` / `USER` / `PASSWORD` / `REMOTE`。
- Git Bash（MSYS）里**必须**加 `MSYS_NO_PATHCONV=1`，否则 `/home/...` 会被改写成 Windows 路径。
- 流程：先传 `/tmp/<目录>.new` → 板上逐文件核 sha256 → 一致才就地覆盖 → 再核一遍；不一致就中止，老目录保留。
- 判据：`build/reports/upload_merged_report.txt` 里两处 sha256 全一致。
  （那份报告是删除 `5094.png` **之前**跑的，记的是 115 文件 / 26.5 MB；现包 114 文件 / 25.0 MB，
  逐文件核对以 `release_manifest.json` 的 113 条为准。）
- 也可以整目录手拷，**但必须一个文件不少** —— 启动时 `verify_package()` 逐文件核 sha256，
  顶层 94 个文件缺一个或内容不一致就拒绝启动。

#### A4　板上运行

1. 浏览器打开 `http://<板子IP>:9090`（Jupyter，`xilinx` / `xilinx`）
2. 进入该目录，打开 `p11_start.ipynb`
3. **先重启内核**（Kernel → Restart），运行**第 1 个单元** —— 自动定位本版目录并打印 `RELEASE_ID`
4. 运行**第 2 个单元**

#### A5　应该看到

| 现象 | 说明 |
|---|---|
| HDMI 出主界面 | **点一下触摸屏**开始处理 |
| 画面被拉正并实时刷新 | 纸、书本倾斜或旋转都能正过来 |
| 界面有帧率读数 | 3 秒统计一次、100 ms 刷新 |
| 默认跑满 2 小时 | `max_duration_s=7200`；提前停按界面上的 ■ Stop |
| 结束打印 `结束；日志: <路径>` | 日志为板上该目录下的 `run-result-*.log` |

参考值（原始日志见 [`board/README.md`](board/README.md)）：480P、静止场景 **22.73 fps**，
相机 30.72 fps，单帧服务时间中位 35.6 ms。口径是 `HDMI_PROGRESS` 里 `frames` 累计值的斜率，
换场景、换档位不能直接比。

**不开相机也能先验一套**：运行 `ai_selftest.ipynb`，用包内 9 条用例图跑 AI 分割，
9 条全过即说明 AI 子进程、清单校验与图片素材都完整。

---

### B · 从零重建

PL 与 PS 两条互不依赖，最后汇进同一个运行目录。

#### B1　PL：BD → 综合 → 实现 → 位流

```
cd build/vivado
vivado -mode batch -source rebuild.tcl   -nojournal -log rebuild.log
vivado -mode batch -source run_build.tcl -nojournal -log run_build.log
```

- `rebuild.tcl` 用 Block Design 源 [`system_light27.tcl`](build/vivado/system_light27.tcl)、
  7 个 IP 的 [`ip_repo/`](build/vivado/ip_repo/)、RTL 与约束 [`src/rtl/`](src/rtl/) 建工程，只建工程不跑流程。
- `run_build.tcl` 跑综合 → 实现 → 写位流，出 9 份报告与 `.xsa`。
- 产物：`build/vivado/build/p11_light27.runs/impl_1/system_wrapper.bit` 与同名 `.hwh`
  （必须同名同目录，`Overlay()` 靠它找硬件信息）。
- **放行条件**：WNS > 0、DRC 错误 0、布线错误 0。交付版实测 LUT 17,569（33.02%）、
  FF 24,135（22.68%）、BRAM 121（86.43%）、DSP 46、WNS +0.650 ns。
- 自己重建的位流要上板，须同步改齐各处登记（两份清单、`p11_contract.EXACT_PAIR_SHA256`、
  交付记录），否则 `verify_package()` 会拒绝启动。
- 三个 HLS IP（`axis_sharp` / `color_convert` / `pixel_unpack`）以**打包好的 IP** 提供
  （`ip_repo/`，含 `hdl/` 与 `component.xml`）；C++ 源与重建方式在 [`src/hls/`](src/hls/)。

#### B2　PS：软件源码

- [`src/ps/`](src/ps/)：`core/` 73 个 + `ui/` 41 个 = 114 个模块，纯 Python，无需编译。
- [`src/native/`](src/native/) 的 6 个 `.cpp` 不预编译：板上首次运行时由 `v64_io.py` /
  `v31_native.py` 用 g++ 现场编成 `.so`（`-O3 -fPIC -shared`，armv7l 加 `-mfpu=neon`）。

#### B3　打包

```
python build/build_merged_release.py release/p11_fps33_20261101_merged
```

合并 6 个层文件 → 按源清单复制 → 剔掉复现用不到的文件 → 删掉 114 个模块 →
造 AI 子进程入口 → 写两份清单 → 3 道门禁（`check_merged` / `check_undefined` /
`check_start_notebook`）。任一道不过就报错退出。

#### B4　上板

回到 **A2** 起，步骤相同。

#### B5　逐层验证（可选）

| 命令 | 核什么 |
|---|---|
| `python build/assemble_runtime.py` | 另打一份 114 模块原样布局，与合并版互相印证 |
| `python build/verify_merge.py` | 合并版切回 114 段做 AST 逐条比对，0 差异 |

---

## 目录结构

```
fpga-perspective-rectify/
├── README.md     项目简介与复现步骤
├── src/          设计源码（RTL / HLS / PS 侧软件）
├── sim/          仿真或验证脚本与结果
├── build/        可复现的构建脚本 + 综合与实现报告
├── board/        上板工程、运行脚本与实测输出
├── release/      上板运行目录（114 个文件，整个目录拷到板子）
├── data/         测试数据与参考结果
├── skill/        技能包（大模型协作中沉淀的可复用经验）
└── report/       设计报告 + 大模型协作记录
```

### 两种发布布局

`p11_contract.verify_package()` 要求运行文件与 `system.bit` 同目录，并按包根路径逐文件核 sha256，
所以仓库分层存放、上板前合回去。两种布局都受支持，写在 `release_manifest.json` 的 `layout` 字段里：

| 布局 | 怎么打 | `.py` 个数 | `layout` |
|---|---|---|---|
| 按层合并（**交付版**） | `python build/build_merged_release.py` | 6 个层文件 + `v99_ai_worker.py` / `v99_ai_selftest.py`（两个子进程入口） | `layers-6` |
| 原样 114 模块 | `python build/assemble_runtime.py` | 114 | `modules-114`（缺字段时默认） |

两种布局内容完全等价：合并版由 `build/verify_merge.py` 做 AST 逐条语句比对，0 差异。

## 环境与依赖

| 项 | 版本 |
|---|---|
| 开发板 | PYNQ-Z2（`xc7z020clg400-1`） |
| 板上镜像 | PYNQ v3.1（pynq 3.1.1 / Python 3.10.4） |
| EDA 工具 | Vivado / Vitis **2025.2** |
| 主机侧 | Python 3 + Jupyter Notebook |

> 如使用其他工具版本，须在报告中说明并保证脚本可复现。

## 许可证

本项目采用 [MIT](LICENSE) 许可证。
