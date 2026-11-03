#!/usr/bin/env python3
"""静态查「引用了一个解释器根本找不到的名字」（等价 pyflakes 的 F821）。

    python build/check_undefined.py <目录或文件> [...]

为什么必须有这个门禁
--------------------
2026-11-02 板上实炸：`display.py:2492 NameError: name 'LINE_BUF_ROWS' is not defined`。
根因是合并工具把 `__import__('p11_contract').LINE_BUF_ROWS` 折叠成了裸名
`LINE_BUF_ROWS`，却没有在本文件里补 `from core import ...`。
而 `check_merged.py` 的 [B] 只做 `__import__`，函数体不执行 ⇒ 这种名字一辈子抓不到。
**导入成功 ≠ 名字能解析。**

做法：用标准库 `symtable` 逐作用域看符号表 —— 一个名字若在函数里是 `is_global()`
（说明它要往外层模块找），而模块作用域里既没赋值、没导入、也不是类/函数定义，
也不是内建名 ⇒ 判未定义。不依赖第三方包。

⚠️ 控制组：对原始 114 个模块也要跑一遍。原版若本来就 0 条，合并版也必须 0 条；
原版若有已知的延迟导入写法（运行时才注入），报告里会列出来，人工确认后加白名单。
"""
import builtins
import datetime
import hashlib
import io
import platform
import symtable
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORT = REPO / "build" / "reports" / "check_undefined_report.txt"
MODULE_BUILTINS = {"__file__", "__name__", "__doc__", "__package__", "__spec__",
                   "__loader__", "__builtins__", "__path__", "__dict__", "__class__"}
_REPORT = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def _walk(table, module_names, out, path=""):
    here = path or table.get_name()
    for sym in table.get_symbols():
        name = sym.get_name()
        if sym.is_global() and sym.is_referenced():
            if name not in module_names and name not in MODULE_BUILTINS \
                    and not hasattr(builtins, name):
                out.append((here, name))
    for child in table.get_children():
        _walk(child, module_names, out, here + "." + child.get_name())


def check_file(path):
    src = path.read_text(encoding="utf-8")
    st = symtable.symtable(src, path.name, "exec")
    module_names = set()
    for sym in st.get_symbols():
        if sym.is_assigned() or sym.is_imported() or sym.is_namespace() \
                or sym.is_parameter() or sym.is_free():
            module_names.add(sym.get_name())
    out = []
    _walk(st, module_names, out)
    # 去重（同名在不同函数里各报一次，保留首次出现的函数路径即可）
    seen, uniq = set(), []
    for where, name in out:
        if name in seen:
            continue
        seen.add(name)
        uniq.append((where, name))
    return uniq


def main():
    global _REPORT
    if len(sys.argv) < 2:
        print("用法: python build/check_undefined.py <目录或文件> [...]")
        return 2
    targets = []
    for a in sys.argv[1:]:
        p = Path(a)
        if p.is_dir():
            targets += sorted(q for q in p.glob("*.py"))
        elif p.is_file():
            targets.append(p)
        else:
            raise SystemExit("找不到：" + a)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(REPORT, "w", encoding="utf-8", newline="\n")
    for h in ["=" * 70,
              "  check_undefined.py —— 静态查未定义名（F821 等价）",
              "=" * 70,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
              f"目标   : {len(targets)} 个文件",
              "=" * 70, ""]:
        log(h)

    try:
        bad_total = 0
        for p in targets:
            try:
                hits = check_file(p)
            except SyntaxError as e:
                log(f"FAIL {p.name} 语法错误：{e}")
                bad_total += 1
                continue
            if not hits:
                log(f"OK   {p.name:<24} 未定义名 0 个")
            else:
                bad_total += len(hits)
                log(f"FAIL {p.name:<24} 未定义名 {len(hits)} 个")
                for where, name in hits:
                    log(f"       {name}   ← {where}")
        log("")
        log("=" * 70)
        log(f"合计未定义名 {bad_total} 个")
        log("RESULT: " + ("PASS" if bad_total == 0 else "FAIL"))
        return 0 if bad_total == 0 else 1
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
