#!/usr/bin/env python3
"""证明合并后的每一行代码都还在、且只改了名字。

做法：把合并文件按分节标记切回 114 段，对每段和原模块各建一棵 AST，
把「原模块」那棵按合并器的改名规则归一化，再逐条顶层语句比 ast.dump。

为什么不用字节码：删掉 import 会改变 Python 3.14 的字节码生成（PUSH_NULL），
bytecode 一定有差异，反而掩盖真正的问题。AST 比的是代码结构本身。

归一化（两边都做）：
  * 丢掉项目内的 import —— 同层的被删、跨层的被改写成 from <层> import
  * 丢掉模块级非项目 import —— 它们被提到文件头了
  * 丢掉 global 声明 —— 合并器会补插，原模块没有
归一化（只对原模块做）：
  * 按改名表换 Name / def / class / global 里的名字
  * 模块对象用法 `vXX.attr` 换成最终名字

    python build/verify_merge.py
"""
import ast
import datetime
import hashlib
import importlib.util
import io
import platform
import re
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "_merge_out"
REPORT = REPO / "build" / "reports" / "verify_merge_report.txt"
BANNER = re.compile(r"^# ===== \[\d+/\d+\] (\w+) =====$", re.M)

_REPORT = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


class DropProjectImports(ast.NodeTransformer):
    """去掉项目内 import（含函数内的）；跨层改写后的 from <层> import 也一并去掉。

    非项目 import（os/numpy/cv2…）保留 —— 那部分两边必须一模一样。
    """

    def __init__(self, layer_of, layer_files):
        self.layer_of = layer_of
        self.layer_files = layer_files

    def visit_ImportFrom(self, node):
        if node.module in self.layer_of or node.module in self.layer_files:
            return None
        return node

    def visit_Import(self, node):
        if any(a.name in self.layer_of or a.name in self.layer_files for a in node.names):
            return None
        return node


def normalize_module_scope(tree, layer_of):
    """模块级非项目 import 已被提到文件头，原模块这边去掉。"""
    keep = []
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        keep.append(n)
    tree.body = keep


class DropGlobal(ast.NodeTransformer):
    def visit_Global(self, node):
        return None


class Rename(ast.NodeTransformer):
    def __init__(self, names, aliases, module_alias, resolver, layer_of,
                 cur_file=None, stem_of=None):
        self.names = names
        self.aliases = aliases
        self.module_alias = module_alias
        self.resolver = resolver
        self.layer_of = layer_of
        self.cur_file = cur_file
        self.stem_of = stem_of or {}

    def visit_Name(self, node):
        if node.id in self.aliases:
            node.id = self.aliases[node.id]
        elif node.id in self.names:
            node.id = self.names[node.id]
        return node

    def visit_FunctionDef(self, node):
        if node.name in self.names:
            node.name = self.names[node.name]
        self.generic_visit(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        if node.name in self.names:
            node.name = self.names[node.name]
        self.generic_visit(node)
        return node

    def visit_Attribute(self, node):
        base = node.value
        target = None
        if isinstance(base, ast.Name) and base.id in self.module_alias:
            target = self.resolver(self.module_alias[base.id], node.attr)
        elif (isinstance(base, ast.Call) and isinstance(base.func, ast.Name)
              and base.func.id == "__import__" and len(base.args) == 1
              and isinstance(base.args[0], ast.Constant)
              and base.args[0].value in self.layer_of):
            # 跨层的动态导入合并器不折叠、只改模块名字符串（2026-11-02 板上 NameError 后改的）
            tgt = self.stem_of.get(self.layer_of[base.args[0].value])
            if tgt is not None and tgt != self.cur_file:
                base.args[0].value = tgt
                return node
            target = self.resolver(base.args[0].value, node.attr)
        if target is None:
            self.generic_visit(node)
            return node
        new = ast.Name(id=target, ctx=node.ctx)
        ast.copy_location(new, node)
        return new


def collect_alias(mg, mod):
    """原模块里「局部名 → 最终名」的映射，只针对同层/自引用的 from-import。"""
    aliases = {}
    for node in ast.walk(mg.trees[mod]):
        if not isinstance(node, ast.ImportFrom) or node.module not in mg.layer_of:
            continue
        for a in node.names:
            res = mg.resolve(node.module, a.name)
            if res is None:
                continue
            target_mod, target_name = res
            if target_mod == mod or mg.layer_of[target_mod] == mg.layer_of[mod]:
                aliases[a.asname or a.name] = mg.final_name(target_mod, target_name)
    return aliases


def collect_module_alias(mg, mod):
    out = {}
    for node in ast.walk(mg.trees[mod]):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in mg.layer_of and mg.layer_of[a.name] == mg.layer_of[mod]:
                    out[a.asname or a.name] = a.name
    return out


def main():
    global _REPORT
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(REPORT, "w", encoding="utf-8", newline="\n")
    for h in ["=" * 70,
              "  verify_merge.py —— 合并前后逐条语句结构比对",
              "=" * 70,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
              "=" * 70, ""]:
        log(h)
    try:
        spec = importlib.util.spec_from_file_location("merge_layers", REPO / "build" / "merge_layers.py")
        ml = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ml)
        mg = ml.Merger()
        layer_files = set(mg.FILES.values())

        total_mod, total_stmt, bad = 0, 0, []
        # 层名 → 合并后文件名（不带 .py）；跨层 __import__ 归一化要靠它判断是不是同一层
        stem_of = {l: Path(f).stem for l, f in mg.FILES.items()}
        for layer, fn, mods in mg.LAYERS:
            text = (OUT / fn).read_text(encoding="utf-8")
            marks = list(BANNER.finditer(text))
            sections = {}
            for i, m in enumerate(marks):
                start = text.find("\n", m.end()) + 1
                end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
                body = text[start:end]
                body = re.sub(r"# =+\n?$", "", body.rstrip()) + "\n"
                sections[m.group(1)] = body
            log(f"[{fn}] 切出 {len(sections)} 段")
            for mod in mods:
                total_mod += 1
                sec = sections.get(mod)
                if sec is None:
                    bad.append((mod, "合并文件里没有这一节"))
                    log(f"    FAIL {mod}: 合并文件里没有这一节")
                    continue
                try:
                    co = ast.parse(mg.sources[mod].decode("utf-8"), mod + ".py")
                    cm = ast.parse(sec, fn + "::" + mod)
                except SyntaxError as e:
                    bad.append((mod, f"解析失败 {e}"))
                    log(f"    FAIL {mod}: 解析失败 {e}")
                    continue
                normalize_module_scope(co, mg.layer_of)
                stem_set = {Path(x).stem for x in layer_files}
                for t in (co, cm):
                    DropGlobal().visit(t)
                    DropProjectImports(mg.layer_of, stem_set).visit(t)

                names = {n: mg.rename[(mod, n)] for n in mg.defs[mod] if (mod, n) in mg.rename}
                aliases = collect_alias(mg, mod)
                module_alias = collect_module_alias(mg, mod)

                def resolver(m, a, _mg=mg):
                    res = _mg.resolve(m, a)
                    return _mg.final_name(*res) if res else a

                co = Rename(names, aliases, module_alias, resolver, mg.layer_of,
                            cur_file=Path(fn).stem, stem_of=stem_of).visit(co)
                ast.fix_missing_locations(co)

                a_body, m_body = co.body, cm.body
                if len(a_body) != len(m_body):
                    bad.append((mod, f"顶层语句数不同：原 {len(a_body)} / 合并 {len(m_body)}"))
                    log(f"    FAIL {mod}: 顶层语句数不同 {len(a_body)} vs {len(m_body)}")
                    continue
                diff = []
                for idx, (sa, sm) in enumerate(zip(a_body, m_body)):
                    total_stmt += 1
                    if ast.dump(sa) != ast.dump(sm):
                        diff.append(idx)
                if diff:
                    bad.append((mod, f"{len(diff)} 条语句不同"))
                    log(f"    FAIL {mod}: {len(diff)} 条语句不同，位置 {diff[:10]}")
                    for idx in diff[:3]:
                        sa, sm = a_body[idx], m_body[idx]
                        log(f"        第 {idx} 条（原第 {sa.lineno} 行）:")
                        log(f"          原  : {ast.dump(sa)[:300]}")
                        log(f"          合并: {ast.dump(sm)[:300]}")
                else:
                    log(f"    OK   {mod}  {len(a_body)} 条顶层语句")
        log("")
        log("=" * 70)
        log(f"模块 {total_mod} 个，顶层语句 {total_stmt} 条，不同 {len(bad)} 个模块")
        for m, why in bad:
            log(f"  - {m}: {why}")
        log("RESULT: " + ("PASS" if not bad else "FAIL"))
        return 0 if not bad else 1
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
