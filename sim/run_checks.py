#!/usr/bin/env python3
"""跑完 sim/checks 的全部主机侧检查，输出单文件报告。

为什么不能像 README 老版那样直接 `python sim/checks/x.py`：
  1. 检查脚本假设自己就住在发布目录里 —— trackfix_cpu_check.py 读
     `Path(__file__).parent/'v105_edges.cpp'`，搬进仓库就必然 FileNotFoundError。
  2. numpy>=2 删了二维 np.cross，而运行时里 6 处在用（v31_tracking.py:129 等），
     直接跑会 ValueError。
本脚本把这两件事都兜住：把发布目录整个复制到临时目录、摆进检查脚本、
注入二维 cross 兼容垫片，再按依赖根依次运行。**不动原发布目录一个字节。**

用法：
    python sim/run_checks.py --release <114 模块扁平运行目录>
    python sim/run_checks.py                  # 自动在 ../_runtime_build/ 里找

    --out FILE   报告路径（默认 sim/reports/run_checks_report.txt）
    --board      连 sharp23_board_check.py 一起跑（需要板子，默认不跑）
    --keep       保留临时目录，便于事后翻现场
"""
import argparse
import datetime
import hashlib
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CHECKS = HERE / "checks"
DEFAULT_REPORT = HERE / "reports" / "run_checks_report.txt"
TIMEOUT_S = 1800

# 在子进程里先装垫片再执行目标脚本。runpy 会把 __file__ 设成传入的路径，
# 所以目标脚本里的 Path(__file__).parent 仍然指向临时目录（= 发布目录副本）。
LAUNCHER = '''import sys, runpy, numpy as np
_orig = np.cross
def _cross(a, b, *args, **kw):
    a = np.asarray(a); b = np.asarray(b)
    if a.shape[-1:] == (2,) and b.shape[-1:] == (2,) and not args and not kw:
        return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]
    return _orig(a, b, *args, **kw)
np.cross = _cross
target = sys.argv[1]
sys.argv = [target]
runpy.run_path(target, run_name="__main__")
'''

_OUT = None


def log(line=""):
    text = str(line) + "\n"
    if _OUT is not None:
        _OUT.write(text)
        _OUT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def looks_like_release(d):
    """扁平 114 模块运行目录的判据；按层合并版（只有 6 个 py）会在这里被挡掉。"""
    need = ("p11_contract.py", "v105_edges.cpp", "v115_pair_display.py", "system.bit")
    return d.is_dir() and all((d / n).is_file() for n in need)


def find_release():
    """在 ../_runtime_build/ 里找候选，取最新修改的那个。"""
    base = REPO.parent / "_runtime_build"
    if not base.is_dir():
        return None
    cands = [p for p in sorted(base.iterdir()) if looks_like_release(p)]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def check_modules():
    return {p.stem: p for p in sorted(CHECKS.glob("*_check.py"))}


def dependency_roots(files):
    """被别的检查 import 的不算根；剩下的才是需要直接跑的。"""
    names = {p.stem for p in files}
    imported = set()
    for p in files:
        src = p.read_text(encoding="utf-8")
        for line in src.splitlines():
            line = line.strip()
            if line.startswith("from ") and " import " in line:
                mod = line[5:].split(" import ")[0].strip()
                if mod in names:
                    imported.add(mod)
    return sorted(names - imported)


def copy_release(src, dst):
    def _ignore(d, names):
        return [n for n in names if n == "__pycache__"]
    shutil.copytree(src, dst, ignore=_ignore)


def main():
    global _OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--board", action="store_true")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    a.out.parent.mkdir(parents=True, exist_ok=True)
    _OUT = open(a.out, "w", encoding="utf-8", newline="\n")
    ok_all = False
    tmp = None
    try:
        log("=" * 78)
        log("  run_checks.py —— 主机侧检查全跑")
        log("=" * 78)
        log(f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}")
        log(f"机器   : {platform.node()} / {platform.platform()}")
        log(f"Python : {sys.version.split()[0]}")
        try:
            import numpy
            log(f"numpy  : {numpy.__version__}")
        except Exception:
            log("numpy  : 未安装")
        try:
            import cv2
            log(f"cv2    : {cv2.__version__}")
        except Exception:
            log("cv2    : 未安装")
        log(f"脚本   : {Path(__file__).name}  sha16={sha256_file(Path(__file__).resolve())[:16]}")
        log("=" * 78)
        log("")

        release = a.release or find_release()
        if release is None:
            log("[FAIL] 找不到可用的发布目录。先用 build/assemble_runtime.py 生成")
            log("       114 模块扁平目录，再用 --release 指过来。")
            log("RESULT: FAIL")
            return 2
        release = release.resolve()
        log(f"[1] 发布目录 {release}")
        if not looks_like_release(release):
            log("    [FAIL] 缺少 p11_contract.py / v105_edges.cpp / v115_pair_display.py / system.bit 之一")
            log("           （按层合并版只有 6 个 .py，跑不了这些检查）")
            log("RESULT: FAIL")
            return 2
        man = release / "release_manifest.json"
        if man.is_file():
            import json
            try:
                rid = json.loads(man.read_text(encoding="utf-8")).get("release_id", "?")
            except Exception:
                rid = "?（解析失败）"
            log(f"    release_id = {rid}")
        log("")

        files = list(check_modules().values())
        if a.board:
            if (CHECKS / "sharp23_board_check.py").is_file():
                files.append(CHECKS / "sharp23_board_check.py")
        else:
            files = [p for p in files if p.name != "sharp23_board_check.py"]
        roots = dependency_roots(files)
        log(f"[2] 检查脚本 {len(files)} 个；依赖根 {len(roots)} 个（跑根即覆盖全链）")
        for n in roots:
            log(f"      - {n}")
        # 空转门禁：根数必须是可解释的，少了说明依赖解析坏了
        if len(roots) < 1:
            log("    [FAIL] 一个根都没解析出来，依赖图解析不可信")
            log("RESULT: FAIL")
            return 2

        tmp = Path(tempfile.mkdtemp(prefix="simchecks_"))
        log("")
        log(f"[3] 复制发布目录到临时目录 {tmp}")
        copy_release(release, tmp / "rel")
        work = tmp / "rel"
        # 全部 .py 都拷：trackfix_cpu_check 会按文件路径加载 trackfix_baseline_physical4.py，
        # 而它不是 *_check.py，只拷根/只拷 *_check.py 都会漏。
        copied = sorted(CHECKS.glob("*.py"))
        for p in copied:
            shutil.copy2(p, work / p.name)
        (work / "_launcher.py").write_text(LAUNCHER, encoding="utf-8")
        log(f"    {sum(1 for _ in work.rglob('*') if _.is_file())} 个文件")
        log("")

        results = []
        for n in roots:
            log("=" * 78)
            log(f"[run] {n}")
            log("-" * 78)
            cmd = [sys.executable, "_launcher.py", f"{n}.py"]
            t0 = time.time()
            p = subprocess.run(cmd, cwd=str(work), capture_output=True, timeout=TIMEOUT_S)
            elapsed = time.time() - t0
            out = (p.stdout + p.stderr).decode("utf-8", "replace")
            for line in out.rstrip("\n").split("\n"):
                log("  | " + line)
            js = work / f"{n}.json"
            passed = None
            if js.is_file():
                import json as _json
                try:
                    passed = bool(_json.loads(js.read_text(encoding="utf-8")).get("passed"))
                except Exception:
                    passed = None
            results.append((n, p.returncode, passed, js.is_file(), elapsed))
            log("-" * 78)
            log(f"  exit={p.returncode}  json={'有' if js.is_file() else '无'}  "
                f"passed={passed}  用时={elapsed:.1f} s")
            log("")

        log("=" * 78)
        log("[4] 汇总")
        bad = []
        for n, code, passed, has_json, elapsed in results:
            flag = "PASS" if (code == 0 and passed is not False and has_json) else "FAIL"
            if flag == "FAIL":
                bad.append(n)
            log(f"    {flag}  {n:<24} exit={code} json={has_json} "
                f"passed={passed}  {elapsed:>6.1f} s")
        log(f"    合计 {sum(r[4] for r in results):.1f} s"
            f"（各根有重叠，靠前的链被后面的根重复跑，合计不是净成本）")
        log("")
        log(f"检查脚本指纹（供事后核对是不是同一版）：")
        for p in files:
            log(f"    {sha256_file(p)[:16]}  {p.name}")
        log("")
        ok_all = not bad
        log("RESULT: " + ("PASS" if ok_all else "FAIL " + ", ".join(bad)))
        return 0 if ok_all else 1
    except Exception:
        log("")
        log("[!!] 完整堆栈（不截断）：")
        log(traceback.format_exc())
        log("RESULT: FAIL")
        return 1
    finally:
        if tmp is not None:
            if a.keep:
                log(f"临时目录保留在 {tmp}")
            else:
                shutil.rmtree(tmp, ignore_errors=True)
        _OUT.close()


if __name__ == "__main__":
    sys.exit(main())
