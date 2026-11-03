#!/usr/bin/env python3
"""生成合并版发布包里那两个「必须是真实文件」的 AI 入口。

为什么必须有这个东西
--------------------
合并只处理 **import**。这两处不是 import，是**被别的进程当文件拉起**：

  v99_ai_service.py:276   subprocess.Popen([python,'-u','-B', str(root/'v99_ai_worker.py'), ...])
  ai_selftest.ipynb        subprocess.Popen([sys.executable,'-u','-B', str(ROOT/'v99_ai_selftest.py')])

合并成 6 个文件之后这两个文件就不存在了，AI 通路和自检都会直接起不来。
但也不能简单把 import 改成 `from core import ...`：

  * `core.py` 顶层 `import cv2,numpy` —— 而 worker 的全部意义就是
    "Lean resident inference only: no OpenCV"，且板上只有 512 MB 内存
  * 自检脚本同理，它要在不碰摄像头的纯 CPU 环境里跑

所以这里生成**自包含**版本：
  * `send_message / recv_message / connect_address / recv_exact`（+ 两个常量）
    按**原文本切片**内联 —— 不走 ast.unparse，注释一个字不丢（只有 worker 需要）
  * `from p11_contract import RELEASE_ID` 改成读同目录的 `release_manifest.json`
    —— 与发布清单同源，不复制常量，也就不会漂移

一致性由 `build/check_merged.py` 的 F 项守：协议函数与
`src/ps/ui/v99_ai_protocol.py` 逐函数 AST 比对，不一致就判红；并真起一次子进程验握手。

    python build/make_ai_entries.py <输出目录>
"""
import ast
import datetime
import hashlib
import io
import platform
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "src" / "ps" / "ui"
PROTOCOL = UI / "v99_ai_protocol.py"
REPORT = REPO / "build" / "reports" / "make_ai_entries_report.txt"

RELEASE_LINE = "from p11_contract import RELEASE_ID"

# 从协议模块里搬过来的顶层语句（按源文件顺序输出）
TAKE = ("MAX_HEADER", "FRAME_BYTES",
        "connect_address", "recv_exact", "send_message", "recv_message")

ENTRIES = [
    dict(
        name="v99_ai_worker.py",
        src=UI / "v99_ai_worker.py",
        inline_protocol=True,
        drop="from v99_ai_protocol import send_message,recv_message,connect_address",
        # 内联的协议函数要用 socket
        imports_swap=("import argparse,hashlib,json,os,platform,struct,sys,time",
                      "import argparse,hashlib,json,os,platform,socket,struct,sys,time"),
    ),
    dict(
        name="v99_ai_selftest.py",
        src=UI / "v99_ai_selftest.py",
        inline_protocol=False,
        drop=None,
        imports_swap=None,
    ),
]

_RE = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def find_one(lines, needle):
    """整行精确匹配；命中数必须正好 1，否则直接抛 —— 不许静默空转。"""
    hits = [i for i, ln in enumerate(lines) if ln.rstrip("\r\n") == needle]
    if len(hits) != 1:
        raise ValueError(f"要在源文件里找到且只找到一行：{needle!r}；实际 {len(hits)} 行")
    return hits[0]


def protocol_body():
    """按原文本切出协议的 6 条顶层语句。"""
    src = PROTOCOL.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    picked = {}
    for node in tree.body:
        name = None
        if isinstance(node, ast.FunctionDef):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in TAKE:
            picked[name] = "\n".join(lines[node.lineno - 1:node.end_lineno])
    missing = [n for n in TAKE if n not in picked]
    if missing:
        raise ValueError("协议模块里找不到：" + ", ".join(missing))
    return "\n\n\n".join(picked[n] for n in TAKE)


RELEASE_BLOCK = '''\
# ---- 与发布清单同源：子进程不导入 core（core 顶层 import cv2/numpy）----
def _release_id():
    """版本号从 release_manifest.json 读，和 p11_contract.RELEASE_ID 是同一份底本。"""
    return json.loads((Path(__file__).resolve().parent / 'release_manifest.json')
                      .read_text(encoding='utf-8'))['release_id']
RELEASE_ID = _release_id()'''

BANNER = """\
# ⚠️ 本文件由 build/make_ai_entries.py 生成，不要直接编辑。
#    源头：src/ps/ui/{src}（+ src/ps/ui/v99_ai_protocol.py）
#    改动请改源头，然后重跑 `python build/make_ai_entries.py <输出目录>`。
"""


def build(spec):
    lines = spec["src"].read_text(encoding="utf-8").splitlines(keepends=True)
    i_rel = find_one(lines, RELEASE_LINE)
    # 先换靠后的，避免前面的替换改变行号
    if spec["inline_protocol"]:
        i_pro = find_one(lines, spec["drop"])
        lines[i_pro] = ("# ---- 以下 6 条来自 v99_ai_protocol.py，按原文本内联（本文件要能单独跑）----\n"
                        + protocol_body() + "\n")
    if spec["imports_swap"]:
        i_imp = find_one(lines, spec["imports_swap"][0])
        lines[i_imp] = lines[i_imp].replace(*spec["imports_swap"])
    lines[i_rel] = RELEASE_BLOCK + "\n"
    lines.insert(1, BANNER.format(src=spec["src"].name))
    return "".join(lines)


def check_self_contained(text):
    """生成结果不许再导入任何项目模块。"""
    bad = [ln for ln in text.splitlines()
           if ln.lstrip().startswith(("from ", "import "))
           and any(f"import {n}" in ln or f"from {n}" in ln
                   for n in ("core", "geometry", "tracking", "display", "ai", "ui",
                             "p11_contract", "v99_ai_protocol", "run_logging"))]
    if bad:
        raise ValueError("生成结果里还有项目模块 import：\n" + "\n".join(bad))


def main():
    global _REPORT
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO / "build" / "_scratch" / "ai_entries"
    out.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(REPORT, "w", encoding="utf-8", newline="\n")
    for h in ["=" * 70,
              "  make_ai_entries.py —— 生成自包含的 AI 独立入口",
              "=" * 70,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
              f"输出   : {out}",
              "=" * 70, ""]:
        log(h)
    try:
        for spec in ENTRIES:
            text = build(spec)
            ast.parse(text, filename=spec["name"], feature_version=(3, 10))
            check_self_contained(text)
            dest = out / spec["name"]
            dest.write_text(text, encoding="utf-8", newline="\n")
            log(f"[+] {spec['name']:<22} {len(text.splitlines()):>4} 行 / "
                f"{len(text.encode('utf-8')):>7,} B  "
                f"sha16={hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
                f"  （源 {len(spec['src'].read_text(encoding='utf-8').splitlines())} 行）")
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
