# sim —— 仿真与验证

本目录回答赛规 3.3.5.1 的第二条：**"仿真或验证结果，说明功能正确性是如何确认的"**。

## 一、功能正确性怎么确认（三层，互不替代）

| 层 | 手段 | 在哪 | 覆盖什么 |
|---|---|---|---|
| **PL（RTL）** | xsim 仿真，testbench 逐条核对寄存器与 AXIS 契约 | [`rtl/`](rtl/) | 灰度、彩色、反压停顿、包中途改参数、复位、II=1 |
| **PS（软件）** | 20 项主机侧 CPU 检查，链式回归 | [`checks/`](checks/) + [`run_checks.py`](run_checks.py) | 几何、跟踪、显示、恢复、界面、AI 协议 |
| **整机** | 板上冒烟与实测输出 | `../board/` | 见 `board/README.md` |

**三者不互相外推**：CPU 检查全绿不等于板上能跑；板上帧率也不能反推 RTL 的正确性。

## 二、目录

| 路径 | 内容 | 文件数 |
|---|---|---|
| `run_checks.py` | 一把跑完全部 CPU 检查，出单文件报告 | 1 |
| `requirements.txt` | 主机侧依赖（**numpy 必须 < 2**，见文件内注释） | 1 |
| `checks/` | 检查脚本 + 2 个基准（`.py` 24 个、`.cpp` 1 个、`.ipynb` 1 个） | 26 |
| `results/` | 各版本检查的原始输出，**历史证据链，不覆盖** | 66 |
| `rtl/` | xsim 两版日志 + 被测核契约文档 | 8 |
| `reports/` | `run_checks.py` 最近一次运行的单文件报告（可随时重生成） | 1 |

## 三、怎么跑

### 3.1 软件检查

**前置**：需要一个 **114 模块的扁平运行目录**（`python build/assemble_runtime.py` 生成）。

```bash
python sim/run_checks.py --release <扁平运行目录>
# 或者不写 --release，脚本自动在 ../_runtime_build/ 里找
python sim/run_checks.py
```

报告写到 `sim/reports/run_checks_report.txt`（头部有时间/机器/numpy/脚本 sha16，逐根完整输出，不截断）。

⛔ **不要直接 `python sim/checks/xxx.py`。** 老版 README 就是这么写的，实际跑不通，实测两种死法：

1. `ModuleNotFoundError: No module named 'p11_contract'` —— 运行时的 114 个模块不在 `sys.path` 上；
2. `FileNotFoundError: .../v105_edges.cpp` —— `trackfix_cpu_check.py:42` 读
   `Path(__file__).parent/'v105_edges.cpp'`，这些脚本**本来就该住在发布目录里**，搬进仓库就断了。

`run_checks.py` 的做法是把发布目录整个复制到临时目录、把检查脚本摆进去再跑，**不动原目录一个字节**。

`--board` 会把 `sharp23_board_check.py` 也跑上（**需要板子**，默认不跑）；`--keep` 保留临时目录便于事后翻现场。

### 3.2 RTL 仿真

见 [`rtl/README.md`](rtl/README.md)。要点：

```
xvlog -sv <repo>/src/rtl/axis_light27.v <repo>/src/rtl/tb_light27.sv
xelab tb_light27 -s light27_sim
xsim  light27_sim -runall
```

通过时打印 `LIGHT27_PASS pixels=5311 cycles=10085, ...`。`-sv` 不能省（不加会误判成 Verilog）。

## 四、清单：20 项检查各验什么（外加 1 个板上诊断、1 个基线探针）

检查是**一条依赖链**：每个脚本先跑前一个再验自己新增的那块。所以只需跑 3 个根
（`overlay` / `pic78` / `smooth`），就覆盖了全部 20 项——`run_checks.py` 会自动算出根。

| 脚本 | 验什么 |
|---|---|
| `trackfix_baseline_physical4.py` | 不是检查，是 `trackfix_cpu_check` 按文件加载的基线探针（4×24 物理边界） |
| `trackfix_cpu_check.py` | 同输入计时 + 边界修复回归，不碰相机/HDMI/overlay/DMA |
| `hybrid_cpu_check.py` | 混合跟踪安装检查，不开相机/HDMI/DMA |
| `unified_cpu_check.py` | 板上安装 smoke，纯 CPU |
| `recovery_cpu_check.py` | 安装 smoke，不开相机/HDMI/overlay/DMA |
| `hotfix_cpu_check.py` | 复位不变量 |
| `smooth_cpu_check.py` | 显示状态与取消（根之一） |
| `live_cpu_check.py` | 最新预览的所有权与取消 + native smoke |
| `overlay_cpu_check.py` | 元数据 / 覆盖层的所有权（根之一） |
| `paired_cpu_check.py` | 配对完成后的元数据 |
| `manual17_cpu_check.py` | manual17 的手动标定路径 |
| `display18_cpu_check.py` | 显示 smoke + 保留的 native17 检查 |
| `reuse21_cpu_check.py` | CPU/native 复用 |
| `profile22_cpu_check.py` | 相机 profile 切换 |
| `sharp23_cpu_check.py` | 锐化准入 / 协议 / UI |
| `sharp24_cpu_check.py` | remap1.5 能力与协议 |
| `sharp25_cpu_check.py` | 即时锐化协议 |
| `target26_cpu_check.py` | 目标选择 |
| `light27_cpu_check.py` | PL 光照补偿的控制与契约（Q8 强度、帧边界、多 tile、100 ms 合并） |
| `ui28_cpu_check.py` | 28 版整体（根之一，链最长） |
| `pic78_cpu_check.py` | `ui28` 的别名入口，供 pic78 版本号使用 |
| `sharp23_board_check.py` | ⚠️ **板上**小图诊断，需 `--board`；不属于"不依赖硬件"的部分 |

另外两个不是检查、不参与回归：`bench_b1.py`（B1 实验）、`benchmark_physical_tracking.py`（板上 CPU 跟踪器对比）。

## 五、`results/` 怎么读

66 份原始输出，横跨 **26 个历史 release_id**（版本 6 → 33），是证据链不是"最新一份覆盖上一份"。
对应关系按文件名里的版本名就能认：

```bash
grep -h '"release_id"' sim/results/*.json | sort | uniq -c
```

当前发布版本 `p11-rgb-pspl-v9-ai-fps-20261101-33` 的证据集中在
`fps33_validation.json`、`ui28_validation.json`、`light27_validation.json` 等文件里
（同一份 JSON 会被后续版本包含为 `previous_*`，所以老版本的结论在新版本里仍可查）。

## 六、约定

- **每个检查必须能判红**：先故意制造一次失败，确认它会报错，再相信它的通过结果。
  一个从未失败过的检查，等于没有检查。（`run_checks.py` 自身也验过：拿按层合并的 6 文件目录去撞，必须 FAIL。）
- `results/` 里的数据**不要覆盖**；新结果另起文件名。
- 仿真结果与板上实测数据分开存放，**不混算、不互相外推**。
- 新增检查请沿用 `xxx_cpu_check.py` 命名，并让它 `from 上一项 import run as previous` 接上链——
  `run_checks.py` 靠这个自动算根。
