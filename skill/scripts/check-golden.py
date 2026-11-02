#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动比对黄金参考 —— 产出目录 vs 参考目录，逐项判定，三态，分母写清楚。

用法：
    python check-golden.py --ref <目录或文件> --out <目录或文件> [选项]
    python check-golden.py --selftest

工作方式（黄金参考怎么来）：
    先用**已知正确**的那一版跑一遍，把产物留一份当参照（很多版本管理工具叫 golden /
    baseline）。之后每次改动都拿新产物跟它比。这样「改坏了」当场就能看出来，
    而不是等到上板或者答辩前才发现。

选项：
    --pixel-tol N     差多少才算「这个像素不一样」（默认 0 = 差 1 就算）
    --pct-tol P       允许多大比例的像素不一样，**单位是百分比**（默认 0）
                      例：--pixel-tol 2 --pct-tol 0.05 = 差 ≤2 的像素不算数，
                          但不一样的像素最多只能占 0.05%
                      ⚠️ 判定只看 pct-tol；pixel-tol 只负责定义「算不算不同」
    --psnr-min DB     PSNR 下限（默认不判；只对 8/16 位整型图有效）
    --text-tol F      文本比对时，数字允许的绝对误差（默认 0 = 逐字符严格）
    --strict-extra    产出里有、参考里没有的文件 → 判红（默认只警告）
    --show N          每个失败项最多打印几行证据（默认 3）

判定是**三态**的：
    PASS  真的比过且达标
    FAIL  真的比过且不达标，或者**该有的文件不见了**
    N/A   这一项**量不了**（格式不支持、解码失败……）—— 不算通过，也不算失败

    ⛔ N/A 绝不计入通过率的分母。本项目踩过：拿「能读出数」当条件去算分母，
       结果一批「量错了对象」的样本把通过率稀释得很漂亮。
    ⛔ 参考里有、产出里没有 ⇒ 一律 FAIL。少一半文件却报绿的检查器是最糟的检查器。

退出码：0 = 没有 FAIL（允许有 N/A，但 N/A 数会单独报出来）；
        1 = 有 FAIL；2 = 参数错。
报告：默认写 <cwd>/_check-golden.log（超 2 MB 下次启动轮转 .1），与屏幕逐字相同。
"""
import io
import os
import sys
import time
import math
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(os.getcwd(), '_check-golden.log')
_fh = None

IMG_EXT = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')
TXT_EXT = ('.txt', '.csv', '.json', '.log', '.md')

try:
    import numpy as np
    import cv2
except ImportError:                      # 只在真的要读图时才需要
    np = None
    cv2 = None


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


def sha16(b):
    return hashlib.sha256(b).hexdigest()[:16]


# ── 读图：⛔ 绝不用 cv2.imread ──────────────────────────────────────
def load_img(p):
    """返回 (ndarray, None) 或 (None, 原因)。

    ⛔ 不用 cv2.imread：它遇到非 ASCII 路径（中文目录）**返回 None 且不报错**，
       于是「读不到」会被当成「没有差异」。本项目已踩过。
    ⛔ 不用 imwrite 存图同理（连 None 都不返回）。
    """
    if cv2 is None or np is None:
        return None, '没装 numpy/cv2，读不了图（装了才能比）'
    try:
        buf = np.fromfile(p, dtype=np.uint8)
    except Exception as e:
        return None, 'np.fromfile 失败 %s: %s' % (type(e).__name__, e)
    if buf.size == 0:
        return None, '文件为空或读不到'
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None, 'cv2.imdecode 返回 None（不是图片，或解码失败）'
    return img, None


def _vmax(dtype):
    if dtype == np.uint8:
        return 255.0
    if dtype == np.uint16:
        return 65535.0
    return None


def cmp_img(pa, pb, o):
    a, ea = load_img(pa)
    b, eb = load_img(pb)
    if ea:
        return 'N/A', ea, []
    if eb:
        return 'N/A', eb, []
    ev = []
    if a.shape != b.shape:
        return 'FAIL', '形状不同：参考 %s vs 产出 %s' % (a.shape, b.shape), ev
    if a.dtype != b.dtype:
        ev.append('dtype 不同：%s vs %s（先转成同一个再比）' % (a.dtype, b.dtype))
    ai = a.astype(np.int64)
    bi = b.astype(np.int64)
    d = np.abs(ai - bi)
    mx = int(d.max())
    ndiff = int((d > o['pixel_tol']).sum())
    pct = 100.0 * ndiff / float(d.size)
    ev.append('max|Δ| = %d ｜ 差 >%d 的元素 %d / %d = %.6f%%'
              % (mx, o['pixel_tol'], ndiff, d.size, pct))
    bad = []
    # ⚠️ 判据**只有这一条**。别再加「max|Δ| > pixel_tol 就红」——
    #    加了它 pct-tol 就变成死开关：max|Δ| 超了直接红，没超则 ndiff 必为 0，
    #    pct 恒等于 0，两个条件互斥到 pct 永远触发不了。
    #    2026-11-01 本脚本第一版正是这么写的，自检 10 条全绿，而 --pct-tol 从未起过作用。
    if pct > o['pct_tol']:
        bad.append('超容差像素 %.6f%% > 允许的 %.6f%%' % (pct, o['pct_tol']))
    vm = _vmax(a.dtype)
    if o['psnr_min'] is not None:
        if vm is None:
            ev.append('PSNR：dtype %s 不是 8/16 位整型，判不了（不参与判定）' % a.dtype)
        else:
            mse = float((d.astype(np.float64) ** 2).mean())
            psnr = float('inf') if mse == 0 else 10 * math.log10(vm * vm / mse)
            ev.append('PSNR = %s' % ('inf' if psnr == float('inf') else '%.2f dB' % psnr))
            if psnr < o['psnr_min']:
                bad.append('PSNR %.2f < %.2f' % (psnr, o['psnr_min']))
    if bad:
        return 'FAIL', '；'.join(bad), ev
    return 'PASS', 'max|Δ| %d，超容差像素 %.6f%% ≤ %.6f%%' % (mx, pct, o['pct_tol']), ev


import re
NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def lines_equal_numeric(x, y, tol):
    """只让**数字**在容差内变化，其余字符必须逐字相同。

    ⛔ 不能用 `x.split()` 分词 —— `1.000,2.000` 在 split 眼里是**一个** token，
       `float()` 直接抛，于是数字容差一次都没生效过（自检当场抓到的）。
    做法：把所有数字替换成占位符比「骨架」，骨架不同就是不同构；
          骨架相同再逐个数比绝对差。
    """
    if x == y:
        return True
    mx, my = list(NUM.finditer(x)), list(NUM.finditer(y))
    if len(mx) != len(my):
        return False
    if NUM.sub('#', x) != NUM.sub('#', y):
        return False
    return all(abs(float(a.group()) - float(b.group())) <= tol for a, b in zip(mx, my))


def cmp_text(pa, pb, o):
    ta = open(pa, 'rb').read().decode('utf-8', 'replace').splitlines()
    tb = open(pb, 'rb').read().decode('utf-8', 'replace').splitlines()
    if len(ta) != len(tb):
        return 'FAIL', '行数不同：参考 %d vs 产出 %d' % (len(ta), len(tb)), []
    bad = []
    for i, (x, y) in enumerate(zip(ta, tb), 1):
        if x == y:
            continue
        ok = o['text_tol'] > 0 and lines_equal_numeric(x, y, o['text_tol'])
        if not ok:
            bad.append((i, x[:70], y[:70]))
    if bad:
        ev = ['第 %d 行不同' % i for i, _x, _y in bad[:o['show']]]
        for i, x, y in bad[:o['show']]:
            ev.append('  参考 %r' % x)
            ev.append('  产出 %r' % y)
        return 'FAIL', '%d / %d 行不同' % (len(bad), len(ta)), ev
    return 'PASS', '%d 行一致（数字容差 %g）' % (len(ta), o['text_tol']), []


def cmp_bytes(pa, pb, o):
    a, b = open(pa, 'rb').read(), open(pb, 'rb').read()
    if a == b:
        return 'PASS', '逐字节一致（%d B）' % len(a), []
    if len(a) != len(b):
        return 'FAIL', '长度不同：参考 %d vs 产出 %d' % (len(a), len(b)), []
    n = sum(1 for x, y in zip(a, b) if x != y)
    return 'FAIL', '%d / %d 字节不同' % (n, len(a)), []


def one_pair(pa, pb, o, label):
    ext = os.path.splitext(pa)[1].lower()
    if ext in IMG_EXT:
        v, why, ev = cmp_img(pa, pb, o)
    elif ext in TXT_EXT:
        v, why, ev = cmp_text(pa, pb, o)
    else:
        v, why, ev = cmp_bytes(pa, pb, o)
    return v, why, ev, label


def compare_trees(R, O, o):
    """R/O 都是 {相对路径: 绝对路径}。返回 [(判定, 理由, 证据行, 名字)]。

    抽成独立函数是为了让**自检能测到「缺文件判红」这条真逻辑**，
    而不是去测一句硬编码的提示文字 —— 那样测的是文案，不是判据。
    """
    rows = []
    for rel in sorted(R):
        if rel not in O:
            rows.append(('FAIL', '参考里有、产出里没有 ⇒ 判红（不许当跳过）', [], rel))
            continue
        try:
            rows.append(one_pair(R[rel], O[rel], o, rel))
        except Exception as e:
            rows.append(('N/A', '比对时抛异常 %s: %s' % (type(e).__name__, e), [], rel))
    return rows


def collect(root):
    """返回 {相对路径: 绝对路径}。单文件时键就是文件名本身。"""
    if os.path.isfile(root):
        return {os.path.basename(root): root}
    got = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in ('.git', '__pycache__')]
        for f in fns:
            p = os.path.join(dp, f)
            got[os.path.relpath(p, root)] = p
    return got


def run(argv):
    o = {'pixel_tol': 0, 'pct_tol': 0.0, 'psnr_min': None,
         'text_tol': 0.0, 'show': 3, 'strict_extra': False}
    ref = out = None
    it = list(argv)
    i = 0
    while i < len(it):
        a = it[i]
        if a == '--strict-extra':
            o['strict_extra'] = True
        elif a.startswith('--'):
            key = a.split('=', 1)[0]
            if key not in ('--ref', '--out', '--pixel-tol', '--pct-tol',
                           '--psnr-min', '--text-tol', '--show'):
                say('不认识的参数：%s' % a)
                return 2
            if '=' in a:
                val = a.split('=', 1)[1]
            else:
                i += 1
                if i >= len(it):
                    say('%s 需要取值' % key)
                    return 2
                val = it[i]
            if key == '--ref':
                ref = val
            elif key == '--out':
                out = val
            else:
                k = key[2:].replace('-', '_')
                o[k] = float(val) if k in ('pct_tol', 'text_tol', 'psnr_min') else int(val)
        elif a in ('-h', '--help'):
            say(__doc__)
            return 0
        i += 1

    if not ref or not out:
        say(__doc__)
        return 2
    if not os.path.exists(ref):
        say('参考路径不存在：%s' % ref)
        return 2
    if not os.path.exists(out):
        say('产出路径不存在：%s' % out)
        return 2
    if os.path.isdir(ref) != os.path.isdir(out):
        say('参考和产出必须同为目录或同为文件')
        return 2

    say('=' * 92)
    say('# 黄金参考比对   %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('#   主机 %s   python %s   cwd %s'
        % (os.environ.get('COMPUTERNAME', '?'), sys.version.split()[0], os.getcwd()))
    say('#   脚本 %s' % os.path.abspath(__file__))
    say('#   sha16 %s' % sha16(open(__file__, 'rb').read()))
    say('#   参考 %s' % os.path.abspath(ref))
    say('#   产出 %s' % os.path.abspath(out))
    say('#   容差 差>%d 才算不同 ｜ 允许占比 %.6f%% ｜ PSNR %s ｜ 文本数字 %g'
        % (o['pixel_tol'], o['pct_tol'],
           ('≥ %.2f dB' % o['psnr_min']) if o['psnr_min'] is not None else '不判',
           o['text_tol']))
    say('=' * 92)

    R, O = collect(ref), collect(out)
    rows = compare_trees(R, O, o)
    extra = sorted(set(O) - set(R))
    say('')
    say('参考 %d 个文件，产出 %d 个文件，比了 %d 对' % (len(R), len(O), len(R)))
    for v, why, ev, rel in rows:
        say('')
        say('[%s] %s' % (v, rel))
        say('      %s' % why)
        for line in ev:
            say('      %s' % line)

    if extra:
        say('')
        say('[%s] 产出里有、参考里没有的 %d 个文件：'
            % ('FAIL' if o['strict_extra'] else '警告', len(extra)))
        for e in extra[:o['show']]:
            say('      %s' % e)
        if len(extra) > o['show']:
            say('      … 还有 %d 个' % (len(extra) - o['show']))
        if not o['strict_extra']:
            say('      （默认只警告。要判红就加 --strict-extra）')

    npass = sum(1 for r in rows if r[0] == 'PASS')
    nfail = sum(1 for r in rows if r[0] == 'FAIL')
    nna = sum(1 for r in rows if r[0] == 'N/A')
    say('')
    say('=' * 92)
    say('  PASS %d ｜ FAIL %d ｜ N/A %d ｜ 参考共 %d 项' % (npass, nfail, nna, len(R)))
    if nna:
        say('  ⚠ %d 项 N/A（量不了）—— **不计入通过率**，也不等于通过' % nna)
    if npass + nfail:
        say('  在**真的判过**的 %d 项里，通过 %d 项（%.1f%%）'
            % (npass + nfail, npass, 100.0 * npass / (npass + nfail)))
    else:
        say('  ⛔ 一项都没真的判过 ⇒ 不能当通过')

    why_red = []
    if nfail:
        why_red.append('%d 项不通过' % nfail)
    if o['strict_extra'] and extra:
        why_red.append('产出多出 %d 个文件（--strict-extra）' % len(extra))
    if (npass + nfail) == 0:
        why_red.append('没有任何一项被真的判过')
    if why_red:
        say('【红】' + '；'.join(why_red))
        rc = 1
    else:
        say('【绿】没有 FAIL')
        rc = 0
    say('退出码 %d（0 = 无 FAIL；1 = 有 FAIL）' % rc)
    say('')
    say('# 报告：%s' % LOG)
    return rc


# ── 自检：先证明能判红，再证明能判绿 ────────────────────────────────
def selftest():
    say('=' * 92)
    say('# check-golden 自检（证明能判红、也能判绿）   %s'
        % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('#   脚本 sha16 %s' % sha16(open(__file__, 'rb').read()))
    say('=' * 92)

    o = {'pixel_tol': 0, 'pct_tol': 0.0, 'psnr_min': None,
         'text_tol': 0.0, 'show': 3, 'strict_extra': False}
    import tempfile
    import shutil
    d = tempfile.mkdtemp()
    try:
        def wr(name, data):
            p = os.path.join(d, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            mode = 'wb' if isinstance(data, bytes) else 'w'
            if mode == 'wb':
                open(p, 'wb').write(data)
            else:
                io.open(p, 'w', encoding='utf-8', newline='').write(data)
            return p

        cases = []

        # 1 字节流：一致 → PASS
        a = wr('t1a.bin', b'ABCDEF')
        b = wr('t1b.bin', b'ABCDEF')
        cases.append(('字节一致', a, b, o, 'PASS', '逐字节一致'))

        # 2 字节流：差 1 字节 → FAIL
        b = wr('t2b.bin', b'ABXDEF')
        cases.append(('字节差 1 个', a, b, o, 'FAIL', '字节不同'))

        # 3 文本：数字容差内 → PASS
        ta = wr('t3a.csv', 'x,y\n1.000,2.000\n3.000,4.000\n')
        tb = wr('t3b.csv', 'x,y\n1.004,1.997\n3.001,4.002\n')
        o3 = dict(o, text_tol=0.01)
        cases.append(('文本数字在容差内', ta, tb, o3, 'PASS', '行一致'))

        # 4 文本：数字超容差 → FAIL（证明容差不是万能的）
        o4 = dict(o, text_tol=0.001)
        cases.append(('文本数字超容差', ta, tb, o4, 'FAIL', '行不同'))

        # 5 文本：行数不同 → FAIL
        tc = wr('t5b.csv', 'x,y\n1.000,2.000\n')
        cases.append(('文本行数不同', ta, tc, o3, 'FAIL', '行数不同'))

        allpass = True
        for name, pa, pb, oo, want, want_in in cases:
            v, why, _ev, _lb = one_pair(pa, pb, oo, name)
            ok = (v == want) and (want_in in why)
            allpass &= ok
            say('')
            say('  %-22s 期望 %s 且理由含 %r ⇒ 实得 %s  %s   %s'
                % (name, want, want_in, v, why, '合格' if ok else '不合格'))

        # 6~ 图像通路。**故意放在中文目录里** —— 正是 cv2.imread 静默返回 None 的场景；
        #    这里能跑通，才说明 np.fromfile + imdecode 那个绕法真的生效了。
        if cv2 is not None and np is not None:
            zh = os.path.join(d, '中文路径')
            os.makedirs(zh, exist_ok=True)
            img = np.zeros((32, 32, 3), np.uint8)
            img[8:24, 8:24] = 200
            p_ok = os.path.join(zh, 'a.png')
            cv2.imencode('.png', img)[1].tofile(p_ok)      # ⛔ 不 imwrite（非 ASCII 路径静默失败）
            p_same = os.path.join(zh, 'a2.png')
            cv2.imencode('.png', img)[1].tofile(p_same)
            wob = img.copy()
            wob[10, 10] = 201                               # 只动 1 个像素
            p_1px = os.path.join(zh, 'b.png')
            cv2.imencode('.png', wob)[1].tofile(p_1px)
            p_sz = os.path.join(zh, 'c.png')
            cv2.imencode('.png', np.zeros((64, 32, 3), np.uint8))[1].tofile(p_sz)

            p_all = os.path.join(zh, 'd.png')           # 大块不同：占比远超 1%
            cv2.imencode('.png', np.zeros((32, 32, 3), np.uint8))[1].tofile(p_all)

            img_cases = [
                ('图片一致（中文路径）',   p_ok,  p_same, o,                    'PASS', 'max|Δ| 0'),
                ('差 1 像素 · tol=0',      p_ok,  p_1px,  o,                    'FAIL', '超容差像素'),
                ('差 1 像素 · tol=5',      p_ok,  p_1px,  dict(o, pixel_tol=5), 'PASS', 'max|Δ| 1'),
                # ⛔ 反死开关臂：这一对图和上上行完全相同，只把 pct-tol 放开就必须翻绿。
                #    若哪天有人给 cmp_img 重新加回「max|Δ| 超了就红」，这条会当场变红。
                ('差 1 像素 · pct=1%',     p_ok,  p_1px,  dict(o, pct_tol=1.0), 'PASS', '≤ 1.000000%'),
                ('大块不同 · pct=1%',      p_ok,  p_all,  dict(o, pct_tol=1.0), 'FAIL', '超容差像素'),
                ('图片尺寸不同',           p_ok,  p_sz,   o,                    'FAIL', '形状不同'),
            ]
            for name, pa, pb, oo, want, want_in in img_cases:
                v, why, _ev, _lb = one_pair(pa, pb, oo, name)
                ok = (v == want) and (want_in in why)
                allpass &= ok
                say('')
                say('  %-22s 期望 %s 且理由含 %r ⇒ 实得 %s  %s   %s'
                    % (name, want, want_in, v, why, '合格' if ok else '不合格'))
        else:
            say('')
            say('  ⚠ 没装 numpy/cv2 ⇒ **图像通路没测**。这次自检的「通过」不覆盖图像比对。')
            allpass = False

        # 缺文件：**真的调 compare_trees**，不是测一句文案
        rd = os.path.join(d, 'ref6')
        od = os.path.join(d, 'out6')
        wr('ref6/keep.bin', b'AAAA')
        wr('ref6/gone.bin', b'BBBB')
        wr('out6/keep.bin', b'AAAA')
        rows6 = compare_trees(collect(rd), collect(od), o)
        d6 = {r[3]: r for r in rows6}       # ⛔ 不能用下标：sorted() 之后 gone 排在 keep 前面
        ok6 = (len(rows6) == 2
               and d6.get('keep.bin', ('', ''))[0] == 'PASS'
               and d6.get('gone.bin', ('', ''))[0] == 'FAIL'
               and '产出里没有' in d6.get('gone.bin', ('', '', ''))[1])
        allpass &= ok6
        say('')
        say('  %-22s 期望 2 项：keep 判 PASS、gone 判 FAIL' % '参考有、产出没有')
        for v, why, _e, rel in rows6:
            say('      [%s] %-12s %s' % (v, rel, why))
        say('  %-22s %s' % ('', '合格' if ok6 else '不合格'))

        say('')
        if allpass:
            say('【自检通过】能判绿（一致 / 容差内）、能判红（差字节 / 超容差 / 行数不同 / 缺文件）')
            say('            且容差写得再大也盖不住「行数不同」和「文件不见了」')
        else:
            say('【自检失败】这个检查器本身不可信，别拿它的绿当结论')
        return 0 if allpass else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    _open_log()
    try:
        rc = selftest() if sys.argv[1:2] == ['--selftest'] else run(sys.argv[1:])
    finally:
        if _fh is not None:
            _fh.close()
    sys.exit(rc)
