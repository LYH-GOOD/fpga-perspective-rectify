# 踩坑清单 · 总索引

> 全部来自本项目**真实踩过的失败**，每条都可追溯到 `report/llm_log/` 里的原始记录。
>
> **编号全局唯一且连续**，条目之间可直接用编号互相引用（如「见 #447」）。
>
> ⚠️ 本目录只放【通用】条目（换题换板仍可用）。**领域专属条目**在 [`project/pitfalls-domain.md`](project/pitfalls-domain.md)，两侧编号连续。
>
> 📦 **2026-11-01 拆分**：原先是一个 488 KB 的单文件（≈15 万 tokens，**任何模型都无法整体读取**），
> 现按主题拆成 8 个分册。**条目内容一字未改**，只是搬了位置；编号未变，跨条目引用仍然有效。

## 按症状快速定位

| 你遇到的症状 | 先看这册 |
|---|---|
| RTL 综合过了但上板不对 / 输出错位一格 / 时序不收敛 | [01-verilog-synth](pitfalls/01-verilog-synth.md) |
| 流式握手死锁 / valid-ready 反压 / 帧边界卡住 | [01-verilog-synth](pitfalls/01-verilog-synth.md) |
| Vivado 建工程失败 / IP 综合挂 / 路径报错 / BD 搭不起来 | [02-vivado-dma](pitfalls/02-vivado-dma.md) |
| AXI DMA 报错 / 长度超限 / BD 悬空 | [02-vivado-dma](pitfalls/02-vivado-dma.md) |
| 判据没抓住 bug / 修好了怎么证明 / 仿真与上板不一致 | [03-verification](pitfalls/03-verification.md) |
| 自检脚本自己坏了 / 检查通过了但不放心 / 配置漂移 | [04-guards](pitfalls/04-guards.md) |
| 帧率上不去 / 账对不上 / 优化完没效果 / 指标口径 / A/B 怎么做 | [05-measurement](pitfalls/05-measurement.md) |
| 交付包在别人机器上坏 / 合并队友代码 / 安装链哈希不匹配 | [06-pspl-delivery](pitfalls/06-pspl-delivery.md) |
| 版本管理 / 路径与正则 / Windows 运维 / 读第三方代码 | [07-misc](pitfalls/07-misc.md) |
| 单点判断力复盘（2026-10-25 之后） | [08-lessons](pitfalls/08-lessons.md) |

## 分册清单

| 分册 | 条目数 | 编号范围 | 大小 |
|---|---:|---|---:|
| [01-verilog-synth](pitfalls/01-verilog-synth.md) · Verilog / 综合 / 流式握手 | 28 | 5–141 | 8 KB |
| [02-vivado-dma](pitfalls/02-vivado-dma.md) · Vivado / AXI DMA / Block Design | 37 | 1–230 | 20 KB |
| [03-verification](pitfalls/03-verification.md) · 验证方法论与判据 | 59 | 42–422 | 40 KB |
| [04-guards](pitfalls/04-guards.md) · 检查与守卫自身的失效 | 63 | 173–383 | 85 KB |
| [05-measurement](pitfalls/05-measurement.md) · 性能测量与排查 | 158 | 38–395 | 155 KB |
| [06-pspl-delivery](pitfalls/06-pspl-delivery.md) · PS/PL 协同、合并与交付 | 37 | 41–450 | 35 KB |
| [07-misc](pitfalls/07-misc.md) · 杂项：版本管理 / 路径 / 运维 / 单点复盘（至 10-24） | 34 | 93–431 | 14 KB |
| [08-lessons](pitfalls/08-lessons.md) · 单点复盘与判断力（10-25 起） | 33 | 432–465 | 14 KB |

> `05-measurement` 较大（155 KB，性能测量是这包最厚的一册），建议**按关键词检索**而非通读。
