"""把分散在 src/ board/ 的源码组装成一个可运行的扁平目录，并校验完整性。

    python build/assemble_runtime.py [输出目录]

为什么需要这一步：`p11_contract.verify_package()` 要求所有运行文件
（109 个 .py、6 个 .cpp、77 个界面资产、system.bit/hwh/manifest、
release_manifest.json）**平铺在同一个目录**，少一个或改一个字节都会抛异常。
仓库按赛规把它们分在 src/ 和 board/ 下，所以运行前要用本脚本合回去。

组装完成后会实际调用一次 `verify_package()`，用发布清单逐文件核对 sha256。
全部通过才打印 PASS；任何一项不符都会打印完整原因（不截断）。

报告写到输出目录旁边的 assemble_runtime_report.txt，屏幕输出与报告逐字相同。
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO.parent / "_runtime_build" / "p11_fps33_20261101"

# (源目录, 目标子目录)；目标为空字符串表示平铺到输出根目录
SOURCES = [
    ("src/ps/core", ""),
    ("src/ps/ui", ""),
    ("src/ps/assets", ""),
    ("src/ps/runtime", ""),
    ("src/native", ""),
    ("board", ""),
    ("src/third_party/ai", "ai"),
]

_REPORT = None


def log(line=""):
    t = line + "\n"
    _REPORT.write(t)
    _REPORT.flush()
    sys.stdout.buffer.write(t.encode("utf-8"))
    sys.stdout.buffer.flush()


def sha16(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def main():
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUT
    report_path = out.parent / "assemble_runtime_report.txt"

    global _REPORT
    out.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(report_path, "w", encoding="utf-8", newline="\n")

    log("=" * 78)
    log("# 运行时目录组装报告")
    log("#   %s   host %s" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                               os.environ.get("COMPUTERNAME", "?")))
    log("#   脚本 %s  sha16 %s" % (Path(__file__).resolve(), sha16(__file__)))
    log("#   仓库 %s" % REPO)
    log("#   输出 %s" % out)
    log("=" * 78)
    log("")

    log("── 1. 清空输出目录 ──")
    if out.exists():
        shutil.rmtree(out)
        log("  已删除旧目录")
    out.mkdir(parents=True)
    log("  已创建 %s" % out)
    log("")

    log("── 2. 复制文件 ──")
    total = 0
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
            target = dst / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            n += 1
        total += n
        log("  %-24s -> %-24s %4d 个" % (rel, sub or "(根目录)", n))
    log("  %-24s %29d 个" % ("合计", total))
    log("")

    log("── 3. 调用 verify_package() 逐文件核对 sha256 ──")
    code = (
        "import sys, json\n"
        "sys.path.insert(0, '.')\n"
        "import p11_contract\n"
        "m = p11_contract.verify_package('system.bit')\n"
        "print(json.dumps({'release_id': m['release_id'], 'keys': sorted(m)}))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(out),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    log("  退出码 %d" % r.returncode)
    if r.stdout.strip():
        log("  标准输出：")
        for line in r.stdout.rstrip("\n").split("\n"):
            log("    " + line)
    if r.stderr.strip():
        log("  标准错误（全文，未截断）：")
        for line in r.stderr.rstrip("\n").split("\n"):
            log("    " + line)
    log("")

    ok = r.returncode == 0
    log("=" * 78)
    if ok:
        log("# 结果：PASS —— 运行目录已组装完毕，完整性校验通过")
        log("# 下一步：把整个目录上传到板端，运行其中任意 Notebook 即可")
    else:
        log("# 结果：FAIL —— 完整性校验未通过，见上面的标准错误全文")
    log("# 报告：%s" % report_path)
    log("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        if _REPORT is not None:
            log("")
            log("=" * 78)
            log("# 失败 —— 完整 traceback（未截断）")
            log("=" * 78)
            for line in traceback.format_exc().rstrip("\n").split("\n"):
                log(line)
        raise
