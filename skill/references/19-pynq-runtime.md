<!--
类型：自有
本文件是 fpga-project-development 自有的规范 —— 既没有上游副本，也不是路由。
素材全部来自本项目 2026-09~11 的板上实测记录（memory：pynq-pl-board-test-result /
camera-kill-vdma-runaway / board-pynq-in-venv / pl-dma-cost-and-prepare-ceiling /
pynq-hwh-requirements / pl-widen64-negative-result / board-no-rtc-and-ram-budget），
以及 **2026-11-01 直接解析本工程真实 `.hwh` 文件得到的结构事实**
（`_p1_hdmi_2026-10-06/out/system.hwh`、`_p11_light27_.../_build29/system.hwh`、
`_pynq_pl/_归档/01_建板与HLS工程/.../plane_quad_bd.../system.hwh`）。

⚠️ 2026-11-01 新增，对应竞赛 §3.2.5.1 的两条加分原文：
①「通用的 Overlay 加载与校验流程、寄存器映射与 register_map 使用范式」
②「可复用的 DMA 搬运与缓存一致性处理封装，含常见出错情形定位方法」。
L 组 HLS 的构建侧（cfg 写法、m_axi 加宽、csim）在 [16](16-vivado-and-pl-build.md)，不在这里重复。
-->

# PYNQ 运行时：Overlay / register_map / DMA

## 为什么有这一份

**PL 侧的事，到 `write_bitstream` 结束；PS 侧的事，从 `Overlay()` 才开始。**
这两段之间有一个巨大的空白：bit 出来了，`.hwh` 也有，然后呢？

本项目在这个空白里踩过的坑，**每一个都不是"报错"，而是"静悄悄地给出错误结果"**：

| 实际发生过 | 症状 | 后来查明 |
|---|---|---|
| 地址寄存器没写进去 | kernel **正常置 AP_DONE**，四条观测全"正常"，**只有输出是垃圾** | PL 被重新配置过，寄存器清零而 Python 句柄还活着 |
| 拿 `register_map` 写地址 | 写不进去，不报错 | HLS 的地址寄存器在 `.hwh` 里就是 `write-only` |
| 按"4 字节步长"算寄存器偏移 | 读到的值看着像一个合法数字 | 这个 HLS 版本给的步长是 8 字节 |
| 用扁平正则扒 `.hwh` | 解析出的偏移**自相矛盾**（两个寄存器同偏移） | `<REGISTER>` 里嵌着 `<FIELD>`，字段也有同名属性 |
| 脚本被 SIGKILL 后硬件还在跑 | `import cv2` 段错误、`import pynq` 报 typing 错 | 采集 VDMA 仍往**已被 Python 释放的物理内存**写 |

**共同点：没有一条会给你一个像样的错误信息。**
所以这一份的核心不是"API 怎么调"，而是 —— **每一步的判据是什么，以及判红之后往哪儿看**。

## 每一项的四元组

| 项 | 类型 | 适用范围（什么时候读） | 使用方法 | 已验证的效果 | 失效条件 |
|---|---|---|---|---|---|
| 一、Overlay 加载→校验→冒烟 | **通用** | 每次把新 bit 带到板上、或换了一块板 | 三步照做，尤其**第二步核基地址** | 抓出过 bit 与 `.hwh` 不配对；`.hwh` 非 XML 时当场判红 | 不用 Overlay 而用裸 `/dev/mem`；非 Xilinx 平台 |
| 二、`register_map` 范式 | **通用** | 要读写 HLS 核的任何寄存器 | 先解析 `.hwh` 判 `ACCESS`，再决定用 `register_map` 还是 `mmio` | 地址寄存器写不进的问题一次性消失 | HLS 版本换了寄存器布局（步长会变，见 §2.4） |
| 三、DMA 搬运与缓存一致性 | **通用** | 任何"每帧几万个像素以上"的数据通路 | `pynq.allocate` + `sync_*_device` + 带超时的 `wait` | 720p 一路跑到 22.7 fps；98 KB 掩膜若走 AXI-Lite 要 24576 次事务 | 数据量小于 ~1 KB（DMA 固定开销不划算）；用中断而不是轮询 |
| 四、出错定位表 | **通用** | 板上行为不对、且**没有像样的报错**时 | 按症状查表，查的不是"可能原因"而是**寄存器判据** | 定位过 3 次"环境看起来坏了"的假象（真因都是 VDMA 失控） | 症状不在表里 ⇒ 照 §1 的三步重新自检一遍 |
| 五、环境事实 | **板卡相关**（PYNQ-Z2 + PYNQ 3.1.1） | 第一次在这块板上跑任何 python | 照抄 §5 的四条 | SSH 里直接跑通了实拍相机 190 帧 | 换镜像 / 换板 / 换 PYNQ 版本 |

---

## 一、Overlay 加载 → 校验 → 冒烟

### 1.1 三步，缺一步就白跑

```python
from pynq import Overlay

ol = Overlay('design_1.bit')          # ① 自动去找**同名**的 design_1.hwh

# ② 校验 —— 不是"没抛异常就算成功"，要核地址
expect = {                            # 从 .hwh 的 MEMRANGE 抄下来（见 §2.1）
    'sharp_0':      0x40030000,
    'axi_dma_0':    0x40400000,
}
bad = [(k, v, ol.ip_dict.get(k, {}).get('phys_addr')) for k, v in expect.items()
       if ol.ip_dict.get(k, {}).get('phys_addr') != v]
assert not bad, '基地址对不上：%r' % (bad,)

# ③ 冒烟 —— 跑一遍**最小数据通路**，比对黄金结果
#     ⛔ 不能靠"读回寄存器"冒烟：HLS 的地址/参数寄存器是 write-only，读不回来
```

### 1.2 为什么第二步必须自己核

**PYNQ 建 `ip_dict` 时只读 `.hwh`，它没有办法知道这个 `.hwh` 是不是跟 `.bit` 同一次构建的。**
所以：

- `.hwh` **缺失** ⇒ `Overlay()` 直接抛错（这一条会自己暴露）；
- `.hwh` **是旧的**（同名但来自上一次构建）⇒ **加载成功、地址表是旧的、没有任何警告**。

你说的每一句「板上跑通了」，都以这行断言为前提。把它写进驱动类的 `__init__`，不要靠记忆。

> 实测佐证：本项目 `_pl_unsharp_2026-10-28` 有 `board_pkg/` 与 `bypass/` 两套同名的
> `system.hwh`（851 723 B / 834 975 B，内容不同），拷错目录时 `Overlay()` 一无所知。

### 1.3 `.hwh` 的两条硬要求（踩过）

- **必须是 XML** —— PYNQ 用 `ElementTree` 解析。Vivado 导出的 `.hwh` 默认就是 XML，
  但**别手工改扩展名**或用工具转成别的格式。
- **必须与 `.bit` 同名同目录** —— `Overlay('a.bit')` 找的是 `a.hwh`。

### 1.4 冒烟测试怎么写

冒烟的唯一目的是「**这张 bit + 这个 hwh + 这段驱动，三者是配套的**」。所以要点是：

1. **输入用能算出唯一答案的数据** —— 例如给一个恒定灰度图，期望输出仍是同一个恒定值；
   或者直接喂一段已知的向量。
2. **判据要比对数值，不能只看到"跑完了"** —— 见上面第一条事故：kernel 明明拿着地址 0 在跑，
   照样把 AP_DONE 置起来。
3. **第一次跑就记下指纹**（输出的 sha256 或逐元素和），以后每次都核。
   `scripts/check-golden.py` 干的就是这件事。

---

## 二、`register_map` 使用范式

### 2.1 地址表：只从 `.hwh` 来

`.hwh` 的 `<MEMRANGE>` 就是地址表的**唯一权威**。解析要点（`ElementTree`，不要用正则）：

```python
import xml.etree.ElementTree as ET
root = ET.parse('design_1.hwh').getroot()

for mr in root.iter('MEMRANGE'):
    if mr.get('MEMTYPE') != 'REGISTER':      # 过滤掉 DDR 那几条（MEMTYPE="MEMORY"）
        continue
    print(mr.get('INSTANCE'), mr.get('BASEVALUE'), mr.get('HIGHVALUE'),
          mr.get('SLAVEBUSINTERFACE'))
```

本项目真实输出（`_p11_light27_2026-10-31/_build29/.../system.hwh`，2026-11-01 实跑）：

```
remap                                       base=0x40000000
axis_bypass_0                               base=0x40001000
axis_light_0                                base=0x40002000
video_hdmi_out_color_convert                base=0x40010000
video_hdmi_out_pixel_unpack                 base=0x40020000
axis_sharp_0                                base=0x40030000
axi_dma_0                                   base=0x40400000
video_hdmi_out_frontend_hdmi_out_hpd_video  base=0x41200000
irq_intc                                    base=0x41800000
video_axi_vdma_disp                         base=0x43000000
video_hdmi_out_frontend_axi_dynclk          base=0x43C00000
video_hdmi_out_frontend_vtc_out             base=0x43C10000
```

三条必须记住的：

- ⛔ **别照抄别人的 `0x43C00000`。** 那个数是 AXI-Lite 的**常见**基址，不是规定。
  本工程里它属于 `axi_dynclk`，而 HLS 核在 `0x40030000`。
- `INSTANCE` 里的名字可能带层次前缀（`video_hdmi_out_color_convert`），
  但 PYNQ 侧用的是同一个 `INSTANCE` 名 —— **`ol.ip_dict` 的键就是它**。
- `MEMTYPE="MEMORY"` 的是 PS 的 DDR 映射（`HP0_DDR_LOWOCM` / `0x1FFFFFFF`），不是外设，跳过。

### 2.2 寄存器偏移：只从 `.hwh` 或 `x<kernel>_hw.h` 来

**同一个 `.hwh` 文件里，两个 IP 的 `ADDRESS_OFFSET` 可能一个用十六进制、一个用十进制**
（2026-11-01 在 `_p11_light27_.../system.hwh` 里实测到）：

| IP | 写法 | 例子 |
|---|---|---|
| `axi_dma_0` | 十六进制 | `<PROPERTY NAME="ADDRESS_OFFSET" VALUE="0x30"/>` |
| `axis_sharp_0` | **十进制** | `<PROPERTY NAME="ADDRESS_OFFSET" VALUE="16"/>` |

⇒ 一律 `int(v, 0)`，它对两种写法都对。**别写 `int(v, 16)`，也别写 `int(v)`。**

### 2.3 ⛔ 解析陷阱：`<REGISTER>` 里嵌着 `<FIELD>`，两者都有同名属性

这是我自己 2026-11-01 踩的，而且**第一次没发现**：用扁平正则扒出来的寄存器表
**自相矛盾**（`w_out` 和 `h_out` 报同一个偏移），因为 `findall` 把字段属性也当成了寄存器属性。

```xml
<REGISTER NAME="CTRL">
  <PROPERTY NAME="ADDRESS_OFFSET" VALUE="0"/>     ← 这才是寄存器的
  ...
  <FIELDS>
    <FIELD NAME="AP_DONE">
      <PROPERTY NAME="ADDRESS_OFFSET" VALUE="1"/>  ← 这是**位号**，不是字节偏移！
      <PROPERTY NAME="BIT_OFFSET"     VALUE="1"/>
```

**`<FIELD>` 的 `ADDRESS_OFFSET` 是位号**（AP_DONE 的 "1" 指 bit1）。混进来就是灾难。

正确写法 —— **只取直接子节点**：

```python
for reg in ab.findall('REGISTERS/REGISTER'):
    props = {p.get('NAME'): p.get('VALUE') for p in reg.findall('PROPERTY')}
    #         ↑ findall('PROPERTY') 只取直接子元素，不会下沉到 FIELDS
    off = int(props['ADDRESS_OFFSET'], 0)
    acc = props.get('ACCESS', '?')
```

**自检判据**：解析完打印「寄存器名 / 偏移 / 访问权限」四列，然后**人眼看一遍偏移是否单调递增**。
出现重复偏移 = 解析错了，不是硬件错了。

### 2.4 ⛔ 别假设寄存器步长是 4

**同一个 Vivado 2026.1，本工程的三个 HLS 核给出了三种布局**（2026-11-01 实测解析）：

| 核 | 布局 |
|---|---|
| `pq`（plane_quad，64 位指针） | `mask_1`@0x10 `mask_2`@0x14 `w`@0x1c `h`@0x24 `out_r_1`@0x2c `out_r_2`@0x30 |
| `axis_sharp_0`（全 32 位标量） | `w_out`@0x10 `h_out`@0x18 `a8`@0x20 `enable`@0x28（**步长 8**） |
| `pixel_unpack` | `mode`@0x10 |

⇒ **永远从文件读，永远不要用 `0x10 + i*4` 推算。**

### 2.5 ⛔ 写地址/参数：用 `mmio.write`，且每次都重写

`register_map` **适合读**（它自己解析 `.hwh`，读只读寄存器很省事），
但 HLS 的参数与地址寄存器在 `.hwh` 里标着 `ACCESS="write-only"`：

```
# plane_quad 的 .hwh（2026-11-01 实跑解析）
CTRL     off=0    size=32  access=read-write
GIER     off=4    size=32  access=read-write
IP_IER   off=8    size=32  access=read-write
IP_ISR   off=12   size=32  access=read-write
mask_1   off=16   size=32  access=write-only     ← 64 位指针低半
mask_2   off=20   size=32  access=write-only     ← 64 位指针高半
w        off=28   size=32  access=write-only
h        off=36   size=32  access=write-only
out_r_1  off=44   size=32  access=write-only
out_r_2  off=48   size=32  access=write-only
```

⇒ **`register_map` 能不能用它，是一个可以从文件里判出来的事实，不用猜。**
判据只有一条：`ACCESS` 是不是 `write-only`。是 ⇒ 走 `ip.mmio.write(offset, value)`。

**两个附加事实（板上实测）**：

- **64 位地址必须拆成两个 32 位分别写** —— `register_map` **不会**把 `mask_1` + `mask_2`
  合并成一个 64 位属性，它们就是两个独立的属性。
- **⛔ 每次调用 kernel 前都要重写全部地址寄存器**，哪怕上一次刚写过。
  2026-09-27 的事故：PL 被别的进程重新配置过，寄存器归零而 Python 侧的 `self.ip` 还活着 ——
  **kernel 拿着地址 0 原地跑完，正常置 AP_DONE，四条观测全"正常"，只有输出是垃圾。**
  重写一遍的成本是几十纳秒，不重写的代价是一次无声错误。

> 💡 **上面这三件事（基地址、偏移、write-only 名单）都别手抄**：
> `python scripts/gen-host-skeleton.py <system.hwh>` 会直接从 `.hwh` 生成一份主机侧模块 ——
> `r()` 读到 write-only 直接抛，`w_u64()` 自动先低半后高半。
> 手抄一遍的失败模式是**静默**的（见本节事故），而生成器把这条约束写进了代码。

### 2.6 判完成：只看 AP_DONE，且只读一次

- `AP_CTRL` 的 **bit0 读回恒为 1**（本工程实测）⇒ 用 bit0 判"跑没跑过"会永远通过。
- `AP_DONE` 是 **bit1**，而且是**自清位** ⇒ 读两次可能第二次就没了。
  **只读一次，存进局部变量再判。**

```python
v = ip.mmio.read(0x00)                 # 只读这一次
done = (v >> 1) & 1
```

> 这条与 [14](14-coding-pitfalls.md) 的「空转门禁」是同一条原理：
> **一个永远为真的判据，等价于没有判据。**

---

## 三、DMA 搬运与缓存一致性

### 3.1 什么时候必须上 DMA

**判据是事务数，不是数据量。**

98 KB 的一比特掩膜走 AXI-Lite 要 **24 576 次事务**（每次一个 32 位字）。
实测对照：720 灰度图在传输量 ×10 时耗时反而 ÷3（固定开销主导）——
**说明 AXI-Lite 通道的成本结构是「每次事务」而不是「每个字节」**，所以大批量必死。

经验分界：**上百字节以上就走 DMA**；几十字节的寄存器配置走 AXI-Lite 反而更快。

### 3.2 三段式封装

```python
from pynq import Overlay, allocate
import numpy as np

ol   = Overlay('design_1.bit')
dma  = ol.axi_dma_0

buf_in  = allocate(shape=(H, W), dtype=np.uint8)   # ← 只能用 allocate 的 CMA 缓冲
buf_out = allocate(shape=(H, W), dtype=np.uint8)

buf_in[:] = frame                                  # 填数据
buf_in.sync_to_device()                            # ① 把 cache 刷到 DDR，PL 才看得见

dma.sendchannel.transfer(buf_in)
dma.recvchannel.transfer(buf_out)
dma.sendchannel.wait()                             # ⛔ 一定要带超时，见 §4
dma.recvchannel.wait()

buf_out.sync_from_device()                         # ② 把 PL 写的 DDR 失效出 cache，CPU 才看得见新值
result = buf_out.copy()                            # 拷出来再还给缓冲池
buf_in.freebuffer(); buf_out.freebuffer()
```

**⚠️ 普通 numpy 数组不能直接喂 `m_axi`** —— 它不保证物理连续。
画布的 ROI 视图（`img[y0:y1, x0:x1]`）尤其不能，那是跨行的非连续内存。
必须 `allocate` 一块、`np.copyto` 进去。

> 💡 **上面这段别手抄** —— 而且 `wait()` **根本没有超时参数**（那句 `⛔ 一定要带超时`
> 是提醒，不是 API）。直接用 `python scripts/dma_xfer.py` 里的 `DmaXfer` / `transfer_np`：
> 它把顺序、超时、以及「超时到底算卡住还是算失败」的判断都固化好了，
> 报错时给出 `S2MM_SR` 原值和逐位判读。`--selftest` 12 条臂，不需要板子。

### 3.3 缓存一致性：两条 `sync`，方向别搞反

| 方向 | 调用 | 忘了会怎样 |
|---|---|---|
| CPU 写 → PL 读 | `sync_to_device()` | PL 读到**旧数据**（还在 cache 里没落 DDR） |
| PL 写 → CPU 读 | `sync_from_device()` | CPU 读到**旧数据**（cache 里的旧副本盖住 DDR 新值） |

⚠️ **诚实标注**：这两条是 PYNQ 的标准用法，本项目全程按此写、批量通路跑对了
（720p 22.7 fps），但**「故意不 sync 会读到什么」我们没有做过对照实验** ——
所以这里给的是「照做就没错」，不是「漏了会怎样」的实测数据。

### 3.4 成本结构（2026-10-29 板上四臂实测，可用来做预算）

```
dma_wait = 2.251 ms + 50.09 µs / kpx      （≈ 20 Mpx/s 有效）
```

- 真实尺寸（185 kpx）处**固定项只占 19.5%，像素项 80.5%** ⇒ **这是像素驱动的硬地板**；
  减小固定开销没用，只能减像素 / 提频 / 加并行。
- ★ **但加大带宽的收益天花板很低**：输出像素砍到 1/4，`dma_wait` 掉 8.46 ms，
  而准备线程的空等 (`prep_wait`) **反涨 4.71 ms**，净 fps 只从 23.2 到 25.2。
  ⇒ **一处变快之后，瓶颈会平移到另一处**，别拿单点的改善当端到端收益
  （方法学见 [15](15-measurement-and-comparison.md)）。

### 3.5 ⛔ 别把"加宽 m_axi"当成默认优化

2026-11-01 实测：把 PL 的 `m_axi` 从 32 位加宽到 64 位，kernel 只快 **6.55%**，
端到端 **0.33%**。⇒ 「口太窄」不是瓶颈，「每像素多少拍」才是。
**在没有先量出"每拍搬了几个有效字节"之前，不要动这个旋钮。**

---

## 四、出错定位表

> 这张表里的每一条，都对应一次真实的误诊。**共同特征是：报错信息指向 Python 环境，
> 而真因在硬件状态。**

| 症状（看起来像什么） | 先查什么（不是猜，是读寄存器） | 判据 | 救法 |
|---|---|---|---|
| `import cv2` 约 1/3 概率 `Segmentation fault` | 采集 VDMA 的 **S2MM_SR (基址+0x34)** | `Halted` 位（bit0）= 0 ⇒ **还在往内存写** | 往 **S2MM_CR (基址+0x30)** 写 `0x4`（bit2 Reset），0.2 s 后复核 SR |
| `import pynq` 报 `typing.py` 里 `'builtin_function_or_method' object has no attribute 'UnionType'` | 同上 | 同上 | 同上。**这跟 Python 版本、跟 PYNQ 镜像都没关系**，是堆被踩坏的下游症状 |
| `free(): invalid next size` / `Fatal Python error: Aborted` | 同上 | 同上 | 同上 |
| 输出全是垃圾，但 kernel 正常置 `AP_DONE` | 驱动里**有没有每次重写地址寄存器** | 若上一次写完后 PL 被重配过 ⇒ 寄存器已归零 | 每次调用前重写全部地址/参数（§2.5） |
| `RuntimeError: No Devices Found` + 警告 `is the XRT environment sourced?` | `DeviceMeta._subclasses` 是不是空的 | 空 ⇒ `embedded_device` 根本没被 import | 在 `import pynq` **之前** `os.environ.setdefault('XILINX_XRT', '/usr')` |
| `OSError: Root permissions required.` | 当前 euid | `/dev/mem` 是 `0640 root:kmem`，PYNQ 直接判 `euid==0` | 用 `sudo -n <venv>/bin/python3`（Jupyter 能跑是因为它 `--allow-root`） |
| 板上"环境坏了"，什么脚本都跑不了 | **先看是不是自己上次没停车** | 见第一行 | ⛔ **别断电重启**，先按第一行停机；确实不行再断电 |

**两条方法论，比表本身重要：**

1. **⛔ 别读 MM2S 的 `0x00`/`0x04` 来判断。** 只有 S2MM 的核，未实现的 MM2S 寄存器
   **读回恒 0**，「SR = 0」**没有任何判别力** —— 我第一次就是这么误判的。
2. **症状指向 Python 时，先怀疑内存被别人踩了。** 堆损坏的表现是随机的、
   看起来像"某个包坏了""版本不兼容"，而真正的证据在一墙之隔的硬件寄存器里。

### 4.1 S2MM 位表：直接从 `.hwh` 读，别翻手册

PYNQ 的 `.hwh` 里带着每个字段的位定义（2026-11-01 从 `_p1_hdmi_2026-10-06/out/system.hwh`
解析 `axi_dma_0` 得到）：

```
S2MM_DMASR (0x34)
  bit 0   Halted         bit 8   SGIntErr      bit 14  Err_Irq
  bit 1   Idle           bit 9   SGSlvErr      bit 16  IRQThresholdSts[8]
  bit 3   SGIncld        bit 10  SGDecErr      bit 24  IRQDelaySts[8]
  bit 4   DMAIntErr      bit 12  IOC_Irq
  bit 5   DMASlvErr      bit 13  Dly_Irq
  bit 6   DMADecErr

S2MM_DMACR (0x30)
  bit 0   RS             bit 4   Cyclic_BD_Enable   bit 16  IRQThreshold[8]
  bit 2   Reset          bit 12  IOC_IrqEn          bit 24  IRQDelay[8]
  bit 3   Keyhole        bit 13  Dly_IrqEn
                         bit 14  Err_IrqEn
```

取法：

```python
for reg in ab.findall('REGISTERS/REGISTER'):
    if reg.get('NAME') != 'S2MM_DMASR':
        continue
    for f in reg.findall('FIELDS/FIELD'):
        p = {q.get('NAME'): q.get('VALUE') for q in f.findall('PROPERTY')}
        print('bit %s w=%s %s' % (p['BIT_OFFSET'], p['BIT_WIDTH'], f.get('NAME')))
```

**这一招的好处：换 IP、换版本都不用查文档**，位定义跟着 `.hwh` 一起走。

---

## 五、环境事实（PYNQ-Z2 + PYNQ 3.1.1 实测）

在**别的板上**要重新核，别当普适真理：

| 事实 | 值 / 做法 | 为什么 |
|---|---|---|
| Jupyter 用的是哪个 python | `/usr/local/share/pynq-venv/bin/python3` | **pynq / numpy / cv2 只在这个 venv 里**；系统 `python3` 没有 pynq 是**正常**，不是坏了 |
| 从 SSH 跑 pynq 要三件事 | ① `sudo -n <venv>/bin/python3` ② 脚本内 `os.environ.setdefault('XILINX_XRT','/usr')` ③ cwd **不能是 `/home/xilinx`** | 少一件的症状完全不同：① `Root permissions required` ② `No Devices Found` ③ 误加载 `/home/xilinx/pynq/` 那个坏副本、报 pydantic 缺失 |
| 开关怎么传给脚本 | **argv** | `sudo` 默认 `env_reset` 会吃掉外层环境变量；`VAR=1 sudo …` 不生效 |
| `XILINX_XRT` 写成什么 | `'/usr'` | 写成 `1` 更糟 —— pyxrt 把它当路径拼成 `1/lib/libxrt_core.so.2` |
| 内存 | **512 MB** | OOM 是真风险；诊断脚本要带内存遥测 |
| 时钟 | **没有 RTC**（fake-hwclock） | 板上时钟 ≠ PC 时钟；**别做亚秒级时间线推理** |
| 冷启动 | **先拔 HDMI 再上电** | HDMI 会回灌 |

---

## 六、这份文件**没有**覆盖的（别当成"我们做过"）

诚实边界，避免被误用：

- ❌ **中断驱动**：本项目**一次都没有真正等过中断** —— 所有"等完成"都是轮询
  （`dma.wait()` / 读状态位）。所以中断相关的封装**未经实测**，不给代码。
- ❌ **Scatter-Gather / 多 BD 链**：全工程用的是 Simple 模式。
- ❌ **多 Overlay 热切换**：没做过。
- ❌ **AXI-Lite 突发写**：没用过，全是一次一个 32 位字。
- ⚠️ **缓存一致性只给了"照做就没错"**，没给"漏了会怎样"的实测对照（见 §3.3）。

---

## 七、和加分项的对应关系

| 竞赛 §3.2.5.1 原文 | 本文对应 | 状态 |
|---|---|---|
| 通用的 Overlay 加载与校验流程 | §1（含「为什么必须自己核地址」） | ✅ |
| 寄存器映射与 `register_map` 使用范式 | §2（含三种真实布局、解析陷阱、写-only 判据） | ✅ |
| 可复用的 DMA 搬运与缓存一致性处理封装 | §3（含成本模型与"别乱加宽"的阴性结论） | ✅ |
| 含常见出错情形定位方法 | §4（症状 → 寄存器判据 → 救法，7 条） | ✅ |
