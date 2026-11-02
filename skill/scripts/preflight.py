#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写码前的机械检查 —— 专抓「会静默炸」的那几类，判断类的留给 references。

用法：
    python preflight.py <文件或目录> [...]        # 检查
    python preflight.py --selftest                # 证明本工具能判红 / 能判绿

检查项（全部机械可判，不是判断题）：
    [红] .py 的字符串字面量里有 GBK 编不进去的字符，而文件又在用 print/sys.stdout.write
         ⇒ 本机 stdout 是 GBK，一 print 就 UnicodeEncodeError，且**一个字节都不出**
    [红] .bat 含非 ASCII 字节   ⇒ cmd 按 GBK 拆行，注释会变成命令
    [红] .bat 用了 LF 行尾        ⇒ 同上
    [黄] 字符串字面量里同时有非 ASCII 和路径分隔符 ⇒ cv2.imread 返回 None、Vivado/HLS 直接挂
    [黄] 有写文件的迹象但全文没有 flush()        ⇒ 崩了就什么都不留（references/14 H 组）

退出码：0 = 无红；1 = 有红。
报告：默认写 <cwd>/_preflight.log（超过 2 MB 下次启动轮转成 .1），与屏幕逐字相同。
"""
import ast
import hashlib
import io
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(os.getcwd(), '_preflight.log')
_fh = None


def _open_log():
    global _fh
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 2 << 20:
            os.replace(LOG, LOG + '.1')
        _fh = io.open(LOG, 'a', encoding='utf-8', newline='\n')
    except OSError:
        _fh = None


def say(s=''):
    t = (s if isinstance(s, str) else str(s)) + '\n'
    if _fh is not None:
        _fh.write(t)
        _fh.flush()
    sys.stdout.buffer.write(t.encode('utf-8', 'replace'))
    sys.stdout.buffer.flush()


def sha16_bytes(b):
    return hashlib.sha256(b).hexdigest()[:16]


def gbk_ok(ch):
    try:
        ch.encode('gbk')
        return True
    except UnicodeEncodeError:
        return False


def read_text(p):
    b = open(p, 'rb').read()
    for enc in ('utf-8', 'gbk'):
        try:
            return b.decode(enc), enc, b
        except UnicodeDecodeError:
            continue
    return None, None, b


# ── 检查 1：.py 字符串字面量里的 GBK 死字符 ─────────────────────────
# 只认「Windows 绝对路径」：盘符开头 或 UNC。绝不能只凭含 '/' 就判 ——
# 'auto/legacy' 这种枚举值会被误伤，实测误报 448 条，检查器当场变成没人看的噪音。
PATH_RE = re.compile(r'^(?:[A-Za-z]:[\\/]|\\\\)')


def _is_stdout_write(node):
    if not isinstance(node, ast.Attribute) or node.attr != 'write':
        return False
    try:
        return 'stdout' in ast.unparse(node.value)
    except Exception:
        return False


def _printed_constants(tree):
    """只收 print(...) / sys.stdout.write(...) 的实参里的字符串 —— 只有它们真会打到控制台。

    已知盲区：包了一层自己写的 say()/log() 就查不出来。宁可漏，不可噪音。
    """
    got = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not ((isinstance(f, ast.Name) and f.id == 'print') or _is_stdout_write(f)):
            continue
        for a in node.args:
            for sub in ast.walk(a):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    got.append(sub)
    return got


def check_py(p):
    out = []
    text, enc, _ = read_text(p)
    if text is None:
        return [('黄', p, 0, '既不是 UTF-8 也不是 GBK，跳过')]
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [('红', p, e.lineno or 0, '语法错误，无法解析：%s' % e.msg)]

    seen = set()
    for node in _printed_constants(tree):
        if id(node) in seen:
            continue
        seen.add(id(node))
        bad = sorted({c for c in node.value if not gbk_ok(c)})
        if bad:
            out.append(('红', p, node.lineno,
                        'print/stdout.write 的字符串里有 GBK 编不进去的字符 %r ⇒ 本机控制台是 GBK，'
                        '跑到这一行就 UnicodeEncodeError，且此前的输出可能一个字都没落地' % (bad,)))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if len(v) > 3 and PATH_RE.match(v) and any(ord(c) > 127 for c in v):
                out.append(('黄', p, node.lineno,
                            'Windows 路径字面量含非 ASCII：%r ⇒ cv2.imread 返回 None 不报错；'
                            'Vivado/HLS 直接挂（14 的 F 组）' % (v[:60],)))

    writes = ("'w'" in text) or ('"w"' in text)
    if writes and 'flush(' not in text:
        out.append(('黄', p, 0, '有写文件迹象但全文没有 flush() ⇒ 崩了就什么都不留（14 的 H 组）'))
    return out


# ── 检查 2/3：.bat 必须纯 ASCII + CRLF ──────────────────────────────
def check_bat(p):
    b = open(p, 'rb').read()
    out = []
    hi = [i for i, x in enumerate(b) if x > 0x7F]
    if hi:
        ln = b[:hi[0]].count(b'\n') + 1
        out.append(('红', p, ln, '含 %d 个非 ASCII 字节（首个在偏移 %d）⇒ cmd 按 GBK 拆行'
                    % (len(hi), hi[0])))
    lf = b.count(b'\n')
    crlf = b.count(b'\r\n')
    if lf and lf != crlf:
        out.append(('红', p, 0, '%d 个 LF 里只有 %d 个是 CRLF ⇒ 必须全部 CRLF'
                    % (lf, crlf)))
    return out


MAP = {'.py': check_py, '.bat': check_bat, '.cmd': check_bat}


def walk(targets):
    for t in targets:
        if os.path.isfile(t):
            yield t
        else:
            for root, dirs, files in os.walk(t):
                dirs[:] = [d for d in dirs
                           if d not in ('.git', '__pycache__', '.venv', 'node_modules')]
                for f in files:
                    yield os.path.join(root, f)


def run(targets):
    say('=' * 92)
    say('# 写码前机械检查   %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('#   主机 %s   python %s   cwd %s'
        % (os.environ.get('COMPUTERNAME', '?'), sys.version.split()[0], os.getcwd()))
    say('#   脚本 %s  sha16 %s'
        % (os.path.abspath(__file__), sha16_bytes(open(__file__, 'rb').read())))
    say('#   判据：GBK(cp936) 能不能编进去 —— 本机 stdout 就是 GBK')
    say('=' * 92)
    nf = nred = nyel = 0
    findings = []
    for p in walk(targets):
        fn = MAP.get(os.path.splitext(p)[1].lower())
        if fn is None:
            continue
        nf += 1
        try:
            findings.extend(fn(p))
        except Exception as e:
            findings.append(('黄', p, 0, '检查器自己抛了 %s: %s' % (type(e).__name__, e)))
    say('')
    say('扫了 %d 个 .py/.bat 文件' % nf)
    if not findings:
        say('')
        say('【绿】没有命中任何一条')
    for sev, p, ln, msg in findings:
        if sev == '红':
            nred += 1
        else:
            nyel += 1
        say('')
        say('[%s] %s%s' % (sev, p, (':%d' % ln) if ln else ''))
        say('      %s' % msg)
    say('')
    say('合计：红 %d、黄 %d' % (nred, nyel))
    say('退出码 %d（1 = 有红，别往下跑）' % (1 if nred else 0))
    say('')
    say('# 报告：%s' % LOG)
    return 1 if nred else 0


# ── 自检：先证明能判红，再证明能判绿 ────────────────────────────────
BAD_PY = ('# -*- coding: utf-8 -*-\nprint("\u26a0 \u2605")\n'
          'print("\u2713 \u2717")\n'
          'P = "D:/study/\u4e2d\u6587/sub"\n'
          'open("x", "w")\n')
# GOOD_PY 里故意塞了两个「曾经的误报陷阱」：docstring 里的 ⇒⚠✓、枚举值 'auto/legacy' 里的斜杠。
# 它们一个都不许报 —— 误报一次，这个检查器就再也没人看。
GOOD_PY = ('# -*- coding: utf-8 -*-\n'
           '"""\u6ce8\u91ca\u91cc\u5199 \u21d2 \u26a0 \u2713 \u662f\u5b89\u5168\u7684\uff1a'
           '\u4e0d\u4f1a\u88ab\u6253\u5230\u63a7\u5236\u53f0"""\n'
           'import sys\n'
           'MODE = "auto/legacy"\n'
           'SOLVER = "qr/svd"\n'
           'def say(s):\n'
           '    sys.stdout.buffer.write((s + "\\n").encode("utf-8", "replace"))\n'
           '    sys.stdout.buffer.flush()\n'
           'say("\u26a0 \u2605 \u4e2d\u6587")\n')
BAD_BAT = b'@echo off\r\necho \xd6\xd0\xce\xc4\r\necho hi\n'
GOOD_BAT = b'@echo off\r\necho hi\r\n'


def selftest():
    say('=' * 92)
    say('# preflight 自检（证明它能判红、也能判绿）   %s'
        % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('#   主机 %s   脚本 sha16 %s'
        % (os.environ.get('COMPUTERNAME', '?'),
           sha16_bytes(open(__file__, 'rb').read())))
    say('=' * 92)
    d = tempfile.mkdtemp()
    try:
        cases = []
        for name, content in (('bad.py', BAD_PY), ('good.py', GOOD_PY)):
            fp = os.path.join(d, name)
            io.open(fp, 'w', encoding='utf-8', newline='').write(content)
            cases.append((name, fp))
        for name, content in (('bad.bat', BAD_BAT), ('good.bat', GOOD_BAT)):
            fp = os.path.join(d, name)
            open(fp, 'wb').write(content)
            cases.append((name, fp))

        allpass = True
        for name, fp in cases:
            fn = MAP[os.path.splitext(name)[1]]
            got = fn(fp)
            reds = sum(1 for g in got if g[0] == '红')
            yels = len(got) - reds
            want_red = name.startswith('bad')
            # good 的判据是【一条都不报】—— 误报和漏报一样致命，噪音会让整个检查器被无视
            ok = (reds > 0) if want_red else (reds == 0 and yels == 0)
            allpass &= ok
            say('')
            say('  %-9s 期望 %s ⇒ 实得 红%d 黄%d   %s'
                % (name, '有红' if want_red else '全静默', reds, yels,
                   '合格' if ok else '不合格'))
            for sev, _p, ln, msg in got:
                say('      [%s] %s' % (sev, msg[:100]))
        say('')
        if allpass:
            say('【自检通过】能判红（bad 都报红）也能判绿（good 都不报红）')
        else:
            say('【自检失败】这个检查器本身不可信，别拿它的绿当结论')
        return 0 if allpass else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    _open_log()
    try:
        a = sys.argv[1:]
        if not a or a[0] in ('-h', '--help'):
            say(__doc__)
            sys.exit(0)
        rc = selftest() if a[0] == '--selftest' else run(a)
    finally:
        if _fh is not None:
            _fh.close()
    sys.exit(rc)
