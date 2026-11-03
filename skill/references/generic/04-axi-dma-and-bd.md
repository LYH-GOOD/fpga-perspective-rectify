# 通用技能 ④：AXI DMA 与 Block Design

> **适用范围**：Zynq + AXI DMA + IP Integrator 的 PS/PL 数据通路。
> **失效条件**：不用 DMA（纯 AXI-Lite）、或换到 Versal/其它厂商。

---

## 一、⭐ AXI DMA 有 5 个默认值会让你上板挂

这是本项目**花时间最多的一类问题**。全部是"默认值在演示规模下不够用"。

| # | 默认值 | 什么情况下挂 | 改成 |
|---|---|---|---|
| 1 | `c_sg_length_width` = **14 位** | 单次传输 > **16383 字节** | **23**（32 位寻址上限 = 8 MB）|
| 2 | MM 侧 32 位 → 长度必须是 **4 的倍数** | 字节数不整除 | 尺寸微调，或改数据位宽 |
| 3 | `c_include_sg` = 1 | 用不到 SG 时多余 | 0 |
| 4 | `c_sg_include_stscntrl_strm` = 1 | 流里没有 status/control 时错配 | 0 |
| 5 | 数据位宽默认 32 | 8bit 灰度流 | `c_m_axis_mm2s_tdata_width = 8` |

### 报错长什么样（都很难反推）

```
❌ Transfer size is 518400 bytes, which exceeds the maximum DMA buffer size 16383.
❌ DMA Internal Error (transfer length 0?)
```

> ⭐ **第二条最难查**：它其实是"传输字节数不是 4 的倍数"，但报错信息
> 完全看不出是尺寸问题。本项目的实例：
> 输出 `479×830 = 397570` 字节（÷4 = 99392.5）→ 挂；
> `613×868 = 532084`（÷4 = 133021）→ 正常。
>
> **教训：报错信息不可信时，回到协议规定去查。**
> Xilinx 原文：*"buffer length is not a multiple of the data width"*。

### 自己的代码里要加一条前置检查

```python
if (w_out * h_out) % 4 != 0:
    # 输出可以自动微调（改宽度 1~3 像素，长宽比影响 <0.5%）
    # 输入【不能】补字节 —— 核按 W×H 精确计数，多一个字节会被当成下一行
    raise ValueError("传输字节数必须是 4 的倍数")
```

---

## 二、⭐ `validate_bd_design` 返回 0 ≠ 接线完整

**本项目最典型的一个"静默失败"**：

Block Design 里 `axi_dma_0/S_AXI_LITE` **悬空**，但：

- `validate_bd_design` 返回 **0**（"校验通过"）
- 综合、实现、比特流全部成功，**0 CW / 0 Error**
- **`.hwh` 里查不到 DMA 的地址** → PYNQ 报 `Could not find IP or hierarchy axi_dma_0`

**根因**：`assign_bd_address` **不会给没有连接主机的从机分配地址**，
而悬空的从机被**静默跳过** —— 只是"没分到地址"而已，不报错。

### 对策：在 BD 脚本里加**地址自查**

```tcl
set segs [get_bd_addr_segs]
foreach n {remap axi_dma_0} {
    set found 0
    foreach seg $segs {
        if {[string match "*$n*" [get_property NAME $seg]]} {
            set off [get_property OFFSET $seg]
            if {$off ne "" && $off ne "<unassigned>"} { set found 1 }
        }
    }
    if {$found} { puts "  \[OK\]   $n 已分配到地址" } \
    else        { puts "  \[FAIL\] $n 没分到地址 —— 它的 AXI 从机口很可能悬空！" }
}
```

> ⭐ **通用原则：工具"校验通过"不等于"你连对了"。**
> 凡是工具会**静默跳过**的东西（悬空端口、未分配地址、被忽略的文件），
> 都要自己写一条显式自查。

---

## 三、第一次上板 PYNQ 找不到 IP？先看真实名字

```python
from pynq import Overlay
ol = Overlay("system.bit", ignore_version=True)
print(sorted(ol.ip_dict.keys()))
```

**PYNQ 用的名字未必等于 BD 里的 cell 名** —— 可能是 `axi_dma_0`，
也可能是 `system_axi_dma_0_0`。按打出来的名字访问即可。

（但如果**压根没有 DMA 的条目**，那就是上面第二节说的"悬空没分地址"。）

---

## 四、驱动 DMA 的实用要点

### `dma.wait()` **没有超时**

```python
# ❌ 卡住就永久阻塞，一行现场信息都不给
dma.sendchannel.wait()

# ✅ 用带超时的轮询（或线程 + Event）
```

**本项目实测**：一次挂起等了 4 分钟、全程无输出，只能强制终止，
**既不知道卡在哪，也拿不到现场**。

**超时后要读关键状态寄存器再报错**，把"卡住了"变成可诊断的数据：

```
现场：核 STATUS=0x00000008  busy=0 frame_done=0 stuck=0  帧计数=1
判断：核没在忙 —— 更像上游被堵（不是核的问题）
```

> ⭐ 这条一加上，定位时间从"小时级 + 猜"变成"30 秒给出方向"。

### `buffer` 分配 → 拷入 → 传输 → 拷回 → 释放

```python
in_buf  = allocate(shape=(h, w), dtype=np.uint8)
out_buf = allocate(shape=(H, W), dtype=np.uint8)
np.copyto(in_buf, img)
dma.sendchannel.transfer(in_buf)
dma.recvchannel.transfer(out_buf)
```

**顺序**：先起 S2MM 再起 MM2S（或反之都可以，PYNQ 两者都支持），
但**必须两个都 wait 完**再 `freebuffer()`。

---

## 五、自查清单（搭完 BD 照着过一遍）

- [ ] 每个 AXI 从机都连了主机（不只是连时钟/复位）
- [ ] `assign_bd_address` 后逐个确认地址非 `<unassigned>`
- [ ] DMA 的 `S_AXI_LITE` 接到了 PS（否则 DMA 完全无法启动）
- [ ] `c_sg_length_width` 按图像字节数改大
- [ ] 单次传输字节数是 4 的倍数
- [ ] 记录下每个 IP 的基地址（写进 README，便于 PS 侧对齐）
- [ ] `Overlay` 能加载，且能读到版本寄存器

---

## 六、⭐ 判据：`dma_wait` 该和【理论地板】比，不是和上一次比

> 2026-10-31：优化完 PL 核之后，"快了多少"这件事必须有个绝对参照，
> 否则只能一直和上一版比，永远不知道还有多少余量。

**理论地板**（本例）：

```
传输字节数 / 每像素拍数 ÷ 主频
= 185,344 px × 4.686 clk/px ÷ 83.333 MHz
= 10.42 ms
```

**实测 `dma_wait_s` 中位 10.96 ms ⇒ 已在地板上（差 5%）。**

| 结论 | 依据 |
|---|---|
| 再优化核**没有意义** | 已经贴着算力地板 |
| 要继续就得**改架构** | 提高并行度，否则拍/像素降不下来 |

**反例（同一天踩的）**：另一处的 `dma_wait` 是 12.48 ms，
高出地板 **2.06 ms（20%）**。差的这部分不是核慢，而是 **AXI/DDR 争用**
（显示 VDMA 同时在读输出缓冲）—— 换算法没用，得换访问模式。

**⭐ 判据**：`dma_wait − 理论地板` 才是"还能优化多少"；
这个差值小于 10% 就说明瓶颈已经不在核里，去别处找。

---

## 七、来源与验证

| 内容 | 来源 | 验证 |
|---|---|---|
| DMA 长度 16383 上限 | 960×540 报错 | 改 23 位后通过 |
| 长度必须 4 的倍数 | 479×830 挂 | 微调到 480×830 后通过 |
| `validate` 返回 0 但悬空 | PYNQ 找不到 DMA | 地址自查脚本抓出 |
| `wait()` 无超时 | 卡 4 分钟零输出 | 加超时+状态快照后 30 秒定位 |
| 一遍自查清单 | 上述全部 | 每次重建 BD 都跑 |
| §六 `dma_wait` vs 理论地板 | 2026-10-31 核提速后判断"还要不要继续优化" | 10.96 vs 10.42 ms ⇒ 判定已到地板 |
