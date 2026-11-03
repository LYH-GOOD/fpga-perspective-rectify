---
name: fpga-image-rectification
description: >
  Domain-layer knowledge from a real PYNQ-Z2 (XC7Z020) streaming image-rectification
  project: streaming image geometry remapping (homography + bilinear interpolation on
  a line-buffer pipeline), single-view plane geometry (focal length from a known
  rectangle, camera-to-plane distance), adaptive quad detection under motion, and the
  AI-assisted RTL workflow used to build it. Use when the user asks to
  "倾斜拍正", "平面校正", "透视校正", "单应矩阵怎么算", "焦距怎么标定",
  "行缓存怎么设计", "双线性插值流水线", "四角检测跳变", "文档边缘检测",
  or mentions "image rectification", "homography", "perspective correction",
  "streaming remap", "line buffer architecture", "bilinear interpolation pipeline",
  "single-view metrology", "quad detection stability", "focal length calibration",
  "camera to plane distance", "preview scaling", "display slot does not fit",
  "预览缩放", "源图放不进显示区", "缩放很慢",
  "AI 和传统方法怎么分工", "候选验证", "跟踪丢失", "标注复核", "增量训练".
  Also use when a scanned/photographed document must be
  flattened in real time, or when a planar object's real-world size must be measured
  from a single camera.
  ⚠️ This skill is BOUND to this project's topic. For reusable, board-agnostic FPGA
  knowledge (stream handshake, Vivado toolchain, verification methodology,
  measurement discipline, mechanical guards), use the parent skill
  `fpga-pynq-engineering` in `../SKILL.md` instead.
argument-hint: "[领域关键词，例如 \"单应矩阵\" 或 \"四角检测跳变\"]"
metadata:
  version: "1.1.0"
  layer: "domain (题型绑定)"
  parent-skill: "../SKILL.md  (fpga-pynq-engineering —— 通用层)"
---

# 平面图像校正 · 领域 Skill

## Purpose

本项目（**倾斜拍摄 → 自动校正为正视图**）的**领域层知识**：
流式图像几何变换怎么设计、单目视觉怎么测真实尺寸、自适应检测怎么才稳。

**Expected outcome：** 同类型题目（流式图像几何变换 / 单目视觉平面测量）可直接复用；
**换成别的题目则用不上** —— 那种情况请用 [通用层 `../SKILL.md`](../SKILL.md)。

**Prerequisites：** 无（纯文档）。

---

## ⭐ 与通用层的分工

| 你要解决的问题 | 看哪 |
|---|---|
| **流式握手怎么写才不死锁 / Vivado 脚本 / 验证判据 / 测量口径 / 配置防漂移** | **通用层** [`../SKILL.md`](../SKILL.md) → `../references/generic/`（8 篇）|
| **单应矩阵 / 行缓存架构 / 单目测距 / 四角检测** | **本层**（下表的 `references/`）|
| **踩坑清单** | 通用条目在 [`../pitfalls.md`](../pitfalls.md)；**领域条目在本目录 [`pitfalls-domain.md`](pitfalls-domain.md)**（两侧编号连续）|

> **原则：本层【引用】通用层，不复制它。** 避免"副本漂移"（`pitfalls` #93~#97）。

---

## When to Use

- 要把**倾斜拍摄的平面**（文档 / 白板 / 方格纸）**校正为正视图**
- 要算 **单应矩阵**、设计**流式图像几何变换**（行缓存 + 双线性插值）
- 要从**单张图**测平面目标的**真实尺寸**（焦距标定 / 相机到平面距离）
- **自适应四角检测**在连续帧里**跳变**，要找稳定方案
- 用大模型辅助写这一类的 RTL / PS 代码（`references/prompts/`）

## When NOT to Use

- **不是平面**（曲面 / 3D 物体）⇒ 单应矩阵不成立，本层无效
- **倾角 > 60°** ⇒ 透视畸变过大、行缓存行数暴增，需先降级（见项目 `CLAUDE.md`）
- **纯空白表面** ⇒ 检测的已知弱点，本层帮不上
- **只想学 FPGA / Vivado 通用知识** ⇒ 用**通用层**，不是这里

---

## 目录

| 文件 | 内容 | 为什么有用 |
|---|---|---|
| [`references/domain/01-streaming-image-remap.md`](references/domain/01-streaming-image-remap.md) | **流式图像几何变换的架构**（框图可照搬） | 非流式（整帧缓冲）做法在视频上必崩 |
| [`references/domain/02-single-view-geometry.md`](references/domain/02-single-view-geometry.md) | **单目视觉平面测量**：焦距标定 + 平面测距公式 | 公式可直接用；本项目实测 4 个角度误差 24% |
| [`references/domain/03-preview-scaling.md`](references/domain/03-preview-scaling.md) | **预览缩放**：源图放不进显示槽时的三条路，以及为什么"最近邻 + 定数模式"最快 | 缩放常被当成小事，实测能占满一帧时间 |
| [`references/prompts/ai-assisted-rtl-workflow.md`](references/prompts/ai-assisted-rtl-workflow.md) | **AI 辅助写 RTL/PS 的提示词工作流** | 提示词模板可直接套 |
| [`references/templates/`](references/templates/README.md) | 案例模板（脚本改路径就能用） | 新题目起步 |
| [`references/domain/04-ai-traditional-tracking.md`](references/domain/04-ai-traditional-tracking.md) | **AI 与传统方法的分工**：候选生成 → 验证 → 跟踪的三段式 | 几何法在杂乱/遮挡下失效时 | 多书、同色背景仍需实测 |
| [`references/domain/05-human-reviewed-labels.md`](references/domain/05-human-reviewed-labels.md) | **人工复核标注流程**：确认后训练、冻结原标注与评估划分 | 要做增量训练时 | 不附训练集与权重 |
| [`pitfalls-domain.md`](pitfalls-domain.md) | **领域踩坑**（流式图像重映射 / 单视图几何） | 与通用清单编号连续 |

---

## ⭐ 2026-10-31 补充：多档位输入与"真正的瓶颈"

### 双分辨率输入（同一比特流）

- 传感器侧提供 640×480 与 800×600 两档，**校正核不用改**（吞吐 4.686 拍/像素，余量 1.9×）
- 但 **800×600 放不进 640×480 的显示槽** ⇒ 600P 每帧都要缩放，480P 是 1:1
- **实测：600P 的预览转换 77.2 ms，480P 只要 10.8 ms** —— 7 倍差距，全部来自缩放
- 优化后 600P 降到 **17.6 ms**，处理帧率 15.9 → **16.46 fps（达相机 16.67 上限）**
- ⇒ 详见 [`references/domain/03-preview-scaling.md`](references/domain/03-preview-scaling.md)

### 瓶颈的迁移顺序（这条比具体数字重要）

| 阶段 | 瓶颈 | 判据 |
|---|---|---|
| 优化前 | **PL 校正核** | `dma_wait_s` ≫ 理论地板（185,344 px × 4.686 clk / 83.33 MHz = 10.42 ms） |
| 核提速后 | **PS 解算/跟踪** | `tracker_s` 长尾（某些模式 124 ms/帧） |
| 现在 | **显示线程合成** | 并排模式 `compose_s` 39–45 ms，`current_display_fps_2s` 17 fps |

**⭐ 教训**：每优化一轮，"瓶颈"就会搬家。
**下一轮该优化哪里，必须重新量**，不能沿用上一轮的结论
（详见通用层 `../references/generic/07` §十 的 10.5：内部指标变好 ≠ 用户指标变好）。

**通用层**（换题换板仍可用，**竞赛单独加分**）在 [`../SKILL.md`](../SKILL.md)：
`../references/generic/` 8 篇 + [`../pitfalls.md`](../pitfalls.md) + `../scripts/` + `../examples/`。

---

## 来源与版本

| 项 | 值 |
|---|---|
| 来源 | PYNQ-Z2 平面图像自适应校正项目（2026-09-23 起）**真实开发过程** |
| 格式对标 | **AMD ROSS 官方 Skill 包**（2026-09）|
| 本版 | v1.1.0（2026-11-01）。上次 2026-10-03；本次新增 `references/domain/03-preview-scaling.md`、补"多档位输入与真正的瓶颈"一节 |
