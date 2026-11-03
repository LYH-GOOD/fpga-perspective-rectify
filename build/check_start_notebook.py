#!/usr/bin/env python3
"""无头执行启动本 p11_start.ipynb 的第 1 个代码单元，验证它在两种发布布局下都能跑通。

    python build/check_start_notebook.py <运行目录> [--notebook <另一个.ipynb>] [--tag <报告名>]

为什么要这个门禁
----------------
启动本是板端唯一入口，但它里面写死了 `p11_contract.py` / `v87_v74_tracking.py` /
`v97_album.py` / `from v75_ui import run_ui` —— 按层合并版（只有 core/geometry/
tracking/display/ai/ui 六个 .py）里一个都没有。改完必须证明：

  * 合并目录：走 `core.py` + `ui.py` 分支，一直跑到最后一行 print
  * 原样 114 模块目录：走 `p11_contract.py` + `v75_ui` 分支，同样跑到最后一行
  * **判红**：拿改动前的旧启动本去跑合并目录，必须失败
    （`--notebook build/_scratch/p11_start_orig.ipynb`）

判据 = 退出码 0 且 stdout 里有最后那行 print（`<RELEASE_ID> V9 FPS33: ...`）。
只判退出码不够 —— 单元可能提前 return，所以两个条件都要。

⚠️ 本机没有 IPython ⇒ 用 build/_stubs/IPython.py（get_ipython() 返回 None）；
   本机没有 fcntl ⇒ 用 build/_stubs/fcntl.py。板上两个都是真的。
"""
import datetime
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORT_DIR = REPO / "build" / "reports"
STUBS = REPO / "build" / "_stubs"
EXPECT_RELEASE = "p11-rgb-pspl-v9-ai-fps-20261101-33"
EXPECT_TAIL = "V9 FPS33: 3s output FPS"
CELL_INDEX = 1          # cells[0] 是 markdown；cells[1] = 找目录 + 设环境变量 + 导入
MARKER = "_build_dir"   # 选错单元的判据

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
    args = sys.argv[1:]
    if not args:
        print("用法: python build/check_start_notebook.py <运行目录> "
              "[--notebook <x.ipynb>] [--tag <报告名>]")
        return 2
    pkg = Path(args[0]).resolve()
    nb_path = None
    tag = pkg.name
    rest = args[1:]
    while rest:
        k = rest.pop(0)
        if k == "--notebook":
            nb_path = Path(rest.pop(0)).resolve()
        elif k == "--tag":
            tag = rest.pop(0)
        else:
            raise SystemExit("未知参数：" + k)
    nb_path = nb_path or (pkg / "p11_start.ipynb")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT = REPORT_DIR / f"check_start_notebook_{tag}.txt"
    _REPORT = io.open(REPORT, "w", encoding="utf-8", newline="\n")

    layout = "layers-6" if (pkg / "core.py").is_file() else "modules-114"
    for h in ["=" * 70,
              "  check_start_notebook.py —— 启动本第 1 单元无头执行",
              "=" * 70,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
              f"运行目录: {pkg}",
              f"启动本  : {nb_path}",
              f"布局    : {layout}（按目录里有没有 core.py 判断）",
              "=" * 70, ""]:
        log(h)

    try:
        if not nb_path.is_file():
            raise FileNotFoundError(f"找不到启动本：{nb_path}")
        nb = json.loads(nb_path.read_bytes().decode("utf-8"))
        cell = nb["cells"][CELL_INDEX]
        src = "".join(cell["source"])
        if MARKER not in src:
            raise ValueError(f"cells[{CELL_INDEX}] 里没有 {MARKER!r} —— 单元格顺序变了，"
                             f"请先确认哪个单元是启动逻辑")
        compile(src, str(nb_path), "exec")
        log(f"[1] 取到 cells[{CELL_INDEX}]，{len(src.splitlines())} 行，语法可解析")
        log(f"    sha16={hashlib.sha256(src.encode('utf-8')).hexdigest()}")

        tmp = Path(tempfile.mkdtemp(prefix="p11start_")).resolve()
        script = tmp / "run_cell1.py"
        script.write_text(src, encoding="utf-8", newline="\n")
        log(f"[2] 写临时脚本 {script}（在运行目录之外，不污染发布包）")

        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(pkg), str(STUBS)])
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("PYTHONHOME", None)
        log(f"[3] 起子进程：cwd={pkg}")
        log(f"    PYTHONPATH={env['PYTHONPATH']}")
        log("")
        log("    " + "-" * 62)
        r = subprocess.run([sys.executable, "-u", "-B", str(script)],
                           cwd=str(pkg), env=env, capture_output=True, timeout=600)
        out = r.stdout.decode("utf-8", "replace")
        err = r.stderr.decode("utf-8", "replace")
        for line in out.splitlines():
            log("    | " + line)
        log("    " + "-" * 62)
        log("")

        ok = True
        if r.returncode != 0:
            ok = False
            log(f"[4] FAIL 退出码 {r.returncode}")
            log("    完整 stderr（不截断）：")
            for line in err.splitlines():
                log("    ! " + line)
        else:
            log("[4] OK   退出码 0")
        if EXPECT_RELEASE not in out:
            ok = False
            log(f"[5] FAIL stdout 里没有 {EXPECT_RELEASE!r}")
        if EXPECT_TAIL not in out:
            ok = False
            log(f"[6] FAIL 没跑到最后一行 print（缺 {EXPECT_TAIL!r}）—— 单元中途退出了")
        if ok:
            log(f"[5] OK   RELEASE_ID = {EXPECT_RELEASE}")
            log(f"[6] OK   跑到最后一行 print")
        log("")
        log("=" * 70)
        log(f"RESULT: {'PASS' if ok else 'FAIL'}  ({pkg.name} / {layout})")
        return 0 if ok else 1
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
