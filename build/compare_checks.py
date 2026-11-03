#!/usr/bin/env python3
"""比对两份 run_checks.py 的 JSON 结果。

判定分三类：
  * 结构差异（键缺失 / 类型不同 / 列表长度不同）—— 一定是问题
  * 非数值差异（字符串、布尔、None）—— 一定是问题
  * 数值差异 —— 单独列出相对偏差；计时类字段本来就有抖动

    python build/compare_checks.py <A.json> <B.json>
"""
import datetime
import hashlib
import io
import json
import platform
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORT = REPO / "build" / "reports" / "compare_checks_report.txt"
_REPORT = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def walk(x, y, p, out):
    if type(x) is not type(y):
        out.append(("STRUCT", p, f"{type(x).__name__} vs {type(y).__name__}", ""))
        return
    if isinstance(x, dict):
        for k in sorted(set(x) | set(y)):
            if k not in x:
                out.append(("STRUCT", p + "/" + k, "只在 B 里", ""))
            elif k not in y:
                out.append(("STRUCT", p + "/" + k, "只在 A 里", ""))
            else:
                walk(x[k], y[k], p + "/" + k, out)
    elif isinstance(x, list):
        if len(x) != len(y):
            out.append(("STRUCT", p, f"长度 {len(x)} vs {len(y)}", ""))
            return
        for i, (u, v) in enumerate(zip(x, y)):
            walk(u, v, f"{p}/{i}", out)
    elif isinstance(x, bool) or x is None or isinstance(x, str):
        if x != y:
            out.append(("VALUE", p, repr(x), repr(y)))
    elif isinstance(x, (int, float)):
        if x != y:
            rel = abs(x - y) / max(abs(x), abs(y), 1e-12)
            out.append(("NUMBER", p, f"{x!r}", f"{y!r}  相对差 {rel:.3%}"))
    else:
        out.append(("STRUCT", p, f"未知类型 {type(x).__name__}", ""))


def main():
    global _REPORT
    if len(sys.argv) != 3:
        print("用法: python build/compare_checks.py <A.json> <B.json>")
        return 2
    a_path, b_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(REPORT, "w", encoding="utf-8", newline="\n")
    for h in ["=" * 70,
              "  compare_checks.py —— 两份检查结果比对",
              "=" * 70,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
              f"A      : {a_path}",
              f"B      : {b_path}",
              "=" * 70, ""]:
        log(h)
    try:
        A = json.loads(a_path.read_text(encoding="utf-8"))["results"]
        B = json.loads(b_path.read_text(encoding="utf-8"))["results"]
        out = []
        for k in sorted(set(A) | set(B)):
            if k not in A:
                out.append(("STRUCT", k, "只在 B 里", ""))
            elif k not in B:
                out.append(("STRUCT", k, "只在 A 里", ""))
            else:
                walk(A[k], B[k], k, out)
        struct = [o for o in out if o[0] == "STRUCT"]
        value = [o for o in out if o[0] == "VALUE"]
        number = [o for o in out if o[0] == "NUMBER"]
        log(f"结构差异 {len(struct)} 处 / 非数值差异 {len(value)} 处 / 数值差异 {len(number)} 处")
        log("")
        for tag, rows in (("结构", struct), ("非数值", value), ("数值", number)):
            if not rows:
                continue
            log(f"---- {tag} ----")
            for kind, p, u, v in rows:
                log(f"  {p}")
                log(f"      A={u}")
                log(f"      B={v}")
            log("")
        bad = len(struct) + len(value)
        log("=" * 70)
        log(f"RESULT: {'PASS（只有数值不同）' if bad == 0 else 'FAIL（存在结构或非数值差异）'}")
        return 0 if bad == 0 else 1
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
