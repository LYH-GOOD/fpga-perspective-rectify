#!/usr/bin/env python3
"""对指定运行目录跑全部 sim/checks/*_cpu_check.py，输出一份可比的 JSON。

用途：给「原版 114 个模块」和「合并版 6 个文件 + 114 个 shim」各跑一遍，
逐项比对返回值，证明合并没有改变行为。

    python build/run_checks.py <运行目录> <输出 json>

报告与屏幕输出逐字相同，每笔 write 都 flush，失败路径全文不截断。
"""
import datetime
import hashlib
import importlib.util
import io
import json
import platform
import sys
import traceback
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#   检查脚本用 Path(__file__).parent 当运行根目录（要找 system.bit / v105_edges.cpp），
#   所以它们必须和运行目录平铺在一起。运行目录里有就用运行目录的，否则用仓库里的。
CHECKS = REPO / "sim" / "checks"

_REPORT = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def install_numpy1_compat():
    """本机 numpy 2.x 删掉了 2 维 np.cross，板上是 1.21.5（支持）。

    这里按 numpy<2 的定义补回来，让两边的检查都能跑；
    原版和合并版用的是同一份补丁，比较结论不受影响。
    """
    import numpy as np
    orig = np.cross
    if getattr(np.cross, "_p11_compat", False):
        return "already"
    try:
        np.cross(np.array([1., 0.]), np.array([0., 1.]))
        return "numpy<2，不需要补丁"
    except Exception:
        pass

    def cross(a, b, *args, **kwargs):
        a = np.asarray(a)
        b = np.asarray(b)
        if a.shape[-1:] == (2,) and b.shape[-1:] == (2,):
            return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]
        return orig(a, b, *args, **kwargs)

    cross._p11_compat = True
    np.cross = cross
    return "已补 2 维 np.cross（numpy 2.x 删掉了它）"


def norm(o):
    """把返回值压成可 JSON 化、可稳定比较的形式。"""
    if isinstance(o, dict):
        return {str(k): norm(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [norm(v) for v in o]
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    if isinstance(o, types.ModuleType):
        return "<module %s>" % o.__name__
    return "<%s>" % type(o).__name__


def main():
    global _REPORT
    if len(sys.argv) != 3:
        print("用法: python build/run_checks.py <运行目录> <输出 json>")
        return 2
    runtime = Path(sys.argv[1]).resolve()
    outpath = Path(sys.argv[2]).resolve()
    outpath.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(str(outpath) + ".txt", "w", encoding="utf-8", newline="\n")

    for h in ["=" * 70,
              "  run_checks.py —— 对运行目录跑全部 CPU 检查",
              "=" * 70,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
              f"运行目录: {runtime}",
              f"Python 可执行: {sys.executable}",
              "=" * 70, ""]:
        log(h)

    # 本机 Windows 没有 fcntl/termios；板上（Linux）是真的。
    stub = REPO / "build" / "_stubs"
    if stub.is_dir():
        sys.path.append(str(stub))
        log(f"桩目录 : {stub}（仅供本机；板上用真模块）")

    global CHECKS
    if any(runtime.glob("*_cpu_check.py")):
        CHECKS = runtime
        log(f"检查脚本: {CHECKS}（与运行目录同处 —— 它们要找旁边的 system.bit / v105_edges.cpp）")
    else:
        log(f"检查脚本: {CHECKS}（仓库里）")
    sys.path.insert(0, str(CHECKS))
    sys.path.insert(0, str(runtime))
    try:
        sys.path.remove(str(REPO))
    except ValueError:
        pass

    log(f"numpy  : {__import__('numpy').__version__} —— {install_numpy1_compat()}")
    log("")

    names = sorted(p.stem for p in CHECKS.glob("*_cpu_check.py"))
    # 只跑链条的最顶端：被别的检查 import 的，由顶端连带跑，单独再跑一次是浪费
    srcs = {n: (CHECKS / (n + ".py")).read_text(encoding="utf-8") for n in names}
    referenced = set()
    for n in names:
        for other in names:
            if other != n and (f"from {other} import" in srcs[n]):
                referenced.add(other)
    tops = [n for n in names if n not in referenced]

    log(f"共 {len(names)} 个检查，其中 {len(tops)} 个是链条顶端（其余被顶端连带跑）")
    log(f"顶端: {', '.join(tops)}")
    log("")

    results = {}
    for n in tops:
        log("-" * 70)
        log(f"[{n}] 开始")
        try:
            spec = importlib.util.spec_from_file_location(n, CHECKS / (n + ".py"))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[n] = mod
            spec.loader.exec_module(mod)
            r = mod.run()
            results[n] = {"ok": True, "value": norm(r)}
            log(f"[{n}] PASS")
        except Exception as e:
            results[n] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                          "traceback": traceback.format_exc()}
            log(f"[{n}] FAIL {type(e).__name__}: {e}")
            log("完整堆栈：")
            log(traceback.format_exc())
        log("")

    payload = {"runtime": str(runtime), "results": results}
    with io.open(outpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.flush()

    bad = [k for k, v in results.items() if not v["ok"]]
    log("=" * 70)
    log(f"通过 {len(results) - len(bad)} / {len(results)}")
    if bad:
        log("失败: " + ", ".join(bad))
    log("RESULT: " + ("PASS" if not bad else "FAIL"))
    _REPORT.close()
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
