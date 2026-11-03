#!/usr/bin/env python3
"""给合并版造 114 个「原模块名」转发垫片，用来跑现成的检查脚本。

合并之后原来的 import 名（v73_ratio、p11_contract…）都不存在了。
为了能不修改 sim/checks/ 就把它们跑起来，本脚本为每个原模块生成一个同名 .py：

    # v73_ratio.py  （垫片，仅验证用）
    from display import make_orientation as make_orientation, ...

只转发「顶层定义 + 顶层再导出」两类名字，其余一概不造。

    python build/make_shims.py <输出目录>
"""
import ast
import datetime
import hashlib
import importlib.util
import io
import platform
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#   这两个名字在合并包里是**真实文件**（被 subprocess.Popen 拉起的子进程入口，
#   见 p11_contract.LAYER_EXTRA_FILES）。给它们造垫片会把真文件覆盖成转发代码，
#   校验立刻报「文件版本或内容不一致」—— 2026-11-02 实踩。
LAYER_EXTRA = ("v99_ai_worker.py", "v99_ai_selftest.py")
REPORT = REPO / "build" / "reports" / "make_shims_report.txt"
_REPORT = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def main():
    global _REPORT
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO / "build" / "_scratch" / "shims"
    out.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(REPORT, "w", encoding="utf-8", newline="\n")
    for h in ["=" * 70,
              "  make_shims.py —— 生成原模块名的转发垫片",
              "=" * 70,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
              f"输出   : {out}",
              "=" * 70, ""]:
        log(h)

    try:
        spec = importlib.util.spec_from_file_location("merge_layers", REPO / "build" / "merge_layers.py")
        ml = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ml)
        mg = ml.Merger()

        total = 0
        for layer, fn, mods in mg.LAYERS:
            layer_mod = Path(fn).stem
            for m in mods:
                if (m + ".py") in LAYER_EXTRA:
                    (out / (m + ".py")).unlink(missing_ok=True)   # 清掉历史残留
                    log(f"    [skip] {m}: 合并包里是真实文件（子进程入口），不造垫片")
                    continue
                # 名字不一定都来自本层：再导出的可能来自别的层，必须分组
                names = {}
                for n in mg.defs[m]:
                    names[n] = (layer_mod, mg.final_name(m, n))
                # 顶层再导出（from X import a [as b]）
                for node in mg.trees[m].body:
                    if isinstance(node, ast.ImportFrom) and node.module in mg.layer_of:
                        for a in node.names:
                            local = a.asname or a.name
                            if local in names:
                                continue
                            res = mg.resolve(node.module, a.name)
                            if res is None:
                                log(f"    [warn] {m}: 再导出 {local} 解析不到")
                                continue
                            names[local] = (Path(mg.FILES[mg.layer_of[res[0]]]).stem,
                                            mg.final_name(*res))
                if not names:
                    log(f"    [warn] {m}: 没有任何顶层名字")
                    continue
                groups = {}
                for orig, (src_mod, fin) in names.items():
                    groups.setdefault(src_mod, []).append((orig, fin))
                # 显式名单放最前，模块对象后面补；顺序不能反，否则补模块那步找不到层文件
                body = ['"""合并版验证用垫片：把原模块名转发到合并层里改过名的定义。"""']
                for src_mod in sorted(groups):
                    items = sorted(groups[src_mod])
                    lines, chunk = [], []
                    for orig, fin in items:
                        chunk.append(f"{fin} as {orig}" if fin != orig else fin)
                        if len(chunk) == 4:
                            lines.append(", ".join(chunk))
                            chunk = []
                    if chunk:
                        lines.append(", ".join(chunk))
                    body.append(f"from {src_mod} import ("
                                + (chr(10) + "    ")
                                + ("," + chr(10) + "    ").join(lines)
                                + "," + chr(10) + ")")
                # 检查脚本会 patch('<模块>.time.perf_counter')，得把层文件里 import
                # 进来的模块对象（time/os/np…）也挂到垫片上，且必须在 import 之后。
                body += ["# 下面这段只为对齐 patch('<模块>.time.perf_counter') 这类用法",
                         "import sys as _sys, types as _types",
                         f"_src = _sys.modules['{layer_mod}']",
                         "for _k, _v in list(vars(_src).items()):",
                         "    if isinstance(_v, _types.ModuleType) and _k not in globals():",
                         "        globals()[_k] = _v",
                         "del _k, _v, _src"]
                (out / (m + ".py")).write_text("\n".join(body) + "\n", encoding="utf-8")
                total += 1
        log(f"[完成] 生成 {total} 个垫片 -> {out}")
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
