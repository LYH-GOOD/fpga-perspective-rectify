<!--
类型：自有
本文件是 fpga-project-development 自有的规范 —— 既没有上游副本，也不是路由。
素材来自本项目真实在跑的脚本：build/build_hdmi.tcl（Vivado 构建驱动）、
_copy_u8.py（单文件报告）、hls_config.cfg + csim tb、以及 llm_log 报告格式。

⚠️ 2026-11-01 新增，对应竞赛 §3.3.5.2「案例模板：可被下一个题目直接套用的
工程骨架、脚本模板、报告模板」。下面的代码**全部改编自真实在用的文件**，
不是示例代码 —— 把 `<>` 换掉就能跑。
-->

# 案例模板

## 为什么有这一份

前面几份讲的是**规矩**（怎么做对、怎么量准、怎么构建）。这一份是**能直接抄的骨架**。

新题目起步时最耗时的不是想算法，是**把工程搭起来**：目录怎么分、构建脚本怎么写、
报告长什么样、怎么证明"这个工程明天还能重建出一模一样的东西"。
这些**每个题目都一样**，抄一次就省一轮。

**全部模板改编自本项目真实在跑的文件**，不是凭空写的示例。

## 每一项的四元组

| # | 模板 | 类型 | 适用范围 | 已验证的效果 | 失效条件 |
|---|---|---|---|---|---|
| 1 | **工程骨架**（目录树） | **通用** | 任何 Vivado / HLS 项目起步 | 本项目四代工程（P1 / p11 / HLS / 相机）都按这个分法，交接时不需要解释 | 纯软件项目（无构建产物，骨架可简化） |
| 2 | **构建驱动 Tcl** | **通用** | 一条命令跑完「打包 IP → 建 BD → 综合 → 报资源与时序」 | 本项目每次构建都用它；`PROGRESS ne 100%` 那条当场拦下过没跑完的综合 | 用 GUI 手工构建（此时脚本无用武之地） |
| 3 | **单文件报告 Python** | **通用** | 任何会跑出结果的脚本（自检/诊断/批处理） | 崩了也留下已跑部分；用户从「手工粘贴屏幕」变成「只下载一个文件」 | 一次性脚本、不需要交接给别人 |
| 4 | **HLS 工程骨架** | **通用** | 新建一个 HLS 核 | 四条硬约束（ASCII 路径 / cfg / s_axilite / csim cwd）已内建 | 手写 Verilog；或走 Vitis 统一 IDE 流程 |
| 5 | **报告模板**（判读 / 协作记录） | **通用**（章节是本队约定） | 每次实验 / 每次改动要留痕时 | 阴性结果、假设清单都能留在同一份报告里 | 无 |
| 6 | **可复现性校验**（已做成 [`scripts/check-repro.py`](../../scripts/check-repro.py)） | **通用** | 交付前 / 换机器重建后 | 真 3.86 MB 比特流实测：一致 → 绿、改 1 字节 → 红、允许区间内 → 绿，耗时 0.04–0.10 s | 构建本身不确定（含随机种子、未初始化寄存器） |

---

## 一、工程骨架

```
<project>/
├── CLAUDE.md              ← 不变量写这里（每次自动加载），不靠对话记忆
├── README.md              ← 人看：这是什么、怎么跑、结果在哪
│
├── src/                   ← ⭐ 手写源文件，全部是"人写的"
│   ├── rtl/*.v            ←   Verilog（如果手写）
│   ├── hls/<kernel>/      ←   HLS 核：<kernel>.cpp + hls_config.cfg
│   └── ps/*.py            ←   PS 侧 Python
│
├── sim/                   ← 仿真（TB + 跑法脚本）
│   ├── tb_*.v / tb_*.cpp
│   └── run_sim.sh         ← 一条命令跑全部 TB，输出 PASS/FAIL
│
├── build/                 ← ⭐ 构建脚本（不是产物）
│   ├── build_synth.tcl    ← 综合到出报告
│   ├── build_impl.tcl     ← 实现到写比特流
│   ├── create_bd*.tcl     ← 建 Block Design
│   ├── package_ip.tcl     ← 打包 IP
│   └── check_filenames.py ← 机械守卫（见 [14](14-coding-pitfalls.md)）
│
├── board/                 ← Vivado 工程本体（.xpr 在这层）
│   └── <proj>/<proj>.xpr
│
├── hw/                    ← ⭐ 交付件：.bit + .hwh（同名！见 [16](16-vivado-and-pl-build.md) D2）
│
├── report/                ← 报告（人看的东西）
│   ├── llm_log/           ←   每次改动一篇
│   └── onboard/           ←   上板原始输出
│
└── _存档/                  ← 快照（代替 git commit，见 [09](../workflow/09-writing-plans.md)）
```

**三条铁律：**

| # | 规矩 | 为什么 |
|---|---|---|
| 1 | **`src/` 只放人写的，`board/` 只放 Vivado 生成** | 复制工程时 `src/` 必须改名、`board/.runs` 绝不碰 —— 混在一起就分不清了（[16](16-vivado-and-pl-build.md) P1） |
| 2 | **`build/` 放脚本，不放产物** | 产物在 `board/<proj>.runs/` 里，几百 MB～几 GB，**绝不进存档** |
| 3 | **`.bit` 和 `.hwh` 放一起且同名** | PYNQ 的 `Overlay()` 自动找同名 `.hwh`（[16](16-vivado-and-pl-build.md) D2） |

**`_` 前缀 = 过程材料**，故意和正式产物分开 —— 以后才分得清哪些是交付物、哪些是草稿。

---

## 二、脚本模板 · 构建驱动 Tcl

**用法**：`vivado -mode batch -source build/build_synth.tcl`
**要点**：一条命令从「源码」走到「资源 + 时序摘要」，中途任何一步不对就 `error` 退出。

```tcl
#=============================================================================
# build/build_synth.tcl
#   <一句话说明这个脚本干什么>
#
#   ⚠️ ASCII ONLY —— Vivado 在中文 Windows 上按 GBK 读 .tcl，
#      文件里出现中文会静默乱码（不是报错，是"跑出来不对"）。
#
#   ⚠️ -jobs ≤ 2 —— 并发 OOC 会撞 tclapp 竞态（见 references/16 的 V8）。
#=============================================================================

set script_dir [file dirname [file normalize [info script]]]
set proj_root  [file normalize [file join $script_dir ..]]
set prj_file   [file join $proj_root board <proj> <proj>.xpr]

puts "============================================================"
puts " BUILD <target>"
puts " Project: $prj_file"
puts "============================================================"

open_project $prj_file

# ---- 1/N  <第一步，例如 package_ip / create_bd> ----
puts "\n---- 1/N  <step> ----"
source [file join $script_dir <step>.tcl]

# ---- 2/N  综合 ----
puts "\n---- 2/N  synth_1 ----"
reset_run synth_1
launch_runs synth_1 -jobs 2
wait_on_run synth_1

set st [get_property STATUS [get_runs synth_1]]
set pr [get_property PROGRESS [get_runs synth_1]]
puts "\n synth_1 status: $st  ($pr%)"

# ⛔ 这是门禁，不是日志：没跑完就必须红
if {$pr ne "100%"} {
    error "synthesis did not finish: $st"
}

open_run synth_1 -name synth_1

# ---- 资源摘要（只打关心的几项，别刷屏）----
puts "\n================= UTILIZATION ================="
set u [report_utilization -return_string]
foreach ln [split $u "\n"] {
    if {[regexp {(Slice LUTs|Slice Registers|Block RAM Tile|RAMB36/FIFO|RAMB18|DSPs|Bonded IOB)} $ln]} {
        puts [string trim $ln]
    }
}

# ---- 时序摘要 ----
puts "\n================= TIMING ================="
set t [report_timing_summary -delay_type min_max -return_string]
foreach ln [split $t "\n"] {
    if {[regexp {(Setup|Hold|WNS|TNS|WHS|THS|Number of failing)} $ln]} {
        puts [string trim $ln]
    }
}

puts "\n============================================================"
puts " SYNTH DONE. Next: build_impl.tcl"
puts "============================================================"
```

**三个必须保留的设计：**

| 设计 | 为什么 |
|---|---|
| `if {$pr ne "100%"} { error ... }` | **这是门禁。** 只打日志的话，综合没跑完你也会往下走。**先证明它能判红**（见 [17](17-prompt-workflows.md) 模板 3） |
| `-jobs 2` 而不是 `-jobs 4` | `-jobs 4` 会触发 Windows 上 `%APPDATA%\Xilinx\Vivado\tclapp\manifest.tcl` 的写冲突，OOC 子 run **静默死亡** |
| 资源/时序**只打几行** | 刷屏的日志等于没日志。要看细节再 `open_run` 单独查 |

**失效条件**：用 GUI 手工构建时脚本用不上；Linux 下 `-jobs` 可以放大（竞态是 Windows 路径问题）。

---

## 三、脚本模板 · 单文件报告 Python

**用法**：`python <script>.py` —— 屏幕和报告**逐字相同**，用户只下载一个文件。

```python
"""<一句话说明这个脚本干什么。>

跑法：python <script>.py
产出：<report_name>_<时间>.log —— 单文件报告，与屏幕逐字相同。
"""
import hashlib
import os
import sys
import time

REPORT = '<report_name>_%s.log' % time.strftime('%Y%m%d_%H%M%S')
_OUT = open(REPORT, 'w', encoding='utf-8', buffering=1)   # ← 行缓冲


def say(line=''):
    """唯一出口：写报告 + 写屏幕，内容一字不差。"""
    text = str(line) + '\n'
    _OUT.write(text)
    _OUT.flush()                                  # ← 每笔都 flush，崩了也留下
    try:
        # ⚠️ 本机 stdout 是 GBK，'✅' / '⚠' 直接 print 会崩且一个字节都不出
        sys.stdout.buffer.write(text.encode('utf-8', 'replace'))
        sys.stdout.buffer.flush()
    except Exception:
        pass


def sha16(p):
    try:
        with open(p, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception as exc:
        return 'ERR:%r' % (exc,)                  # ← 失败原因原样留，不吞


def main():
    say('#' * 76)
    say('# <script_name>  %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('#   host=%s  uid=%d' % (os.uname().nodename, os.geteuid()))  # Windows 用 os.getlogin()
    say('#   sha16=%s' % sha16(__file__))
    say('#' * 76)

    # ... 正文 ...

    say('')
    say('  报告: %s' % os.path.abspath(REPORT))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        import traceback
        say('')
        say('!! 异常（全文，不截断）：')            # ⛔ 绝不许 split('\n')[0][:80]
        for row in traceback.format_exc().rstrip().splitlines():
            say('   | ' + row)
        say('  报告: %s' % os.path.abspath(REPORT))
        raise
```

**五个必须保留的设计（每一个都对应一次事故）：**

| 设计 | 事故 |
|---|---|
| `sys.stdout.buffer.write(...encode('utf-8','replace'))` | `print('✅')` 在 GBK 控制台**直接崩，且报告一个字节都不出** |
| `buffering=1` + 每笔 `flush()` | 崩在中途时，已经跑过的那部分必须留在盘上 |
| 报告头和屏幕**走同一个 `say()`** | 保证"逐字相同"；两处分别写迟早会不一致 |
| 异常**全文**写进报告 | `str(x).split("\n")[0][:80]` 会截掉的恰好是最该看的那几行 |
| `sha16(__file__)` 进报告头 | 报告必须能自证「是哪一版脚本跑的」 |

**失效条件**：纯 Linux 环境（stdout 不是 GBK）时 `encode` 那层仍需要，但不会崩；
一次性脚本、不需要给人交接时可以省掉报告，**但绝不省 traceback 全文**。

---

## 四、HLS 工程骨架

**`src/hls/<kernel>/hls_config.cfg`** —— 源文件不接受位置参数，必须写这个：

```ini
part=xc7z020clg400-1
[hls]
clock=100MHz
flow_target=vivado
syn.file=<kernel>.cpp
syn.top=<kernel>
```

跑法：

```bat
v++.bat -c --mode hls --config hls_config.cfg --work_dir <dir> --part xc7z020clg400-1
```

**`<kernel>.cpp` 接口骨架** —— 每一条 `m_axi` 都必须配一条 `s_axilite`：

```c
void <kernel>(const ap_uint<8>* in, ap_uint<8>* out, int w, int h) {
#pragma HLS INTERFACE m_axi     port=in  bundle=gmem depth=<N>
#pragma HLS INTERFACE s_axilite port=in  bundle=control   // ← 少这行就出双接口
#pragma HLS INTERFACE m_axi     port=out bundle=gmem depth=<N>
#pragma HLS INTERFACE s_axilite port=out bundle=control
#pragma HLS INTERFACE s_axilite port=w   bundle=control
#pragma HLS INTERFACE s_axilite port=h   bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control

    for (int y = 0; y < h; ++y) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=4096
        for (int x = 0; x < w; ++x) {
#pragma HLS PIPELINE II=1
            // ...
        }
    }
}
```

**`sim/tb_<kernel>.cpp` 的契约**：**路径从环境变量拿，不要猜 cwd**。

```c
const char* dir = getenv("HLS_TB_DIR");   // ← 不要用 "." 或 argv[0] 推
```

因为 `vitis-run --mode hls --csim` 打印的 `Changing directory to ...` **是骗人的**，
tb 真正的 cwd 既不是脚本目录也不是那行说的目录。

**反空转判据（必须写进 tb 的退出码）**：

```
必须 bad=N>0 且 输出里不含 "cannot open" 才算真跑过；
只判"输出里有 TB_FAIL"会把"文件打不开"也当成通过。
```

---

## 五、报告模板

### 5.1 判读报告（每次实验一份）

```markdown
# <实验名> 判读 · <日期>

## 一、这一轮的口径
- 计数器：<哪一行日志的哪个字段>
- 分母：<几帧 / 几次调用 / 几条线程>
- 饱和了吗：<是 / 否，依据>

## 二、数据
| 组 | 值 | 备注 |
|---|---|---|

## 三、结论
<只写这一轮数据支持的结论>

## 四、本轮假设（未实测，必须标出来）
- [假设] <乘数 / 外推 / 猜测>

## 五、阴性结果
<"改了没用" 也要写 —— 否则下一个人会重做一遍>

## 六、产物
- 报告：<路径>
- 数据：<路径>
```

**为什么必须有「假设」和「阴性结果」两节**：
本项目曾按「每帧 3 次」的**未标注假设**排优化优先级，实测是 **0.05 次/帧**，差 15 倍，整条结论作废。

### 5.2 协作记录（每次改动一篇）

```markdown
# <日期> · <主题>
## 一、问题（现象 + 数据）
## 二、根因（怎么定位的）
## 三、修复
## 四、比修复更重要的东西（如果有）
## 五、踩坑清单（技能包原料）
```

**要点**：失败和走弯路都写；带数字；末尾固定加"踩坑清单"。

---

## 六、可复现性校验

**已做成脚本，不用抄**：[`scripts/check-repro.py`](../../scripts/check-repro.py)

```bash
python scripts/check-repro.py <a.bit> <b.bit>                       # 有任何差异都判红
python scripts/check-repro.py <a.bit> <b.bit> --allow=0x1F00-0x1F10 # 声明允许的区间
python scripts/check-repro.py --selftest                            # 6 条自检
```

**为什么必须有 `--allow`**：Vivado 的 `.bit` 里带构建时间戳，重建两次必然有几个字节不同。
本项目实测：同一份源重建只差 **5 个字节**。不把「允许不同的区间」写死，这个检查**每次都会红**
—— 然后就会被无视。

**判据**：

| 情形 | 判定 |
|---|---|
| 0 个差异字节 | ✅ 完全可复现 |
| 差异**全部**落在 `--allow` 区间内 | ✅ 但这是「允许范围内的一致」，**不是**逐字节一致 |
| 有差异，没给 `--allow` | ❌ |
| 有差异落在区间外 | ❌ |
| 长度不等 | ❌ `--allow` 写得再宽也盖不住这个 |

**配套的另外两个脚本**：

- [`scripts/check-timing.py`](../../scripts/check-timing.py) —— 检查综合/实现报告的 WNS / WHS 与资源占用
  （认 `report_timing_summary` 与 `report_utilization` 的真实输出格式）。
- [`scripts/check-golden.py`](../../scripts/check-golden.py) —— **黄金参考比对**：先留一份「已知正确」的产物当参照，
  以后每次改动都拿新产物跟它比。`--ref <参考> --out <产出>`，逐文件判 PASS / FAIL / N/A。

```bash
python scripts/check-golden.py --ref golden/ --out out/                  # 逐像素严格
python scripts/check-golden.py --ref golden/ --out out/ --pixel-tol 2 --pct-tol 0.05
python scripts/check-golden.py --ref golden/ --out out/ --strict-extra   # 多出文件也判红
python scripts/check-golden.py --selftest                                # 11 条自检
```

**两个容差的分工**（搞混了就会拧一个永不生效的开关）：`--pixel-tol` 定义「差多少才算这个像素不一样」，
`--pct-tol` 定义「允许多大比例的元素不一样」，**判定只看后者**。

三个脚本都用 `--selftest` 先证明能判红 —— 见 [17](17-prompt-workflows.md) 模板 3。

---

## 七、来源验证

| 模板 | 从哪些失败/观察总结 | 怎么验证有效 |
|---|---|---|
| 工程骨架 | 四代工程合并时的目录混乱；复制工程时把 `.runs/` 一起改了 | 按此分法后，复制改名一次构建通过 |
| 构建 Tcl | `-jobs 4` 撞 tclapp 竞态导致 OOC **静默死亡**；综合没跑完却继续往下走 | 改成 `-jobs 2` + `PROGRESS` 门禁后，2/2 恢复 |
| 单文件报告 | `print('✅')` 在 GBK 控制台崩且报告 0 字节；中途崩了什么都不留 | 改成 `buffer.write` + 每笔 flush 后，崩了也留下已跑部分 |
| HLS 骨架 | 中文路径下 v++ 直接挂；少 `s_axilite` 出双基地址；csim 猜 cwd 拿到 `cannot open` | 四条约束逐条 A/B 实测 |
| 报告模板 | 未标注假设差 15 倍；阴性结果没记导致重做 | 加了「假设」「阴性结果」两节后，结论可追溯 |
| 可复现性 | 交付包里的原件与源不一致；重建与交付差 5 字节 | 每次交付前跑，差异区间定位到日期区 |

---

## 八、失效条件汇总

| 模板 | 什么时候别用 |
|---|---|
| 工程骨架 | 纯软件项目（无构建产物，可大幅简化）；不是 Vivado 流程的 FPGA 厂商 |
| 构建 Tcl | 用 GUI 手工构建；Linux 下 `-jobs` 可放大 |
| 单文件报告 | 一次性脚本、不交接 —— 但 traceback 全文永远不能省 |
| HLS 骨架 | 手写 Verilog；Vitis 统一 IDE 流程（cfg 写法不同） |
| 报告模板 | 无（章节可按项目调整） |
| 可复现性校验 | 构建本身含真随机（如随机初始化 BRAM）时，逐字节相同不成立 |
