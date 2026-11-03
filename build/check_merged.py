#!/usr/bin/env python3
"""合并版运行目录自检：语法 / 完整性闸门 / 模块身份。

    python build/check_merged.py <运行目录>

检查项：
  A. 6 个文件都能按 Python 3.10 语法解析（板端就是 3.10.4）
  B. 6 个文件都能导入
  C. 每个层文件都有 RELEASE_ID 与 _SOURCE_SHA256
  D. p11_contract.verify_package('system.bit') 真能通过（逐文件核 sha256）
  E. 故意改坏一个字节 → 必须报错（证明闸门不是永远通过）
"""
import datetime
import hashlib
import io
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORT = REPO / "build" / "reports" / "check_merged_report.txt"
LAYERS = ("core", "geometry", "tracking", "display", "ai", "ui")
PROTOCOL = REPO / "src" / "ps" / "ui" / "v99_ai_protocol.py"
_REPORT = None


def _recv_frame(sock, timeout):
    """读一帧：4 字节大端长度 + JSON。与 v99_ai_protocol.send_message 的线格式一致。"""
    sock.settimeout(timeout)
    head = b""
    while len(head) < 4:
        chunk = sock.recv(4 - len(head))
        if not chunk:
            raise EOFError("AI 子进程在帧头处断开")
        head += chunk
    size = struct.unpack("!I", head)[0]
    body = b""
    while len(body) < size:
        chunk = sock.recv(size - len(body))
        if not chunk:
            raise EOFError("AI 子进程在帧体处断开")
        body += chunk
    return json.loads(body)


def _probe_worker(worker, manifest_src, v98_src, timeout=60.0):
    """真起一次 AI 子进程，返回它发回来的消息列表和 stderr 全文。

    只在临时目录里跑：把那两个清单和 worker 放一起，不污染发布目录。
    """
    tmp = Path(tempfile.mkdtemp(prefix="p11ai_probe_")).resolve()
    out = err = conn = listener = proc = None
    got = []
    failure = None
    try:
        shutil.copy2(worker, tmp / "v99_ai_worker.py")
        shutil.copy2(manifest_src, tmp / "release_manifest.json")
        shutil.copy2(v98_src, tmp / "v98_ai_manifest.json")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        out = open(tmp / "stdout.log", "wb")
        err = open(tmp / "stderr.log", "wb")
        proc = subprocess.Popen(
            [sys.executable, "-u", "-B", str(tmp / "v99_ai_worker.py"),
             "--socket", f"tcp:127.0.0.1:{port}", "--nonce", "probe-" + os.urandom(8).hex()],
            cwd=str(tmp), stdout=out, stderr=err)
        listener.settimeout(timeout)
        try:
            conn, _ = listener.accept()
        except socket.timeout:
            raise TimeoutError("AI 子进程没有连过来")
        # 一直读到终结帧：ready（真板）或 error（本机的平台断言）—— 中间会有 stage 帧
        for _ in range(20):
            try:
                msg = _recv_frame(conn, 120.0)
            except (EOFError, OSError, socket.timeout):
                break
            got.append(msg)
            if msg.get("type") in ("ready", "error"):
                break
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if proc is not None:
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for f in (out, err):
            if f is not None:
                f.close()
    stderr_text = ""
    log_path = tmp / "stderr.log"
    if log_path.is_file():
        stderr_text = log_path.read_text(encoding="utf-8", errors="replace")
    shutil.rmtree(tmp, ignore_errors=True)
    return got, stderr_text, failure



def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def main():
    global _REPORT
    if len(sys.argv) != 2:
        print("用法: python build/check_merged.py <运行目录>")
        return 2
    root = Path(sys.argv[1]).resolve()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(REPORT, "w", encoding="utf-8", newline="\n")
    for h in ["=" * 70,
              "  check_merged.py —— 合并版运行目录自检",
              "=" * 70,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
              f"运行目录: {root}",
              "=" * 70, ""]:
        log(h)
    fails = []
    try:
        import ast
        # ---- A. 3.10 语法 ----
        log("[A] 按 Python 3.10 语法解析")
        for n in LAYERS:
            src = (root / (n + ".py")).read_text(encoding="utf-8")
            try:
                ast.parse(src, filename=n + ".py", feature_version=(3, 10))
                log(f"    OK   {n}.py  {len(src.splitlines()):,} 行")
            except SyntaxError as e:
                fails.append(f"A/{n}")
                log(f"    FAIL {n}.py  {e}")
        log("")

        # ---- B/C/D ----
        sys.path.insert(0, str(root))
        for h in [str(REPO)]:
            if h in sys.path:
                sys.path.remove(h)
        stubs = REPO / "build" / "_stubs"
        if stubs.is_dir():
            sys.path.append(str(stubs))
            log(f"    桩目录 {stubs}（Windows 没有 fcntl，板上是真的）")
        log("")

        log("[B] 逐个导入")
        for n in LAYERS:
            try:
                __import__(n)
                log(f"    OK   {n}")
            except Exception as e:
                fails.append(f"B/{n}")
                log(f"    FAIL {n}: {type(e).__name__}: {e}")
                log(traceback.format_exc())
        log("")

        log("[C] RELEASE_ID / _SOURCE_SHA256")
        core = sys.modules.get("core")
        want = getattr(core, "RELEASE_ID", None)
        log(f"    RELEASE_ID = {want}")
        for n in LAYERS:
            m = sys.modules.get(n)
            if m is None:
                fails.append(f"C/{n}")
                log(f"    FAIL {n} 没导入")
                continue
            rid = getattr(m, "RELEASE_ID", None)
            sha = getattr(m, "_SOURCE_SHA256", None)
            real = hashlib.sha256((root / (n + ".py")).read_bytes()).hexdigest()
            ok = (rid == want and sha == real)
            log(f"    {'OK  ' if ok else 'FAIL'} {n}: RELEASE_ID={'一致' if rid == want else rid}"
                f"  _SOURCE_SHA256={'一致' if sha == real else sha}")
            if not ok:
                fails.append(f"C/{n}")
        log("")

        bit_abs = str(root / "system.bit")
        log("[D] verify_package(<运行目录>/system.bit) 真跑一遍")
        try:
            release = core.verify_package(bit_abs)
            log(f"    PASS layout={release.get('layout')} release_id={release.get('release_id')}"
                f" 校验文件 {len(release.get('sha256', {}))} 条")
        except Exception as e:
            fails.append("D/verify_package")
            log(f"    FAIL {type(e).__name__}: {e}")
            log(traceback.format_exc())
        log("")

        log("[E] 空转门禁：故意改坏 system.bit 再核一次，必须报「内容不一致」")
        bit = root / "system.bit"
        original = bit.read_bytes()
        try:
            bit.write_bytes(original[:-1] + bytes([original[-1] ^ 0xFF]))
            try:
                core._FILE_DIGESTS.clear()
                core.verify_package(bit_abs)
                fails.append("E/gate-blind")
                log("    FAIL 改坏了还是通过 —— 这个闸门是空转的")
            except Exception as e:
                msg = str(e)
                if "不一致" in msg or "配对" in msg:
                    log(f"    OK   按预期报「不一致」：{type(e).__name__}: {msg}")
                else:
                    fails.append("E/wrong-error")
                    log(f"    FAIL 报错了但不是内容校验：{type(e).__name__}: {msg}")
            finally:
                bit.write_bytes(original)
                core._FILE_DIGESTS.clear()
        finally:
            bit.write_bytes(original)
            core._FILE_DIGESTS.clear()
        log("")

        # ---- F. AI 子进程入口（合并后唯一一个「必须是真实文件」的模块） ----
        log("[F] AI 子进程入口 v99_ai_worker.py")
        worker = root / "v99_ai_worker.py"
        if not worker.is_file():
            fails.append("F/missing")
            log("    FAIL 发布目录里没有 v99_ai_worker.py —— AI 子进程会起不来")
        else:
            wsrc = worker.read_text(encoding="utf-8")
            log(f"    {len(wsrc.splitlines()):,} 行 / {len(wsrc.encode('utf-8')):,} B"
                f"  sha16={hashlib.sha256(wsrc.encode('utf-8')).hexdigest()[:16]}")

            # F1 板端语法
            try:
                ast.parse(wsrc, filename="v99_ai_worker.py", feature_version=(3, 10))
                log("    OK   F1 按 Python 3.10 语法解析")
            except SyntaxError as e:
                fails.append("F1/syntax")
                log(f"    FAIL F1 {e}")

            # F2 自包含：不许导入任何层文件（否则会把 cv2 拉进 AI 子进程）
            bad = [ln for ln in wsrc.splitlines()
                   if ln.lstrip().startswith(("from ", "import "))
                   and any(f"import {n}" in ln or f"from {n}" in ln
                           for n in ("core", "geometry", "tracking", "display", "ai", "ui",
                                     "p11_contract", "v99_ai_protocol"))]
            if bad:
                fails.append("F2/imports")
                log("    FAIL F2 生成文件里还有项目模块 import：")
                for ln in bad:
                    log("         " + ln)
            else:
                log("    OK   F2 自包含（没有导入任何层文件）")

            # F3 内联的协议函数与源模块逐函数 AST 相同
            try:
                proto_want = {}
                for node in ast.parse(PROTOCOL.read_text(encoding="utf-8")).body:
                    if isinstance(node, ast.FunctionDef):
                        proto_want[node.name] = ast.dump(node)
                got_nodes = {}
                for node in ast.parse(wsrc).body:
                    if isinstance(node, ast.FunctionDef):
                        got_nodes[node.name] = ast.dump(node)
                miss = sorted(n for n in proto_want if n not in got_nodes)
                diff = sorted(n for n in proto_want
                              if n in got_nodes and got_nodes[n] != proto_want[n])
                if miss or diff:
                    fails.append("F3/protocol")
                    log(f"    FAIL F3 缺 {miss}  不一致 {diff}")
                else:
                    log(f"    OK   F3 协议 {len(proto_want)} 个函数与源模块逐函数 AST 相同")
            except Exception as e:
                fails.append("F3/protocol")
                log(f"    FAIL F3 {type(e).__name__}: {e}")
                log(traceback.format_exc())

            # F4 真起一次子进程：必须收到 hello，且跑完资产校验才被平台断言拦下
            rel = root / "release_manifest.json"
            v98 = root / "v98_ai_manifest.json"
            if not v98.is_file():
                fails.append("F4/no-v98")
                log("    FAIL F4 发布目录里没有 v98_ai_manifest.json")
            else:
                got, stderr_text, failure = _probe_worker(worker, rel, v98)
                kinds = [m.get("type") for m in got]
                log(f"    子进程回了 {len(got)} 帧：{kinds}  启动异常={failure}")
                # 本机不是 ARMv7，所以正确路径必然是：hello -> … -> error(ARMv7)。
                # 若 RELEASE_ID 和 v98 清单对不上，这里会是 "AI manifest version mismatch"。
                ok = (len(got) >= 2 and kinds[0] == "hello" and kinds[-1] == "error"
                      and "ARMv7" in str(got[-1].get("error", "")))
                if got and got[0].get("type") == "hello":
                    same = got[0].get("release_id") == want
                    log(f"         hello.release_id={'一致' if same else got[0].get('release_id')}"
                        f"（本包 {want}）")
                    if not same:
                        fails.append("F4/release-id")
                if ok:
                    log("    OK   F4 握手通过 + 走到平台断言（说明 RELEASE_ID 与 v98 清单对上了）")
                else:
                    fails.append("F4/probe")
                    for m in got:
                        log(f"         {json.dumps(m, ensure_ascii=False)}")
                    if stderr_text:
                        log("         --- 子进程 stderr 全文 ---")
                        log(stderr_text)
                    log(f"         {failure or ''}")

                # F5 判红：把 RELEASE_ID 的取键改错，必须收不到 hello
                mutated = wsrc.replace("['release_id']", "['release_idx']")
                if mutated == wsrc:
                    fails.append("F5/not-mutable")
                    log("    FAIL F5 找不到可改坏的位置，判红环节是空转的")
                else:
                    tmpdir = Path(tempfile.mkdtemp(prefix="p11ai_bad_")).resolve()
                    try:
                        badf = tmpdir / "v99_ai_worker.py"
                        badf.write_text(mutated, encoding="utf-8", newline="\n")
                        bad_got, _, bad_fail = _probe_worker(badf, rel, v98)
                        if any(m.get("type") == "hello" for m in bad_got):
                            fails.append("F5/gate-blind")
                            log("    FAIL F5 改坏了还能握手 —— 这个闸门是空转的")
                        else:
                            log(f"    OK   F5 判红有效（改坏后握手不上：{bad_fail}）")
                    finally:
                        shutil.rmtree(tmpdir, ignore_errors=True)
        log("")

        log("=" * 70)
        log("RESULT: " + ("PASS" if not fails else "FAIL  " + ", ".join(fails)))
        return 0 if not fails else 1
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
