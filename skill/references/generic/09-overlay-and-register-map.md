# 09 · Overlay 加载、身份校验与 register_map

> **适用范围**：任何用 PYNQ `Overlay` 加载 PL 设计的项目（Zynq / Zynq MPSoC / Kria）。
> **失效条件**：裸机（无 Linux/PYNQ）或不用 Overlay 的场景。
> **不依赖任何特定题目**：讲的是"怎么确认板上跑的是你以为的那份硬件"，
> 以及"怎么安全地读写它的寄存器"。

---

## 为什么单独立一篇

上板调试里最贵的一类事故是：**代码没错、逻辑没错，但跑的根本不是你刚改的那份硬件。**
它没有任何报错，只有"结果不对"，于是你会去查算法、查时序、查数据 ——
一圈下来浪费几天。本篇的四层校验就是为此设计的，**总成本约 20 行代码**。

本项目的真实数据：**至少 3 次静默失败**（RTL 没上板 / IP 缓存是旧的 / 交付包里的副本漂移），
每次都在校验加上之后**一眼定案**。

---

## 一、加载路径：先搞清楚 Overlay 从哪来

PYNQ 的 `Overlay` 支持几种来源，**行为差别很大**：

| 来源 | 写法 | 说明 |
|---|---|---|
| 直接给 `.bit` | `Overlay('system.bit')` | 需要**同目录下有同名 `.hwh`**，否则拿不到 `ip_dict` |
| 给 `.xsa` | `Overlay('design.xsa')` | 会自己解出 bit 与 hwh；**推荐交付用这个** |
| IP 仓库名 | `Overlay('base.bit', download=True)` | 会去 PYNQ 的 overlay 仓库下载，**路径不经你控制** |

**⭐ 判据一：`ip_dict` 为空 ⇒ 九成是缺 `.hwh`（或 `.xsa` 里没有整机 hwh）。**
不是"这个 IP 没实现"，也不是"bit 坏了"。

**⚠️ 交付包里最常见的坑：子模块 hwh 冒充整机 hwh。**
导出 XSA 时，若层次里嵌套了 IP 集成流，会同时生成"整机 `system.hwh`"和
"子模块 `xxx.hwh`"。**放错那一个，`ip_dict` 里就只有子模块的 IP**，
表现为"明明例化了却找不到"。判据：`len(overlay.ip_dict)` 应该等于你 BD 里的 IP 总数。

---

## 二、加载之后必须校验四层

按顺序，前一层不过就不用看后一层。

### 第 1 层 · 结构：该有的 IP 都在

```python
required = ('my_ip', 'axi_dma_0', 'video/axi_vdma_disp')   # 键名 = BD 里的层次路径
missing  = [k for k in required if k not in overlay.ip_dict]
if missing:
    raise RuntimeError('overlay missing: %s' % missing)
```

**⭐ 判据二：键名不是例化名，是 BD 里的【层次路径】**（`video/hdmi_out/frontend/vtc_out` 这种）。
名字写错和"没实现"报的是同一个错 —— 先把 `sorted(overlay.ip_dict)` 打出来对一遍。

### 第 2 层 · 地址：基址对不对

```python
if int(overlay.ip_dict['my_ip']['phys_addr']) != 0x40000000:
    raise RuntimeError('base address mismatch')
```

**为什么必须查**：地址是 `assign_bd_address` 自动分配的，**改一次 BD 就可能变**。
一旦变了，你去写 `0x40000000` 就是**在写别人的寄存器** —— 不报错，只是行为诡异。

### 第 3 层 · 参数：关键 IP 的配置对不对

```python
params = overlay.ip_dict['video/axi_vdma_disp']['parameters']
for key, value in (('C_INCLUDE_MM2S', 1), ('C_INCLUDE_S2MM', 0),
                   ('C_NUM_FSTORES', 4)):
    if int(params.get(key, -1)) != value:
        raise RuntimeError('VDMA param mismatch: ' + key)
```

**⭐ 判据三：`overlay.ip_dict[name]['parameters']` 里存的是综合时的 IP 参数**，
是"这份 bit 到底怎么配的"的直接证据。比看 `.xci` 文件可靠（`.xci` 可能被改过但没重综合）。

### 第 4 层 · 身份：**读版本寄存器**（最值钱的一层）

```python
from pynq import MMIO
actual   = int(MMIO(0x40000000, 0x40).read(0x30))   # 自己 IP 里的版本寄存器
expected = 0x4C540001                                # 软件期望的版本
checkpoint('HW_IDENTITY', actual=hex(actual), expected=hex(expected))
if actual != expected:
    raise RuntimeError('version mismatch: 0x%08x != 0x%08x' % (actual, expected))
```

**⭐ 判据四：每个自研 IP 都要有一个【只读版本寄存器】，且软件启动必须读它。**
这是唯一能证明"板上的 bit 就是我期望的那一份"的手段，成本是一行 RTL。

**它为什么不可替代**：前三层查的都是"`.hwh` 描述的那份设计"，
而 `.hwh` 和 `.bit` 可以是**不同次综合的产物**（交付包里最常见的事故就是混用）。
只有读寄存器，才是在问**板上的真实硬件**。

> 本项目把版本寄存器放在 `remap` IP 的 `0x30`，回读值 `0x4C540001`（v4.4.0.1）。

**⚠️ 别用 `Overlay` 的 `is_loaded` / `download()` 返回值当证据** ——
它们只说明"下载动作完成了"，不说明下载的是哪一份。

---

## 三、`register_map`：比裸 `MMIO` 好在哪

PYNQ 为每个带 AXI-Lite 的 IP 自动生成 `register_map`，把寄存器名、位域、读写属性都描述出来。

```python
ip = overlay.my_ip                       # 例如 overlay.remap
ip.register_map.version                  # 按名字读，不用记偏移
ip.register_map.cfg_w_in = 640           # 按名字写，自动按位宽截断
ip.register_map.CTRL.AP_START = 1        # 位域直接点出来
print(ip.register_map)                   # 打印全部寄存器当前值
```

**三个必须知道的坑：**

| 坑 | 现象 | 对策 |
|---|---|---|
| **只写寄存器读回来是 0** | 以为"写失败了" | 看 `.hwh` 里该寄存器的 `access` 属性；只写寄存器**本来就读不回**，判据要换别的寄存器 |
| **位域写成整体会把同寄存器的其它位清零** | 改了 A 位，B 位莫名其妙变了 | 用位域赋值（`reg.FIELD = x`），别整体赋一个整数 |
| **`register_map` 是缓存还是直读，取决版本** | 写了立刻读，可能读到旧值 | 关键路径上**用 `MMIO` 直接读**，别依赖缓存 |

**⭐ 判据五：能读回的关键寄存器，写完立刻读回比对**，
不一致就抛异常 —— 这能抓住"地址错、位宽错、IP 没使能"一整类问题。

> 本项目为此做了 10 个字的**参数包写入 + 回读校验**（`parameter_readbacks`），
> 每帧都验。代价约 0.4 ms，换来的是"参数错位"这一类 bug 永远不会静默发生。

---

## 四、DMA 缓存一致性：flush / invalidate 放在哪

Zynq 的 PS 有 cache，PL 的 DMA 直接访问 DDR —— **两者看到的数据可能不一致**。
PYNQ 的 `allocate()` 返回的 buffer 自带 `flush()` / `invalidate()`，但**放错位置等于没放**。

```
CPU 写缓冲 → flush()  → DMA 读（MM2S）
DMA 写缓冲 → invalidate() → CPU 读（S2MM）
```

| 动作 | 谁做 | 什么时候 |
|---|---|---|
| `src.flush()` | **CPU 写完之后**、启动 DMA **之前** | 否则 DMA 可能读到 cache 里的旧数据 |
| `dst.invalidate()` | **DMA 完成之后**、CPU 读**之前** | 否则 CPU 可能读到 cache 里的旧数据 |

**⭐ 判据六：`flush` 在"写完后、传输前"，`invalidate` 在"传输后、读之前"。**
放到对面 = 白做，而且**没有任何报错**，症状是"偶尔数据错一格"。

**多块传输的优化**（本项目实测有效）：
第一次传输前 `flush` 一次，最后一块完成后 `invalidate` 一次 ——
中间 CPU 不碰这块内存，就不需要每块都同步。省下的时间在 `cache_sync_s` 里看得见。

---

## 五、常见报错 → 定位表

| 报错 / 现象 | 最可能的原因 | 第一步查什么 |
|---|---|---|
| `ip_dict` 为空 / `AttributeError: no attribute 'xxx'` | 缺 `.hwh`，或放的是**子模块 hwh** | `len(overlay.ip_dict)`、`sorted(overlay.ip_dict)` |
| `RuntimeError: overlay missing ['xxx']` | 键名不是 BD 层次路径；或该 IP 根本没进 bit | 打印 `sorted(overlay.ip_dict)` 对名字 |
| 写寄存器无反应，读回全 0 | 地址错 / IP 没使能 / 是只写寄存器 | 先读**版本寄存器**确认地址对；再看 `.hwh` 的 access |
| DMA 不出数据、`wait()` 卡死 | 长度超上限、长度非 4 的倍数、源地址未 flush | 见 `04-axi-dma-and-bd.md` 的 5 个默认值 |
| 数据**偶尔**错一格 | 缓存没同步（flush/invalidate 放错位置） | 先在**每块**传输前后都同步，确认是这个问题再优化 |
| 结果对但**整体错位一行/一列** | 行跨度（stride）与实际宽度不一致 | 比对 buffer 的 `shape`/`strides` 与写进 IP 的宽高 |
| 重启内核后行为变了 | 内核缓存了旧模块 / 旧 overlay | 见下方判据七 |

**⭐ 判据七：改了 `.py` 模块后必须重启内核。**
PYNQ 的 Overlay 对象和已导入模块都会被缓存；`from xxx import` 拿到的可能是旧代码。
真遇到"明明改了没生效"，先重启内核，再怀疑别的。

---

## 六、一页速查

```
加载后四层校验（缺一不可）
  ① 结构：required ⊆ overlay.ip_dict     —— 键名是 BD 层次路径
  ② 地址：phys_addr == 期望值            —— 地址会被 assign_bd_address 改掉
  ③ 参数：ip_dict[name]['parameters']    —— 综合时的真实配置
  ④ 身份：读【版本寄存器】               —— 唯一能证明"板上是这一份 bit"

修了 RTL / 重综合之后
  ① 版本寄存器值 +1
  ② 软件期望值同步改
  ③ 启动时读回比对，不一致就拒绝启动

缓存一致性
  flush：CPU 写完 → 传输前
  invalidate：传输完 → CPU 读前
  放错位置不报错，症状是"偶尔错一格"

改了 .py
  → 重启内核（Overlay 与模块都会被缓存）
```

---

## 七、来源与验证

| 内容 | 来源 | 验证 |
|---|---|---|
| 四层校验（结构/地址/参数/身份） | 3 次"跑的不是我以为的那份硬件"的静默失败 | 版本寄存器回读一眼定案；之后同类问题 0 次 |
| `ip_dict` 键名是 BD 层次路径 | PYNQ 找不到 IP，实为例化名与路径不一致 | 打印 `sorted(ip_dict)` 后当场解决 |
| 子模块 hwh 冒充整机 hwh | 交付包 `ip_dict` 缺大量 IP | 换成整机 hwh 后恢复 |
| 参数包写入 + 回读 | 参数错位导致"图错但核不报错" | 10 字回读校验，每帧 0.4 ms |
| flush/invalidate 位置 | 多块传输偶发单行错位 | 调整同步位置后消失 |
| 重启内核 | 改了模块行为未变 | 成为固定动作 |

**同族**：`pitfalls/06-pspl-delivery.md`（交付包与哈希链）、
`pitfalls/02-vivado-dma.md`（DMA 默认值与 BD 自查）、
`03-vivado-toolchain.md` §8.3（工程归档里可能是旧 RTL）。

---

> **姊妹材料**：`.hwh` 结构事实与 PYNQ 运行时的展开见 [`19-pynq-runtime.md`](../team/19-pynq-runtime.md) —— 本文给判据与定位表，那篇给实测细节。
