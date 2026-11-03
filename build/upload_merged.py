#!/usr/bin/env python3
"""把合并发布目录整包传到板上 super/ 下，并逐文件核 sha256。

    python build/upload_merged.py [本地目录] [远端目录]

默认：
  本地 D:\\study\\competition\\qian\\_runtime_build\\p11_fps33_20261101_merged
  远端 /home/xilinx/jupyter_notebooks/super/p11_fps33_20261101_merged

流程（先传 staging、验完再就地覆盖）：
  1. SFTP 传到 /tmp/<name>.new（板上普通用户可写）
  2. 板端逐文件算 sha256，与本地现算值比对，不一致就中止、不动目标目录
  3. sudo cp -a staging/. → 目标目录（**不换 inode**，正在跑的 Jupyter 内核 cwd 不会失效）
  4. 清掉上一版多出来的文件，再逐文件核一遍 sha256
  5. 删掉 staging

⛔ 为什么不用「mv 老目录再换新的」：2026-11-02 实踩 —— Jupyter 内核 cwd 指向老目录 inode，
   `rm -rf` 之后内核里 `Path.cwd()` 直接 `FileNotFoundError: [Errno 2]`，用户得重启内核。

⛔ 只碰 `<远端目录>` 及其 `.old`/`.new` 临时目录，队友目录一个字不碰。
"""
import datetime
import hashlib
import io
import platform
import posixpath
import sys
import traceback
from pathlib import Path

import paramiko

HOST = "192.168.2.99"
USER = "xilinx"
PASSWORD = "xilinx"
# 本地源目录默认跟着仓库走（clone 到别处也能跑）；第 1 个参数可覆盖
LOCAL = Path(__file__).resolve().parent.parent.parent / "_runtime_build" / "p11_fps33_20261101_merged"
REMOTE = "/home/xilinx/jupyter_notebooks/super/p11_fps33_20261101_merged"
REPORT = Path(__file__).resolve().parent / "reports" / "upload_merged_report.txt"
_REPORT = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def main():
    global _REPORT
    local = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else LOCAL
    remote = sys.argv[2] if len(sys.argv) > 2 else REMOTE
    staging = "/tmp/" + posixpath.basename(remote) + ".new"
    old = remote + ".old"

    # 报告按远端目录名区分，别让第二次上传覆盖第一次的留痕
    report = (REPORT if remote == REMOTE
              else REPORT.with_name(f"upload_merged_{posixpath.basename(remote)}_report.txt"))
    report.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(report, "w", encoding="utf-8", newline="\n")
    for h in ["=" * 78,
              "  upload_merged.py —— 合并发布包上板 + 逐文件 sha256 复核",
              "=" * 78,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"脚本   : {Path(__file__).name}  sha16={sha256_bytes(Path(__file__).read_bytes())[:16]}",
              f"本地   : {local}",
              f"远端   : {USER}@{HOST}:{remote}",
              "=" * 78, ""]:
        log(h)

    try:
        # ⛔ Git Bash(MSYS) 会把「像 POSIX 路径」的参数改写成 Windows 路径。
        #    2026-11-03 实踩：/home/xilinx/... 变成 D:/Program Files/Git/home/...，
        #    到了板上被空格拆成两段，在 /home/xilinx 下建出 `D:` 和 `Files` 两个垃圾目录。
        #    跑法必须是 `MSYS_NO_PATHCONV=1 python build/upload_merged.py ...`。
        #    这里兜一道：宁可现在拒绝，也不要把包写到一个莫名其妙的地方。
        if not remote.startswith("/") or any(ch in remote for ch in " :"):
            raise RuntimeError(
                "远端路径不像 POSIX 绝对路径：%r\n"
                "  多半是 Git Bash 把参数改写了 —— 用 MSYS_NO_PATHCONV=1 前缀重跑。" % (remote,))
        files = sorted(p for p in local.rglob("*") if p.is_file())
        rel = [(p, p.relative_to(local).as_posix()) for p in files]
        log(f"[1] 本地 {len(rel)} 个文件，{sum(p.stat().st_size for p in files):,} B")
        want = {r: sha256_bytes(p.read_bytes()) for p, r in rel}

        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(HOST, username=USER, password=PASSWORD, timeout=20)
        log(f"[2] SSH 已连上 {HOST}")

        def sh(cmd):
            _, out, err = cli.exec_command(cmd, timeout=300)
            rc = out.channel.recv_exit_status()
            return rc, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")

        rc, o, e = sh(f"rm -rf {staging} && mkdir -p {staging}")
        if rc != 0:
            raise RuntimeError(f"建 staging 失败 rc={rc}\n{o}\n{e}")

        sftp = cli.open_sftp()
        dirs = sorted({posixpath.dirname(r) for _, r in rel} - {""})
        for d in dirs:
            rc, o, e = sh(f"mkdir -p {staging}/{d}")
            if rc != 0:
                raise RuntimeError(f"建目录 {d} 失败 rc={rc}\n{o}\n{e}")
        for i, (p, r) in enumerate(rel, 1):
            sftp.put(str(p), f"{staging}/{r}")
            if i % 25 == 0 or i == len(rel):
                log(f"    上传 {i}/{len(rel)}")
        sftp.close()

        log("[3] 板端逐文件算 sha256 复核")
        rc, o, e = sh(f"cd {staging} && find . -type f | sort | xargs -d '\\n' sha256sum")
        if rc != 0:
            raise RuntimeError(f"板端 sha256sum 失败 rc={rc}\n{o}\n{e}")
        got = {}
        for line in o.splitlines():
            if not line.strip():
                continue
            h, name = line.split(None, 1)
            got[name.strip().lstrip("./")] = h
        bad = [(r, want[r], got.get(r)) for r in want if got.get(r) != want[r]]
        extra = sorted(set(got) - set(want))
        log(f"    远端实数 {len(got)} / 本地 {len(want)}；不一致 {len(bad)}；多出 {len(extra)}")
        for r, w, g in bad[:20]:
            log(f"    ✗ {r}\n        本地 {w}\n        远端 {g}")
        for r in extra[:20]:
            log(f"    ✗ 多出 {r}")
        if bad or extra:
            raise RuntimeError("sha256 复核未通过，老目录原样保留，已中止")

        # ⛔ 别再用「mv 老目录 → 换新的」：2026-11-02 实踩 —— Jupyter 内核的 cwd 指向
        #    老目录的 inode，`rm -rf .old` 之后内核里 `Path.cwd()` 直接
        #    FileNotFoundError: [Errno 2]，用户必须重启内核才能继续。
        #    就地覆盖（cp -a 到已存在的目录）不动 inode，内核照常活着。
        log("[4] 就地覆盖到目标目录（不换 inode，正在跑的内核 cwd 不会失效）")
        cmd = (f"echo xilinx | sudo -S -p '' sh -c "
               f"'mkdir -p {remote} && cp -a {staging}/. {remote}/ && chown -R {USER}:{USER} {remote}'")
        rc, o, e = sh(cmd)
        log(f"    rc={rc}  stdout={o.strip()!r}  stderr={e.strip()!r}")
        if rc != 0:
            raise RuntimeError(f"覆盖失败 rc={rc}")

        # staging 里没有、目标里还留着的旧文件（上一版多出来的）要清掉，但只清文件
        rc, o, e = sh(f"cd {remote} && find . -type f | sed 's|^\\./||' | sort")
        stale = [x for x in o.splitlines() if x.strip() and x not in want]
        if stale:
            log(f"    清掉 {len(stale)} 个上一版残留：{stale[:6]}{' …' if len(stale) > 6 else ''}")
            rc, o, e = sh("echo xilinx | sudo -S -p '' sh -c 'cd %s && rm -f %s'"
                          % (remote, " ".join("'" + x.replace("'", "'\\''") + "'" for x in stale)))
            if rc != 0:
                raise RuntimeError(f"清残留失败 rc={rc}\n{o}\n{e}")

        log("[5] 覆盖完再核一遍（目标路径，不是 staging）")
        rc, o, e = sh(f"cd {remote} && find . -type f | sort | xargs -d '\\n' sha256sum")
        if rc != 0:
            raise RuntimeError(f"复核失败 rc={rc}\n{o}\n{e}")
        got2 = {}
        for line in o.splitlines():
            if not line.strip():
                continue
            h, name = line.split(None, 1)
            got2[name.strip().lstrip("./")] = h
        bad2 = [r for r in want if got2.get(r) != want[r]]
        log(f"    目标路径实数 {len(got2)}；不一致 {len(bad2)}")
        if bad2 or set(got2) != set(want):
            raise RuntimeError(f"最终复核未通过：{len(bad2)} 个不一致，多出 {sorted(set(got2)-set(want))[:10]}")

        rc, o, e = sh(f"rm -rf {staging}")
        log(f"[6] 删掉 staging {staging}（rc={rc}）")

        rc, o, e = sh(f"ls -ld {remote}; ls {remote} | head -20")
        log("[7] 板上现状：")
        for line in (o or e).splitlines():
            log("    " + line)

        log("")
        log("=" * 78)
        log(f"上传 {len(want)} 个文件，逐文件 sha256 全部一致")
        log("RESULT: PASS")
        cli.close()
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
