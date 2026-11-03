#!/usr/bin/env python3
"""一条命令打出「按层合并」的完整发布目录，并跑完所有自检。

链条（顺序不能换）：
  1. merge_layers.py        114 个模块 -> 6 个层文件（AST 定位、原文本切片）
  2. 照 assemble_runtime.py 的源清单整目录复制（界面资产 / .cpp / system.* / ai/ 一个不少），
     再按 RELEASE_EXCLUDE 剔掉 2 个「复现用不到」的文件（旧 ZIP 安装本 / 上次上传的校验快照）
  3. 删掉顶层 114 个模块 .py
  4. 拷进 6 个层文件
  5. make_ai_entries.py     生成自包含的 AI 独立入口 v99_ai_worker.py + v99_ai_selftest.py
  6. make_release_manifest.py  以原清单为底本，换成 6+1 条 .py 的 sha256，
                               并把 sha256 收敛成包内文件的精确快照（幽灵条目一条不留）
  7. check_merged.py        语法 / 导入 / 模块身份 / 契约闸门（含判红）/ AI 子进程门禁（含判红）
  8. check_undefined.py     静态查未定义名（symtable，F821 等价）—— 导入成功不代表名字能解析
  9. check_start_notebook.py  无头执行 p11_start.ipynb 第 1 单元（板端唯一入口）

    python build/build_merged_release.py [输出目录]

默认输出 D:\\study\\competition\\qian\\_runtime_build\\p11_fps33_20261101_merged
"""
import datetime
import hashlib
import io
import platform
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build"
DEFAULT_OUT = REPO.parent / "_runtime_build" / "p11_fps33_20261101_merged"
LAYERS = ("core", "geometry", "tracking", "display", "ai", "ui")

# 与 assemble_runtime.py 保持同一份源清单（(源目录, 目标子目录)）
SOURCES = [
    ("src/ps/core", ""),
    ("src/ps/ui", ""),
    ("src/ps/assets", ""),
    ("src/ps/runtime", ""),
    ("src/native", ""),
    ("board", ""),
    ("src/third_party/ai", "ai"),
    # ai_selftest.ipynb → v99_ai_selftest.py 会按 v99_ai_selftest.json 的 cases[].image
    # 去读 ai_selftest/*.png 并核 sha256。2026-11-03 实测：不带上这一条，包里 10 条用例
    # 全部 FileNotFoundError（33 版包里本来就有，是改成 layers-6 时丢的）。
    ("data/ai_selftest", "ai_selftest"),
]

# 不随包上传的文件（相对发布目录根，条目可以是目录）。
# 判据只有一条：**官方复现 = 拷目录 + 跑 p11_start.ipynb**，用不到的一律不发。
# 2026-11-02：原来这 35 个里有 33 个是 ncnn 包内文件（model_zoo/utils/dist-info），
# 已直接从 src/ 删除（备份在 build/_scratch/ncnn_dropped_backup/），不再需要排除规则。
# ⛔ 但 .dist-info/licenses/LICENSE.txt 必须留在 src/ —— ncnn 是 BSD-3-Clause，分发二进制要带许可。
# 剩下这 2 条仍按原判据保留：官方复现 = 拷目录 + 跑 p11_start.ipynb，用不到的一律不发。
RELEASE_EXCLUDE = (
    # 从 ZIP 安装的安装本：要求同目录有我们根本不发的 zip，
    # 第 5 单元还会跑包里没有的 pic78_cpu_check.py ⇒ 传上去只会让人以为包坏了。
    "install_ai_fps_full_20261101_33.ipynb",
    # 上一次上传留下的校验快照，全包 0 处引用。
    "fps33_upload_checksums.json",
    # board/logs/ 是**证据**（22.73 fps 的原始 run-result），不是运行文件：
    #   2026-11-03 实测 —— 不排掉它，一条命令产出的包是 106 个文件 / +14.4 MB，
    #   而板上跑着的交付包是 104 个。它还会被写进 release_manifest.json，
    #   于是 v84_prebuilt.export_ready_upload 每次都要多读 14 MB。
    "logs",
)

REPORT = BUILD / "reports" / "build_merged_release_report.txt"
_REPORT = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def sha16(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def run(script, *args):
    """跑 build/ 下的一个脚本；屏幕输出原样转发，返回 (退出码, 输出全文)。"""
    cmd = [sys.executable, str(BUILD / script), *[str(a) for a in args]]
    log(f"  $ python build/{script} {' '.join(str(a) for a in args)}")
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True)
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    for line in out.rstrip("\n").split("\n"):
        log("    | " + line)
    return r.returncode, out


def main():
    global _REPORT
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUT
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(REPORT, "w", encoding="utf-8", newline="\n")
    for h in ["=" * 78,
              "  build_merged_release.py —— 打完整合并发布目录",
              "=" * 78,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={sha16(__file__)}",
              f"输出   : {out}",
              "=" * 78, ""]:
        log(h)
    try:
        failures = []

        log("[1] 合并 114 个模块 -> 6 个层文件")
        code, _ = run("merge_layers.py")
        if code != 0:
            raise RuntimeError("merge_layers.py 失败，见上面的完整输出")
        log("")

        log("[2] 复制全部非模块文件")
        if out.exists():
            shutil.rmtree(out)
            log(f"    删掉旧目录 {out}")
        out.mkdir(parents=True)
        copied = 0
        skipped = []

        def _excluded(rel_out):
            return any(rel_out == e or rel_out.startswith(e + "/") for e in RELEASE_EXCLUDE)

        for rel, sub in SOURCES:
            src = REPO / rel
            if not src.is_dir():
                raise RuntimeError("源目录不存在：" + str(src))
            dst = out / sub if sub else out
            dst.mkdir(parents=True, exist_ok=True)
            n = 0
            for p in sorted(src.rglob("*")):
                if not p.is_file() or p.name == "README.md":
                    continue
                rel_out = f"{sub}/{p.relative_to(src).as_posix()}" if sub else p.relative_to(src).as_posix()
                if _excluded(rel_out):
                    skipped.append(rel_out)
                    continue
                target = dst / p.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
                n += 1
            copied += n
            log(f"    {rel:<24} -> {sub or '(根目录)':<24} {n:>4} 个")
        log(f"    合计 {copied} 个")
        log(f"    按 RELEASE_EXCLUDE 排除 {len(skipped)} 个")
        # 空转门禁：每条排除规则必须真的匹配到东西，否则就是规则名写错了、
        # 文件照样被传上去（2026-10-22 那类「永远通过」的坑）。
        for e in RELEASE_EXCLUDE:
            if not any(s == e or s.startswith(e + "/") for s in skipped):
                raise RuntimeError(f"RELEASE_EXCLUDE 规则没匹配到任何文件，检查规则名：{e}")
        for s in skipped:
            log(f"      - {s}")
        log("")

        log("[3] 删掉顶层 114 个模块 .py")
        dropped = sorted(p.name for p in out.glob("*.py"))
        for p in out.glob("*.py"):
            p.unlink()
        log(f"    删掉 {len(dropped)} 个（{dropped[0]} … {dropped[-1]}）")
        log("")

        log("[4] 拷进 6 个层文件")
        for n in LAYERS:
            src = REPO / "_merge_out" / (n + ".py")
            if not src.is_file():
                raise FileNotFoundError(f"合并产物不存在：{src}")
            shutil.copy2(src, out / (n + ".py"))
            log(f"    + {n}.py  sha16={sha16(src)}  {src.stat().st_size:,} B")
        log("")

        log("[5] 生成自包含的 AI 独立入口（worker + selftest）")
        code, _ = run("make_ai_entries.py", out)
        if code != 0:
            raise RuntimeError("make_ai_entries.py 失败")
        log("")

        log("[6] 重写 release_manifest.json")
        base = REPO / "src" / "ps" / "runtime" / "release_manifest.json"
        if not base.is_file():
            raise FileNotFoundError(f"找不到底本清单：{base}")
        log(f"    底本 {base}  sha16={sha16(base)}")
        code, _ = run("make_release_manifest.py", out, base)
        if code != 0:
            raise RuntimeError("make_release_manifest.py 失败")
        log("")

        log("[7] 合并版运行目录自检")
        code, _ = run("check_merged.py", out)
        if code != 0:
            failures.append("check_merged")
        log("")

        log("[8] 静态查未定义名（F821 等价 —— 2026-11-02 板上 NameError 的教训）")
        code, _ = run("check_undefined.py", *(out / (n + ".py") for n in LAYERS))
        if code != 0:
            failures.append("check_undefined")
        log("")

        log("[9] 启动本第 1 单元无头执行（板端唯一入口，必须真的跑得通）")
        code, _ = run("check_start_notebook.py", out, "--tag", "merged")
        if code != 0:
            failures.append("check_start_notebook")
        log("")

        log("[10] 清掉自检产生的 __pycache__（那是本机 3.14 的产物，不该进板端包）")
        gone = 0
        for p in out.rglob("__pycache__"):
            if p.is_dir():
                gone += sum(1 for q in p.rglob("*") if q.is_file())
                shutil.rmtree(p)
        log(f"    删掉 {gone} 个 .pyc")
        log("")

        log("=" * 78)
        log(f"目录 {out}")
        total = sum(1 for p in out.rglob("*") if p.is_file())
        log(f"文件 {total} 个（其中 .py {len(list(out.glob('*.py')))} 个）")
        for p in sorted(out.glob("*.py")):
            log(f"  {p.name:<20} {p.stat().st_size:>9,} B  sha16={sha16(p)}")
        w = out / "release_manifest.json"
        if w.is_file():
            log(f"  release_manifest.json {w.stat().st_size:>9,} B  sha16={sha16(w)}")
        log("")
        log("RESULT: " + ("PASS" if not failures else "FAIL " + ", ".join(failures)))
        return 0 if not failures else 1
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
