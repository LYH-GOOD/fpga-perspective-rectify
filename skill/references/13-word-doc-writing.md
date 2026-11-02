<!--
类型：自有
本文件是 fpga-project-development 自有的规范 —— 既没有上游副本，也不是路由。
规范参数提炼自 math-modeling 整合包里的 paper-formal-writer（见文末「来源」）。
-->

# Word 文档写作

## 为什么有这一条

用户的原始要求：

> **「你的这个 word 文档写得很乱，参考外部的 skill 数学建模整合的大 skill 整合包，使用其中的和 word 书写的 skill 并且加入当前 FPGA skill 整合包里。」**

**「乱」的根源不是内容，是做法。** 直接写 Python 拼 `add_paragraph`，排版参数散落在几十处调用里：
标题顺手用了蓝色、正文没有首行缩进、表格没边框没表头底色、字号一处一个样。
**同一份内容换个脚本重生成，排版就全变了。**

**解法：内容与排版分离。**

```text
① 写一份 Markdown 源文件  ← 只关心内容：什么标题、什么表格、什么顺序
② 跑一次渲染脚本          ← 只关心排版：字体/字号/缩进/边框，此处统一
③ 得到 .docx
```

改内容改 ①，改样式改 ②。**永远不要为了调一个字号去动内容文件。**

## 什么时候用

- 要产出一份**给人看的 Word 文档**（提醒单、使用说明、设计方案、答辩材料）。
- 已有一份 `.docx` 要统一排版。
- 要检查一份 `.docx` 的格式是否规范。

## 完整流程

### ① 写 Markdown 源

文件名约定：`<文档名>_source.md`，与最终 `.docx` 同目录。

**渲染器只认下面这几种语法**，写别的会被当正文：

| 你写的 | 渲染成 |
|---|---|
| `# 标题` / `## 标题` / `### 标题` | Heading 1 / 2 / 3（黑体 15 / 13 / 12 pt） |
| 普通一行文字 | 正文段（宋体 10.5 pt，首行缩进 0.74 cm） |
| `\| a \| b \|` 连续多行 | 表格（第一行自动当表头，加灰底） |
| ` ``` ` 包裹的块 | 代码块（Consolas 8.5 pt） |
| 单独一行 `$$` 包裹的块 | 公式块（Cambria Math 10.5 pt，居中） |
| `- 文字` 或 `* 文字` | 项目符号段（`•`，悬挂缩进） |
| `![图题](图片路径)` | 居中图片 + 图题 |
| 空行 | 段落分隔（**不产生空段落**） |

正文里的 `**粗体**`、`` `代码` ``、`[链接](url)` 会被**剥掉标记、只留文字**（不保留粗体效果）。

### ② 跑渲染脚本

**渲染器已经落地**，直接跑：

```bash
cd "<project-root>"
python tools/render_docx.py "<文档名>_source.md"
```

- 省略第二个参数时，`<文档名>_source.md` → 同目录 `<文档名>.docx`。
- 也可以显式指定输出：`python tools/render_docx.py a_source.md b.docx`。
- 跑完会打印 `标题 N ｜ 表格 N ｜ 图片 N ｜ 代码块 N`，**这四个数要和源文件对得上再往下走**。

`tools/render_docx.py` 是 `format_formal_docx.py` 渲染核心的独立化版本（去掉数模专用的 `main()` / `write_report()` / `*_index` / `read_csv_rows`，改成 CLI，并按坑 1 / 坑 6 修正了两处上游缺陷）。
**要调样式就改这个脚本顶部的常量块**（`FONT_BODY` / `SIZE_*` / `MARGIN` / `TABLE_*` / `INDENT_FIRST_LINE` / `LINE_SPACING`），不要去改 Markdown 源。

上游脚本原文（只读参考，**不要直接跑** —— 路径写死在数模的 `paper_output/` 里）：
`~/.claude/skills/math-modeling/references/mathmodel/skills/paper-formal-writer/scripts/format_formal_docx.py`

### ③ 验证

渲染完**必须回读**，确认不是空文件：

```bash
python -c "
import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document
d = Document(r'<路径>')
p = [x.text for x in d.paragraphs if x.text.strip()]
print('非空段落:', len(p), '| 表格:', len(d.tables))
for x in p[:8]: print(' ', x[:60])
"
```

段落数 / 表格数对得上、中文不乱码，才算过。

---

## 排版规范（照抄，别自由发挥）

**页面**：上下边距 `2.54 cm`，左 `2.8 cm`，右 `2.6 cm`

**正文**（Normal 样式）：

| 项 | 值 |
|---|---|
| 字体 | 宋体，10.5 pt |
| 首行缩进 | **0.74 cm**（= 2 字符） |
| 行距 | 1.35 |
| 段后 | 4 pt |
| 对齐 | **两端对齐**（JUSTIFY） |

**标题**（Heading 1/2/3）：

| 项 | 值 |
|---|---|
| 字体 | **黑体**，加粗 |
| 颜色 | **纯黑 `RGBColor(0,0,0)`** ⚠️ 不是蓝色、不是主题色 |
| 字号 | H1 `15` / H2 `13` / H3 `12` pt |
| 首行缩进 | **无**（必须显式设 `None`，否则继承 Normal 的缩进） |
| 段前/段后 | 10 pt / 6 pt |
| `keep_with_next` | `True`（标题不许孤零零留在页尾） |

**表格**：

| 项 | 值 |
|---|---|
| 表头底色 | `F2F2F2` |
| 边框 | 单线，颜色 `D9D9D9`，粗细 `6` |
| 单元格内边距 | `90` twips（四边） |
| 字号 | 9 pt；表头加粗 |
| 垂直对齐 | 居中 |
| 水平对齐 | 内容 **≤16 字符→居中**，否则左对齐 |
| 表题 | 放在表格**上方**，居中、加粗 |

**代码块**：Consolas `8.5 pt`，左缩进 0.4 cm，右缩进 0.2 cm
**公式块**：Cambria Math `10.5 pt`，居中
**列表项**：左缩进 0.74 cm，悬挂缩进 `-0.25 cm`，前缀 `• `

## 图表四段式（不许只贴图不解释）

```text
正文引导句      ← 说明这张图表是干什么的
（图 / 表）     
图表解释段      ← 读出了什么
结论回扣句      ← 说明这对结论意味着什么
```

表格同理：**表格前说明用途，表格后解释规律**。列名要短而明确。

## 六个已知坑

**坑 1 —— 中文字体必须设三处，少一处就渲染成方框/宋体。**
`run.font.name` 只管西文，中文要单独设 `rFonts` 的 `w:eastAsia`：

```python
run.font.name = "黑体"
run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "黑体")
```

⚠️ `get_or_add_rPr()` 不能写成 `run._element.rPr` —— 后者在 rPr 还没创建时是 `None`，直接 `.rFonts` 会 `AttributeError`。

**坑 2 —— `1. 文字` 会被误判成标题。**
渲染器有条规则：行首匹配 `^(?:\d+\.){0,2}\d+\s+` 且整行 ≤80 字符 → 当标题。
所以 **正文里不要用 `1. 2. 3.` 开头**，要用 `- `（项目符号）或中文编号（`①`、`第一步`）。
`5.1 小节名` 这种是**故意**的，会被正确地渲染成二级标题。

**坑 3 —— 标题最多 3 级。** `####` 及以下会被**压到 3 级**，层级信息丢失。

**坑 4 —— 表格列宽不由 `|` 里的空格数决定。** 渲染器按内容自适应；要固定列宽得渲染后单独设 `cell.width`。

**坑 5 —— 不支持嵌套列表和有序列表。** `  - 子项` 会被当普通正文。

**坑 6 —— `w:tcPr` 的子元素必须按 schema 顺序插入，不能用 `append()`。**
⚠️ **上游 `format_formal_docx.py` 有这个问题，本项目脚本已修正。** 上游的
`set_cell_shading()` / `set_cell_borders()` / `set_cell_margin()` 全都用 `tc_pr.append(...)`，
而 `cell.vertical_alignment = ...` 会先创建 `w:vAlign` —— 结果 `tcBorders`/`shd`/`tcMar`
全部排在 `vAlign` **后面**，违反 OOXML schema。

正确顺序（`CT_TcPr`）：

```text
tcW, gridSpan, hMerge, vMerge, tcBorders, shd, noWrap, tcMar,
textDirection, tcFitText, vAlign, hideMark
```

`python-docx` 只给 `tcW` / `gridSpan` / `vMerge` / `vAlign` 提供了有序插入（`get_or_add_*`），
其余三个要自己定位：

```python
def _tcpr_child(tc_pr, tag_name):
    element = tc_pr.find(qn(f"w:{tag_name}"))
    if element is not None:
        return element
    element = OxmlElement(f"w:{tag_name}")
    successors = tuple(f"w:{n}" for n in TCPR_ORDER[TCPR_ORDER.index(tag_name) + 1:])
    tc_pr.insert_element_before(element, *successors)   # ← 关键：不是 append
    return element
```

⚠️ **诚实边界**：我方只验证到「修正前顺序违反 schema、修正后全部单元格合 schema」。
**"违反顺序时 Word 是否真的弹修复提示"没有实测过**（本机没有可无头驱动的 Word / LibreOffice）。
不要对外说"Word 一定打不开"。

## 格式自查清单

交付前逐条过：

- [ ] 标题颜色是**黑**的（不是蓝的、不是主题色）
- [ ] 正文有首行缩进，且标题**没有**
- [ ] 表格有表头底色和边框
- [ ] 表格单元格 `tcPr` 子元素顺序合 schema（坑 6）
- [ ] 没有 `####` 以下的标题被压平
- [ ] 正文里没有 `1. ` 开头的行（会被误判成标题）
- [ ] 每张图/表都有引导句和解释段
- [ ] 回读验证：段落数、表格数对得上，中文不乱码
- [ ] **没有 `TODO` / `XXX` / `待补` / `占位符` 残留**

## 来源

| 来源 | 取用了什么 |
|---|---|
| `math-modeling/references/mathmodel/skills/paper-formal-writer/` | 全部排版参数、渲染器结构、图表四段式 |
| 其中 `scripts/format_formal_docx.py`（478 行） | 渲染核心 + 全部排版常量。⚠️ **两处上游缺陷已在本项目修正**：① `apply_run_font` 用 `run._element.rPr` 会在 rPr 缺失时 `AttributeError`（见坑 1）；② 表格元素用 `append()` 导致 `tcPr` 顺序违规（见坑 6） |
| 其中 `references/figure-table-writing-rules.md` | 图表四段式 |
| 其中 `references/cumcm-paper-standard.md` 等 3 份 | ⛔ **未取用** —— 国赛论文骨架，对本项目不适用 |

**没搬进来的**（刻意）：国赛章节骨架（`1 问题重述 / 2 问题分析 / 3 模型假设 / 4 符号说明…`）、
18000 字门禁、证据门禁、`paper_output/` 目录契约、MathModel 十子技能工作流。
**本项目要的是"怎么把 Word 排整齐"，不是"怎么写数模论文"。**

上游目录仍然在磁盘上，需要时可直接读：
`~/.claude/skills/math-modeling/references/mathmodel/skills/paper-formal-writer/`
