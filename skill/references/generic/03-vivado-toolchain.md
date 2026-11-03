# 通用技能 ③：Vivado / 工具链（Windows）

> **适用范围**：在 Windows 上用 Vivado 做 RTL 工程的任何项目。
> **失效条件**：Linux 下部分条目不适用（路径大小写、批处理文件等）。

---

## 一、让工程**可复现**：一切用 Tcl，且脚本要幂等

### 踩过的坑

"在我机器上能跑"——本项目**在队友机器上连坏 4 次**，其中 2 次是脚本问题：

| 现象 | 根因 |
|---|---|
| 脚本在队友那边找不到文件 | **交付包和仓库的目录布局不一样**，脚本硬编码了路径 |
| `sim` 跑不起来 | **生成物没进生成步骤**，我们这边靠残留文件"看起来是过的" |

### 正确做法

**(a) 路径全部从脚本自身位置推**

```tcl
set script_dir [file dirname [file normalize [info script]]]
set proj_root  [file normalize [file join $script_dir ..]]
```

**(b) 布局自适应**（交付包通常比仓库扁平）：

```bash
if   [ -d "src/rtl" ]; then RTL_DIR="src/rtl"; TB_DIR="src/tb"
elif [ -d "rtl"     ]; then RTL_DIR="rtl";     TB_DIR="sim/tb"
else echo "[FAIL] 找不到 RTL 目录"; exit 1
fi
```

**(c) 用"删掉所有生成物再跑"来验证可复现性**

```bash
rm -rf sim/out sim/vectors && bash sim/run_sim.sh
```

> ⭐ **这一步能抓出"靠残留文件假装通过"的流程**。本项目就是这么发现
> 向量生成步骤漏了一个脚本的。

---

## 二、Vivado 会自动改你的顶层

```tcl
# ❌ 只设 top，Vivado 会把"未验证"的 top 换掉
set_property top my_top [get_filesets sources_1]

# ✅ 必须先禁掉自动编译顺序管理
set_property source_mgmt_mode None [current_project]
set_property top my_top [get_filesets sources_1]
update_compile_order -fileset sources_1
```

**症状**：综合的顶层悄悄变成了别的模块，报一堆"找不到 xxx"。

---

## 三、删工程之前必须先在 Vivado 里关掉

```tcl
close_project          # 先关
# 然后才能在文件系统里删目录
```

否则 `.Xil` / `.runs` 目录被锁，删不干净，下次打开工程状态错乱。

**相关**：僵死的 `xsimk.exe` 会锁住 `.sim` 目录 —— 任务管理器里杀掉再删。

---

## 四、综合 vs 实现：**综合过了不等于实现能过**

本项目的真实数字：

| 阶段 | WNS |
|---|---|
| 综合后估算 | 通过 |
| **实现后（真实布线）** | **-0.254 ns，38 个端点违例** |

**原因**：BRAM 从 32 块涨到 80 块、**铺满芯片** → 控制信号布线变长 → 整体拥塞。

> ⭐ **资源用量要纳入时序预算**，不能只看"容量够不够"。
> 判据：失败的端点里如果**不只有大扇出信号，连状态机的 CE 都挂了**，
> 那就是**全局布线压力**，加 `max_fanout` 治不了，只能降频或减资源。

---

## 五、时钟频率：PS7 的 FCLK 只能取特定值

Zynq 的 `FCLK = IO PLL(1000 MHz) ÷ DIV0 ÷ DIV1`，**必须是能整除出来的值**。

```tcl
CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {83.333}   # 1000 ÷ 4 ÷ 3
```

随便填非整数分频会被 Vivado **就近取整**，实际频率和你想的不一样。

> ⚠️ 相关坑：`PCW_M_AXI_GP0_FREQMHZ` 是**只读派生参数**且卡在 10，
> BD 生成时会刷一条 `Propagation TCL tries to overwrite USER strength parameter` 警告，**无害，忽略**。

---

## 六、打包 IP 时**不要**硬编码 `FREQ_HZ`

```tcl
# ❌ 错：为了让警告消失而写死频率
set_property value 100000000 [ipx::get_bus_parameters FREQ_HZ -of_objects $clk_if]
```

后果：**时钟频率从此不可改**。本项目后来为了时序收敛要把 FCLK 从 100 MHz 降到 83.333 MHz，
BD 生成直接失败：

```
ERROR: [BD 41-237] Bus Interface property FREQ_HZ does not match between
       /remap/aclk(100000000) and /ps7/FCLK_CLK0(83333336)
```

**正确做法**：**不设** `FREQ_HZ`，让 Block Design 从实际连上的时钟自动传播。
会多一条 `Clock interface 'aclk' has no FREQ_HZ parameter` 警告 —— **无害**。

> **教训：消警告的方法不该是硬编码一个值。**

---

## 七、其它零碎但会浪费半小时的

| 坑 | 现象 | 对策 |
|---|---|---|
| Windows 策略挡掉 `launch_simulation` | `compile.bat 不是内部或外部命令` | 注册表 `HKCU\Environment\NoDefaultCurrentDirectoryInExePath = 0` |
| Vivado 生成的 `.bat` 用 `exit` | 调用方整个退出 | 改成 `exit /b` |
| xsim 不接受 `-testplusarg` 里的盘符路径 | 参数传不进去 | 用相对路径 |
| `puts "  [OK] ..."` | `invalid command name "OK"` | 方括号在 Tcl 里是命令替换，提示文字里要转义 `\[OK\]` |
| XDC 里不能用 `remove_from_collection` | 报错 | XDC 只支持有限命令集 |
| `open_project` 刷一堆 `cannot add Board Part` | 一屏警告 | 无害，`set_msg_config -id {Board 49-26} -suppress` |

---

## 八、2026-10-30：两个"看起来像 RTL 有问题、其实是环境"的失败

> 同一次重新综合，连续两轮挂掉 2 个 IP。**两轮挂的是不同的 IP**，
> 而中间把 RTL 换回已知能过的版本也照样挂 ⇒ 问题不在设计。

### 8.1 工程路径太长 ⇒ IP 缓存路径超 Windows 260 字符

| 现象 | `Could not open 'C' for writing` + `tclapp::load_apps failed`，2 个 IP synthesis 失败 |
|---|---|
| 根因 | 工程路径 82 字符，**IP 缓存目录还要往下叠几层**，合计超过 MAX_PATH |
| 修法 | 把源码树挪到短路径（本例 82 → **33 字符**） |

**判据**：`Vivado 报的错指向 'C' 这种单字母文件名`，基本都是路径被截断，不是文件内容问题。

### 8.2 并行 OOC 综合抢同一个临时目录

| 现象 | 换短路径后**仍然随机挂 2 个 IP，且每轮挂的不同** |
|---|---|
| 根因 | `launch_runs synth_1 -jobs N` 的 N 个 OOC 子任务共用默认临时目录 |
| 修法 | 显式把 `TEMP`/`TMP` 指到独立短目录，并把并发从 8 降到 4；**改完要先 `reset_run synth_1`** |

**⭐ 最值钱的一条判据：「每次失败的是不同 IP」⇒ 环境争用，不是那个 IP 或你的 RTL。**
这一条能省掉一整轮"去查那个 IP 的代码"。

### 8.3 顺带：`archive_project` 导出的是**当前工程里的那份 RTL**

工程归档（`archive_project` 产出的 zip）里带的是 `.gen/.../ipshared/` 与 `.ipdefs/` 下的
**源码副本**。如果源码目录换过、工程是旧的，归档里就是**旧 RTL**，
而归档同时又带着某次实现的 bit —— **两者可能不同源，且不会有任何报错**。

**判据**：交付工程归档前，必须打开 zip 抽查关键 RTL 的**字节数/哈希**，
并与"部署用的 bit"对得上。只看 zip 能打开、能建工程是不够的。

---

## 九、来源与验证

| 内容 | 来源 |
|---|---|
| 路径从脚本自身推 / 布局自适应 | 交付包在队友机器上坏了 4 次 |
| `source_mgmt_mode None` | top 被自动改写 |
| 综合过≠实现过 | 实测 WNS 从"通过"变 -0.254 |
| FCLK 取值 | 降频时踩到 |
| 不硬编码 FREQ_HZ | BD 生成失败 |
| §8.1 路径超 260 字符 | 2026-10-30 重综合，`Could not open 'C'` 挂 2 个 IP |
| §8.2 并行 OOC 抢临时目录 | 同日，**每轮挂的 IP 不同** |
| §8.3 归档里是旧 RTL | 同日，交接包工程归档的 RTL 比部署 bit 旧一个版本 |

**全部来自"脚本在别人机器上跑不起来"或"改了参数就崩"的真实事故。**
