#!/usr/bin/env python3
"""把版本化模块按依赖层合并成 6 个文件。

设计要点：
  * 只用 AST 计算位置，改的是原文本 —— 注释和排版逐字保留，不走 ast.unparse。
  * 同一层内重名的顶层名字一律加 "__<原模块名>" 后缀，调用点按 from X import 的来源同步改。
  * 函数级 import 同样处理（工程里共 537 处），否则合并后模块名不存在、板上直接崩。
  * import X as Y 的模块对象用法精确展开成名字；写属性时补 global，避免变成局部变量。
  * 字符串字面量一律不动（工程里 v86_motion_frames 这类是日志字段名，不是 import）。
  * 报告与屏幕输出逐字相同，每笔 write 都 flush，失败路径全文不截断。
"""
import ast
import collections
import datetime
import hashlib
import platform
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "ps"
OUT = REPO / "_merge_out"
REPORT = REPO / "build" / "reports" / "merge_layers_report.txt"

# 文件依赖顺序：core < geometry < tracking < ui < display < ai（已实测无反向边）
LAYERS = [
    ("core", "core.py", [
        "p11_contract", "run_logging", "v31_crash", "v31_diagnostics",
        "v31_gc_budget", "v31_pixels", "v84_prebuilt", "v94_audit"]),
    ("geometry", "geometry.py", [
        "find_homography", "p1_paper_quad", "pl_fields", "v8_geometry", "v8_plan",
        "v8_surface", "v8_tables", "v10_quad", "v14_planner", "v41_quad", "v45_color",
        "v48_candidates", "v49_boundary", "v50_orientation", "v51_target",
        "v62_boundary", "v62_exterior", "v62_policy", "v84_color", "v85_boundary",
        "v85_candidates", "v86_candidates"]),
    ("tracking", "tracking.py", [
        "v31_detection", "v31_tracking", "v31_startup", "v58_budget", "v58_recovery",
        "v67_observation", "v68_stability", "v69_policy", "v78_localization",
        "v79_acquire", "v79_setup", "v80_cache", "v81_evidence", "v83_recovery",
        "v86_policy", "v86_tracking", "v87_acquire", "v87_v74_tracking", "v88_motion",
        "v88_recovery", "v90_lk", "v91_policy", "v107_policy", "v31_native",
        "v87_v74_native", "v90_transaction", "v91_native", "v105_native"]),
    ("display", "display.py", [
        "v31_camera", "v64_camera_hdmi", "v64_hdmi_display", "v64_io",
        "v64_p1_backend", "v70_hdmi_timing", "v70_ps", "v71_display", "v73_ratio",
        "v73_ratio_ui", "v74_hold", "v741_reading", "v76_snapshot"]),
    ("ai", "ai.py", [
        "v98_ai_geometry", "v98_ai_request", "v98_ai_worker", "v99_ai_protocol",
        "v99_ai_selftest", "v99_ai_service", "v99_ai_ui", "v99_ai_worker"]),
]
UI_EXCLUDE = set(sum((m for _, _, m in LAYERS), []))

_REPORT = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def _target_names(t):
    """赋值左值可能是元组/列表解包（NX,NY=7,5），要递归展开。"""
    if isinstance(t, ast.Name):
        return {t.id}
    if isinstance(t, (ast.Tuple, ast.List)):
        return set().union(*[_target_names(e) for e in t.elts]) if t.elts else set()
    if isinstance(t, ast.Starred):
        return _target_names(t.value)
    return set()


def top_level_defs(tree):
    out = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                out |= _target_names(t)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
    return out


def sorted_topologically(names, deps):
    order, seen, stack = [], set(), set()

    def visit(n):
        if n in seen:
            return True
        if n in stack:
            return False
        stack.add(n)
        for d in sorted(deps.get(n, ())):
            if d in names and d != n and not visit(d):
                return False
        stack.discard(n)
        seen.add(n)
        order.append(n)
        return True

    for n in names:
        if not visit(n):
            return None
    return order


class Merger:
    def __init__(self):
        self.layer_of = {}
        for layer, _fn, mods in LAYERS:
            for m in mods:
                self.layer_of[m] = layer
        all_mods = {}
        for sub in ("core", "ui"):
            for p in sorted((SRC / sub).glob("*.py")):
                all_mods[p.stem] = p
        self.ui_mods = [m for m in all_mods if m not in UI_EXCLUDE]
        for m in self.ui_mods:
            self.layer_of[m] = "ui"
        self.LAYERS = LAYERS + [("ui", "ui.py", self.ui_mods)]
        self.FILES = {layer: fn for layer, fn, _ in self.LAYERS}
        self.sources, self.trees, self.defs = {}, {}, {}
        for m in self.layer_of:
            p = all_mods[m]
            self.sources[m] = p.read_bytes()
            self.trees[m] = ast.parse(self.sources[m].decode("utf-8"), filename=str(p))
            self.defs[m] = top_level_defs(self.trees[m])
        self.rename, self.collisions = {}, []
        for layer, _fn, mods in self.LAYERS:
            byname = collections.defaultdict(set)
            for m in mods:
                for n in self.defs[m]:
                    if n != "_SOURCE_SHA256":
                        byname[n].add(m)
            for n, who in sorted(byname.items()):
                if len(who) > 1:
                    self.collisions.append((layer, n, sorted(who)))
                    for m in who:
                        self.rename[(m, n)] = n + "__" + m

    def resolve(self, mod, name, _seen=None):
        """顺着再导出链找到这个名字真正的定义模块（v82_interaction.checkpoint 实际来自 run_logging）。"""
        _seen = _seen if _seen is not None else set()
        key = (mod, name)
        if key in _seen:
            return None
        _seen.add(key)
        if name in self.defs[mod]:
            return (mod, name)
        for n in self.trees[mod].body:
            if isinstance(n, ast.ImportFrom) and n.module in self.layer_of:
                for a in n.names:
                    if (a.asname or a.name) == name:
                        return self.resolve(n.module, a.name, _seen)
        return None

    def final_name(self, mod, name):
        return self.rename.get((mod, name), name)

    def module_deps(self, mod):
        # 只按「顶层」import 排序：函数内的 import 是惰性的，运行到才需要，
        # 不参与文件内顺序；把它们算进来会造出假环。
        deps = set()

        def walk(n):
            for c in ast.iter_child_nodes(n):
                # 函数/类体内的 import 是惰性的，不算加载期依赖
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if isinstance(c, ast.ImportFrom) and c.module in self.layer_of:
                    deps.add(c.module)
                elif isinstance(c, ast.Import):
                    for a in c.names:
                        if a.name in self.layer_of:
                            deps.add(a.name)
                walk(c)

        walk(self.trees[mod])
        return deps

    def transform(self, mod):
        text = self.sources[mod].decode("utf-8")
        lines = text.split("\n")
        layer = self.layer_of[mod]
        tree = self.trees[mod]
        drop = set()
        cross, hoist, warns = [], [], []
        alias = {}
        module_alias = {}
        need_global = collections.defaultdict(set)

        parents = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parents[c] = n

        def enclosing_func(node):
            p = parents.get(node)
            while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                p = parents.get(p)
            return p

        # ---- 第 1 遍：处理所有 import（顶层 + 函数内）----
        # 两种情形必须分开：
        #   同层（含自引用）—— 语句删掉，引用直接改名。名字本来就在本文件的全局作用域里。
        #   跨层          —— 语句必须原样留下，只把模块名换成层文件名，再 alias 回原来的局部名。
        #                    跨层的名字不在本文件里，删掉就变成 NameError（2026-11-02 踩过：
        #                    v73_ratio 里 `from v50_orientation import DualOrientation as
        #                    OriginalOrientation`，v50_orientation 在 geometry 层，
        #                    alias 把 OriginalOrientation 改写成了本文件不存在的 DualOrientation）。
        rewrite = {}           # 跨多行：行号(0 基) -> (结束行号, 替换文本)
        inline_rewrites = []   # 单行：与原文本列区间对齐，避开 `a();import x` 这种行内前缀

        def put_rewrite(node, keep):
            if node.lineno == node.end_lineno:
                inline_rewrites.append((node.lineno - 1, node.col_offset,
                                        node.end_col_offset, "; ".join(keep)))
            else:
                text = "\n".join(" " * node.col_offset + k for k in keep)
                rewrite[node.lineno - 1] = (node.end_lineno, text)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in self.layer_of:
                lazy = enclosing_func(node) is not None
                keep = []
                for a in node.names:
                    res = self.resolve(node.module, a.name)
                    if res is None:
                        warns.append(f"{mod}:{node.lineno} from {node.module} import {a.name} —— 找不到定义")
                        continue
                    target_mod, target_name = res
                    target = self.final_name(target_mod, target_name)
                    local = a.asname or a.name
                    if target_mod == mod or self.layer_of[target_mod] == layer:
                        if alias.get(local, target) != target:
                            warns.append(f"{mod}:{node.lineno} {local} 指向两个不同目标 {alias[local]} / {target}")
                        alias[local] = target
                    else:
                        lname = self.layer_of[target_mod]
                        keep.append(f"from {lname} import {target} as {local}")
                        cross.append((lname, target, local, lazy))
                if keep:
                    put_rewrite(node, keep)
                else:
                    for ln in range(node.lineno - 1, node.end_lineno):
                        drop.add(ln)
            elif isinstance(node, ast.Import):
                if not any(a.name in self.layer_of for a in node.names):
                    # 与项目无关的 import：模块级提到文件头，函数内的原样不动
                    if node.col_offset == 0:
                        hoist.append("\n".join(lines[node.lineno - 1:node.end_lineno]))
                        for ln in range(node.lineno - 1, node.end_lineno):
                            drop.add(ln)
                    continue
                keep = []
                for a in node.names:
                    if a.name not in self.layer_of:
                        keep.append("import " + a.name + (f" as {a.asname}" if a.asname else ""))
                        continue
                    local = a.asname or a.name
                    lname = self.layer_of[a.name]
                    if lname == layer:
                        module_alias[local] = a.name
                    else:
                        keep.append(f"import {lname} as {local}")
                        cross.append((lname, a.name, local, enclosing_func(node) is not None))
                if keep:
                    put_rewrite(node, keep)
                else:
                    for ln in range(node.lineno - 1, node.end_lineno):
                        drop.add(ln)
            elif isinstance(node, ast.ImportFrom) and node.col_offset == 0:
                hoist.append("\n".join(lines[node.lineno - 1:node.end_lineno]))
                for ln in range(node.lineno - 1, node.end_lineno):
                    drop.add(ln)

        for n in self.defs[mod]:
            if (mod, n) in self.rename:
                alias[n] = self.rename[(mod, n)]

        # ---- 第 2 遍：算出所有替换（行内列区间）----
        cur_file = Path(self.FILES[layer]).stem   # 本模块合并后所在的层文件名，如 'display'
        replacements = list(inline_rewrites)   # (line, c0, c1, newtext)
        covered = [(ln, c0, c1) for ln, c0, c1, _ in inline_rewrites]  # 已替换区间，防止二次编辑
        for node in ast.walk(tree):
            base = None
            dyn = False
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name) and node.value.func.id == "__import__"
                    and len(node.value.args) == 1 and isinstance(node.value.args[0], ast.Constant)
                    and node.value.args[0].value in self.layer_of):
                base = node.value.args[0].value
                dyn = True
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id in module_alias:
                base = module_alias[node.value.id]
            if base is None:
                continue
            res = self.resolve(base, node.attr)
            if res is None:
                warns.append(f"{mod}:{node.lineno} {base}.{node.attr} —— 找不到定义")
                continue
            new = self.final_name(*res)
            if node.lineno != node.end_lineno:
                warns.append(f"{mod}:{node.lineno} {base}.{node.attr} 跨行，未处理")
                continue
            #   ⛔ 2026-11-02 板上实炸：`__import__('p11_contract').LINE_BUF_ROWS` 被折叠成裸名，
            #      但 v64_p1_backend 里根本没有 `from p11_contract import LINE_BUF_ROWS`
            #      （作者是故意动态取的）⇒ 合并后函数内 NameError。
            #      跨层时**只改模块名字符串**，保持动态导入的形式，裸名一律不造。
            #      （同层可以折叠：名字就在本文件顶层，函数里能按 LEGB 找到。）
            tgt_file = Path(self.FILES[self.layer_of[res[0]]]).stem
            if dyn and tgt_file != cur_file:
                arg = node.value.args[0]
                replacements.append((arg.lineno - 1, arg.col_offset, arg.end_col_offset,
                                     repr(tgt_file)))
                covered.append((arg.lineno - 1, arg.col_offset, arg.end_col_offset))
                continue
            replacements.append((node.lineno - 1, node.col_offset, node.end_col_offset, new))
            covered.append((node.lineno - 1, node.col_offset, node.end_col_offset))
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                fn = enclosing_func(node)
                if fn is not None:
                    need_global.setdefault(id(fn), (fn, set()))[1].add(new)

        def inside(ln, c):
            return any(l == ln and a <= c < b for l, a, b in covered)

        def hit_span(node_line, from_col, word):
            """在指定行里找到标识符的真实字节区间（def/class 名、global 名都是字符串字段，不是 ast.Name）。"""
            if node_line - 1 >= len(lines) or node_line != node_line:
                return None
            data = lines[node_line - 1].encode("utf-8")
            w = word.encode("utf-8")
            i = data.find(w, from_col)
            if i < 0:
                return None
            # 前后必须是边界，避免把 foo 命中到 foobar 里
            if i > 0 and (data[i - 1:i][0] in b"_0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"):
                return None
            j = i + len(w)
            if j < len(data) and (data[j:j + 1][0] in b"_0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"):
                return None
            return (i, j)

        # def / class 的名字必须跟着改名，否则定义和引用对不上
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    and (mod, node.name) in self.rename:
                sp = hit_span(node.lineno, node.col_offset, node.name)
                if sp is None:
                    warns.append(f"{mod}:{node.lineno} 找不到定义名 {node.name} 的位置")
                    continue
                replacements.append((node.lineno - 1, sp[0], sp[1], self.rename[(mod, node.name)]))
                covered.append((node.lineno - 1, sp[0], sp[1]))
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                for nm in node.names:
                    if nm in alias:
                        sp = hit_span(node.lineno, node.col_offset, nm)
                        if sp:
                            replacements.append((node.lineno - 1, sp[0], sp[1], alias[nm]))
                            covered.append((node.lineno - 1, sp[0], sp[1]))

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in alias and not inside(node.lineno - 1, node.col_offset):
                replacements.append((node.lineno - 1, node.col_offset, node.end_col_offset, alias[node.id]))

        # ---- 第 3 遍：补 global 声明 ----
        inserts = collections.defaultdict(list)
        for fn, names in need_global.values():
            names = sorted(names)
            first = fn.body[0]
            at = first.lineno - 1
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                at = first.end_lineno
            indent = " " * (fn.body[0].col_offset if fn.body else 4)
            inserts[at].append(f"{indent}global {', '.join(names)}")

        # ---- 第 4 遍：落到文本 ----
        out_lines = []
        by_line = collections.defaultdict(list)
        for ln, c0, c1, new in replacements:
            by_line[ln].append((c0, c1, new))
        ln = 0
        while ln < len(lines):
            for ins in inserts.get(ln, []):
                out_lines.append(ins)
            if ln in rewrite:
                end_ln, text = rewrite[ln]
                out_lines.append(text)
                ln = end_ln
                continue
            if ln in drop:
                ln += 1
                continue
            raw = lines[ln]
            if ln not in by_line:
                out_lines.append(raw)
                ln += 1
                continue
            data = raw.encode("utf-8")
            for c0, c1, new in sorted(by_line[ln], reverse=True):
                data = data[:c0] + new.encode("utf-8") + data[c1:]
            out_lines.append(data.decode("utf-8"))
            ln += 1
        body = "\n".join(out_lines).strip("\n")
        while "\n\n\n\n" in body:
            body = body.replace("\n\n\n\n", "\n\n\n")
        return body, cross, hoist, warns

    def merge_layer(self, layer, fn, mods):
        order = sorted_topologically(mods, {m: self.module_deps(m) for m in mods})
        if order is None:
            raise RuntimeError(f"{layer} 层内模块级依赖有环，无法排序")
        cross, hoist, bodies, warns = [], [], [], []
        for m in order:
            body, c, h, w = self.transform(m)
            cross += c
            hoist += h
            warns += w
            bodies.append((m, body))
        seen, head = set(), []
        for h in hoist:
            if h not in seen:
                seen.add(h)
                head.append(h)
        # 跨层 import 现在原地保留（见 transform 第 1 遍），不再往文件头搬 ——
        # 搬到文件头会把「函数内惰性 import」变成加载期依赖，造出假环。
        parts = [f'"""{layer} —— 合并层，含 {len(order)} 个原始模块。\n\n'
                 f'本文件由 build/merge_layers.py 生成，不要直接编辑。\n'
                 f'每个原始模块的边界见下方 "# ===== [NN/MM] 模块名 =====" 分节标记。\n"""',
                 "from pathlib import Path\nimport hashlib"]
        if head:
            parts.append("\n".join(head))
        parts.append("_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()")
        for i, (m, body) in enumerate(bodies, 1):
            parts.append(f"# {'=' * 70}\n# ===== [{i:02d}/{len(order):02d}] {m} =====\n# {'=' * 70}")
            parts.append(body)
        return "\n\n\n".join(parts) + "\n", order, warns


def main():
    global _REPORT
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = open(REPORT, "w", encoding="utf-8", newline="\n")
    for h in [
        "=" * 70,
        "  merge_layers.py —— 把版本化模块按依赖层合并成 6 个文件",
        "=" * 70,
        f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"机器   : {platform.node()} / {platform.platform()}",
        f"Python : {sys.version.split()[0]}",
        f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
        f"仓库   : {REPO}",
        "=" * 70,
        "",
    ]:
        log(h)
    try:
        mg = Merger()
        log(f"[1] 读入 {len(mg.layer_of)} 个模块")
        for layer, fn, mods in mg.LAYERS:
            log(f"    {layer:9s} {fn:12s} {len(mods):3d} 个模块")
        log("")
        log(f"[2] 层内重名 {len(mg.collisions)} 处，全部按 <名字>__<原模块> 改名")
        per = collections.Counter(c[0] for c in mg.collisions)
        for layer, _fn, _mods in mg.LAYERS:
            if per.get(layer):
                log(f"    {layer:9s} {per[layer]:3d} 处")
        log("")
        log("[3] 开始生成")
        OUT.mkdir(parents=True, exist_ok=True)
        total_warn = 0
        for layer, fn, mods in mg.LAYERS:
            text, order, warns = mg.merge_layer(layer, fn, mods)
            (OUT / fn).write_bytes(text.encode("utf-8"))
            total_warn += len(warns)
            log(f"    {fn:12s} {len(text.splitlines()):6d} 行 "
                f"{len(text.encode()):9,d} B  模块顺序: {', '.join(order[:4])}"
                f"{' ...' if len(order) > 4 else ''}")
            for w in warns:
                log(f"      ! {w}")
        log("")
        log(f"[4] 完成，警告 {total_warn} 条")
        log(f"[5] 输出目录: {OUT}")
        log("")
        log("RESULT: OK")
        return 0
    except Exception:
        log("")
        log("[!!] 失败，完整堆栈如下（不截断）：")
        log(traceback.format_exc())
        log("RESULT: FAIL")
        return 1
    finally:
        _REPORT.close()


if __name__ == "__main__":
    sys.exit(main())
