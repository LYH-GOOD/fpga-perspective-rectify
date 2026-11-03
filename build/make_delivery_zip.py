#!/usr/bin/env python3
"""把一个发布目录打成单个 zip（交付给外部看的"一个文件"）。

    python build/make_delivery_zip.py [源目录] [输出zip]

默认：
  源   D:\\study\\competition\\qian\\_runtime_build\\p11_fps33_20261101_merged
  输出 D:\\study\\competition\\qian\\_runtime_build\\p11_fps33_20261101_merged.zip

约束：
  * 条目按相对路径排序、时间戳固定 ⇒ 同样的输入打出来的 zip 逐字节稳定（sha 可复现）。
  * 打完必须回读自检：条目集合 == 磁盘文件集合，且逐条目 sha256 与磁盘一致。
    这里先造一次失败再信绿（改一个字节，必须报红）。
"""
import datetime
import hashlib
import platform
import shutil
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

# 默认路径跟着仓库走（clone 到别处也能跑），不写死本机盘符
_REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = _REPO.parent / "_runtime_build" / "p11_fps33_20261101_merged"
DEFAULT_OUT = _REPO.parent / "_runtime_build" / "p11_fps33_20261101_merged.zip"
REPORT = Path(__file__).resolve().parent / "reports" / "make_delivery_zip_report.txt"
FIXED_TIME = (2026, 11, 2, 0, 0, 0)  # 固定时间戳，保证可复现
_OUT = None


def log(line=""):
    text = str(line) + "\n"
    if _OUT is not None:
        _OUT.write(text)
        _OUT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_zip(src, out, files):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            rel = p.relative_to(src).as_posix()
            info = zipfile.ZipInfo(rel, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())


def verify(src, out):
    """回读 zip 逐条目核 sha，返回 (ok, 问题列表)。"""
    problems = []
    # 输出 zip 可能就放在 src 里（如 src/src.zip），不能把自己当成「磁盘上多出来的文件」
    disk = {p.relative_to(src).as_posix(): p for p in src.rglob("*")
            if p.is_file() and p.resolve() != out.resolve()}
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        if sorted(names) != sorted(disk):
            problems.append(f"条目集合不一致：zip {len(names)} 个 / 磁盘 {len(disk)} 个")
        for name in names:
            if name not in disk:
                problems.append(f"zip 多出：{name}")
                continue
            if sha256_bytes(z.read(name)) != sha256_file(disk[name]):
                problems.append(f"内容不一致：{name}")
    return (not problems), problems


def main():
    global _OUT
    src = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_SRC
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else DEFAULT_OUT
    # 报告按输出名区分，别让第二次打包覆盖第一次的留痕
    report = REPORT.with_name(f"make_delivery_zip_{out.stem}_report.txt")
    report.parent.mkdir(parents=True, exist_ok=True)
    _OUT = open(report, "w", encoding="utf-8", newline="\n")
    try:
        log("=" * 70)
        log("  make_delivery_zip.py —— 发布目录打成单个 zip")
        log("=" * 70)
        log(f"时间 : {datetime.datetime.now().isoformat(timespec='seconds')}")
        log(f"机器 : {platform.node()} / {platform.platform()}")
        log(f"脚本 : {Path(__file__).name}  sha16={sha256_file(Path(__file__).resolve())[:16]}")
        log(f"源   : {src}")
        log(f"输出 : {out}")
        log("")
        if not src.is_dir():
            log(f"RESULT: FAIL 源目录不存在：{src}")
            return 1
        files = sorted((p for p in src.rglob("*")
                        if p.is_file() and p.resolve() != out.resolve()),
                       key=lambda p: p.relative_to(src).as_posix())
        raw = sum(p.stat().st_size for p in files)
        log(f"[1] 收集 {len(files)} 个文件，原始 {raw/1024/1024:.2f} MB")

        log("[2] 空转门禁：先故意改坏一个条目，自检必须报红")
        tmp = Path(tempfile.mkdtemp(prefix="zipcheck_"))
        bad = tmp / "_selfcheck_bad.zip"
        write_zip(src, bad, files)
        with zipfile.ZipFile(bad, "a") as z:
            z.writestr(zipfile.ZipInfo("__ghost__.txt", date_time=FIXED_TIME), b"x")
        ok, problems = verify(src, bad)
        shutil.rmtree(tmp)
        # 报红的原因也必须是那条幽灵 —— 只要红就算过的话，搜出别的问题也会被当成通过
        if ok or not any("__ghost__.txt" in p for p in problems):
            log("    [FAIL] 自检没按预期报红 —— 这个校验不可信，停止")
            for p in problems:
                log("        " + p)
            log("RESULT: FAIL")
            return 1
        log("    [OK] 按预期报红：" + next(p for p in problems if "__ghost__.txt" in p))

        log("[3] 打包")
        out.parent.mkdir(parents=True, exist_ok=True)
        write_zip(src, out, files)
        size = out.stat().st_size
        log(f"    {out.name}  {size/1024/1024:.2f} MB  压缩率 {100*size/raw:.1f}%")

        log("[4] 回读逐条目核 sha256")
        ok, problems = verify(src, out)
        for p in problems:
            log("    [FAIL] " + p)
        log(f"    {'[OK] 全部一致' if ok else '[FAIL] 有不一致'}")
        log("")
        log(f"zip  sha256 = {sha256_file(out)}")
        log(f"zip  sha16  = {sha256_file(out)[:16]}")
        log(f"包装后大小  = {size:,} B")
        log("")
        log(f"RESULT: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    except Exception:
        log("[!!] 完整堆栈（不截断）：")
        log(traceback.format_exc())
        log("RESULT: FAIL")
        return 1
    finally:
        _OUT.close()
        print("report ->", report, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
