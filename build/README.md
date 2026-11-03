# build —— 可复现构建

## 从零复现（按这个顺序）

| 步 | 命令 | 产物 | 约需 |
|---|---|---|---|
| 1 | `python build/build_merged_release.py` | 114 文件运行包（layers-6）+ 全链自检 PASS | 约 3 min（本机实测） |
| 2 | `cd build/vivado && vivado -mode batch -source rebuild.tcl` | `build/vivado/build/p11_light27.xpr` | 1–3 min |
| 3 | `cd build/vivado && vivado -mode batch -source run_build.tcl` | 位流 + 9 份报告 + `.xsa` | 半小时量级（8 jobs） |
| 4 | `python build/upload_merged.py`（可选） | 板上 `/tmp/…` → 校验 → 就地覆盖 | 2–3 min |

只要**软件**跑起来，第 1 步就够；只要**PL**，走第 2–3 步。第 1 步与第 2–3 步互不依赖。

## 组装 114 模块原样目录（备选：跑 sim 检查、对照用）

```
python build/assemble_runtime.py
```

把 `src/` 与 `board/` 下分散的 213 个文件合回一个扁平目录，并调用
`p11_contract.verify_package()` 逐文件核对 sha256——通过才打印 PASS。

输出默认到 `../_runtime_build/p11_fps33_20261101/`，同目录下另有
`assemble_runtime_report.txt` 记录完整过程。

## 打「按层合并」发布包（6 个文件版）

```
python build/build_merged_release.py
```

一条命令从 `src/` 重新合并并打完整目录，默认输出
`../_runtime_build/p11_fps33_20261101_merged/`；入库副本在 `release/p11_fps33_20261101_merged/`。
链条与判据：

| 步骤 | 脚本 | 干什么 |
|---|---|---|
| 1 | `merge_layers.py` | 114 个模块 → `core/geometry/tracking/display/ai/ui` 六个文件（AST 定位、原文本切片，中文注释一个字不丢） |
| 2–4 | （本脚本） | 照 `assemble_runtime.py` 的源清单整目录复制（再按 `RELEASE_EXCLUDE` 剔掉 3 条复现用不到的东西：旧 ZIP 安装本 / 上传校验快照 / **`board/logs/` 整个目录**）→ 删掉 114 个模块 `.py` → 拷进 6 个层文件 |
| 5 | `make_ai_entries.py` | 生成**自包含**的 `v99_ai_worker.py` / `v99_ai_selftest.py`（都是 `subprocess.Popen` 拉起的子进程入口，不是被 import 的模块） |
| 6 | `make_release_manifest.py` | 先把 `v98_ai_manifest.json` 收敛成包内 `ai/**` 的精确快照（40 → 7 条），再把 release 的 `sha256` 收敛成包内文件的精确快照（232 → 103 条），写 `layout: "layers-6"`。**两步顺序不能换**：AI 清单会改写磁盘文件，release 必须后算 |
| 7 | `check_merged.py` | A 3.10 语法 / B 导入 / C 模块身份 / D 契约闸门 / E 判红 / F AI 子进程门禁（含判红） |
| 8 | `check_undefined.py` | 静态查未定义名（标准库 `symtable`，等价 pyflakes F821）—— **导入成功 ≠ 名字能解析**；2026-11-02 板上 `LINE_BUF_ROWS` NameError 就是 `check_merged` 的 [B] 抓不到的 |
| 9 | `check_start_notebook.py` | 无头执行 `p11_start.ipynb` 第 1 单元（**板端唯一入口**）—— 合并版里没有 `p11_contract.py` / `v75_ui.py`，启动本必须改走 `core.py` / `ui.py` 分支才跑得起来 |
| 10 | （本脚本） | 清掉自检产生的 `__pycache__` |

**清单为什么要收敛**：`verify_package()` 只核 `required` 那 103 条，清单里多余条目从不校验
⇒ 底本里 130 条指向包里根本不存在的文件（`ai_selftest/*.png`、`hardware_light27/*` …）一直没人发现。
它们并非无害：`v84_prebuilt.export_ready_upload` 会遍历 `sha256` 逐个 `read_bytes()`，幽灵条目在那条路径上
直接 `FileNotFoundError`。现在清单 = 包内文件（除自己）的一一对应，`make_release_manifest.py` 每次先跑
**判红自检**（造一个幽灵条目 + 一个漏登文件，两条判据都必须报出来）再收敛，收敛后还有两条后置断言。

`v98_ai_manifest.json` 同理、而且更急：AI 子进程 `validate_assets()`（[v99_ai_worker.py:77](../src/ps/ui/v99_ai_worker.py#L77)）
会 `for name in manifest['sha256']: read_bytes()`，2026-11-02 板上因为清单里留着 33 条已剔除的
`model_zoo/utils/dist-info`，整条 AI 通路 `AI_INIT_FAILED`。**这个坑构建门禁抓不到** ——
`check_merged` 的 AI 门在 x86 上先撞平台断言（`machine != 'armv7l'`）就返回，遍历资产的循环只有板上才跑得到。
⇒ 验证 AI 必须在板上**直接调 `v99_ai_worker.validate_assets()`**（可再 `Model(...)` 走完 warmup），不要点屏幕试。

**合并正确性的五层证据**（缺一层都不算过）：

1. `verify_merge.py` —— 切回 114 段，AST 逐条顶层语句比对，**0 差异**（覆盖 2.8 万行全部代码，
   包括检查脚本跑不到的路径）。
2. `run_checks.py` + `compare_checks.py` —— 原版与合并版各跑一遍检查链，比结果；
   结构差异 0、非数值差异 0，数值差异只剩计时抖动（与「同一版跑两遍」的噪声底逐条相同）。
3. `check_merged.py` —— 契约闸门 `verify_package()` 真通过，并且**改坏一个字节必须报错**
   （E）、**改坏 RELEASE_ID 必须握不上手**（F5）—— 证明闸门不是永远通过。
4. `check_start_notebook.py` —— 无头执行 `p11_start.ipynb` 第 1 单元：合并目录与 114 模块目录
   **都要跑到最后一行 print**；再拿改动前的旧启动本去跑合并目录，**必须失败**（判红）。
   报告 `reports/check_start_notebook_{merged,modules114,red_orig_nb}.txt`。
5. `check_undefined.py` —— 六个层文件未定义名 **0 个**，控制组（原版 114 模块）也 0 个；
   判红：故意造一个 `return int(LINE_BUF_ROWS)` 必须报 `FAIL`。
   **只查「导入能不能过」是抓不到 `NameError` 的** —— 这个门禁就是为 2026-11-02 那次板上实炸补的。

## 上板

```
python build/upload_merged.py
```

⚠️ **在 Git Bash（MSYS）里传板端路径必须加 `MSYS_NO_PATHCONV=1`**：

```
MSYS_NO_PATHCONV=1 python build/upload_merged.py <本地目录> /home/xilinx/jupyter_notebooks/super/<包名>
```

不加的话 `/home/...` 会被改写成 `D:/Program Files/Git/home/...`，到板上被空格拆成两段，
在 `/home/xilinx` 下建出 `D:` 和 `Files` 两个垃圾目录（2026-11-03 实踩，包被传到了错的地方）。
脚本现在自带闸门：远端路径不是以 `/` 开头就直接拒绝，并提示加这个前缀。

SFTP 传 `/tmp/<目录名>.new` → 板上逐文件 `sha256sum` 与本地现算值比对 → 不一致就中止、
老目录原样保留 → 一致才 `sudo cp -a` **就地覆盖**（⛔ 不换目录：Jupyter 内核的 cwd 指向老目录的
inode，换掉再删 `.old` 会让内核里 `Path.cwd()` 直接 `FileNotFoundError`）→ 清上一版残留 →
在目标路径**再核一遍** → 删 staging。
报告 `reports/upload_merged_report.txt`。（2026-11-03 实测：115 文件 / 26.5 MB / 两处 sha256 全一致。
⚠️ 那次是删除 `5094.png` 之前跑的；现包 114 文件 / 25.0 MB，以 `release_manifest.json` 的 113 条为准。）

## 辅助脚本（不在主链上，按需单跑）

| 脚本 | 干什么 |
|---|---|
| `analyze_run_log.py` | 读板上 `run-result.log`，出一份只读的分段耗时分析报告 |
| `make_delivery_zip.py` | 把一个发布目录打成单个 zip（外发用"一个文件"） |
| `make_shims.py` | 给合并版造 114 个「原模块名」转发垫片，让现成的检查脚本还能按老名字 import |

## 其他文件

| 路径 | 内容 |
|---|---|
| `reports/` | 软件构建链的自检报告；其中 7 份 `*_impl.rpt` 是 **PL 综合与实现报告**（时序/资源/DRC/IO/时钟/功耗/布线），对应交付位流 `aaa9f632…` |
| `vivado/` | **PL 侧可复现构建源**：BD 脚本、IP 仓库、RTL 接口契约、建工程与跑流程的 tcl。见 [vivado/README.md](vivado/README.md) |
| `light27_hardware.json` | PL 硬件参数记录（快核重建后的资源/时序/板上实测） |
| `_stubs/` | 两个本机替身模块：`IPython.py`（`get_ipython()` 返回 None）与 `fcntl.py`（Windows 没有）。`check_merged` / `check_start_notebook` / `run_checks` 会把它插进 `sys.path`。**必须入库** |
| `_scratch/` | `make_*.py` 的默认输出目录（100 MB / 1000+ 文件），随时可重跑，**已 gitignore** |
| `delivery_manifest.json` | **33 版（114 模块扁平布局）** 的交付记录：zip 大小、sha256、测试勾选状态。⚠️ 记录的是当时那一版；当前构建链产出的是 layers-6 合并布局，清单由 `make_release_manifest.py` 现算 |
| `upload_inventory.json` | 同一次 33 版上板时的文件清单（390 条，由板上 `v84_prebuilt.py` 现算落盘）。⚠️ 同一说明：含 `hardware_light27/*` 等合并版已剔除的条目 |

## 环境

| 项 | 版本 |
|---|---|
| EDA 工具 | Vivado / Vitis **2025.2** |
| 目标器件 | `xc7z020clg400-1` |
| Python | 3.10+（本机 3.14.6 实跑通；`check_merged.py` 按 3.10 语法解析，与板端 3.10.4 对齐） |
| 第三方包 | 仅 `paramiko`（`upload_merged.py` 走 SFTP 才需要）；其余全是标准库 |

## 约定

- 构建脚本必须能从零跑通，不依赖任何手工点击。
- 报告保留原始输出，不截断、不做摘要。
- ⛔ 不提交 Vivado 构建产物（`.runs/` `.cache/` `.hw/` 等），已在 `.gitignore` 中排除。
