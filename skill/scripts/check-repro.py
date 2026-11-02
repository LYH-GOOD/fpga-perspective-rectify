#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两个构建产物逐字节比对 —— 判据必须写清「哪几个字节允许不同」，否则一律判红。

用法：
    python check-repro.py <a> <b> [--allow LO-HI[,LO-HI...]] [--show N]
    python check-repro.py --selftest                  # 证明本工具能判红、也能判绿

为什么要有 --allow：
    Vivado 出的 .bit 里带构建时间戳，重建两次必然有几个字节不同。
    本项目实测：同一份源重建，只差 **5 个字节**，落在构建日期区。
    如果不把「允许不同的区间」写死，这个检查每次都会红 —— 然后就会被无视。
    ⇒ 先跑一遍看差异落在哪，再把那个区间写进 --allow，此后才有判别力。

判据：
    完全一致                                              ⇒ 绿
    有差异，且每个差异都落在 --allow 声明的区间内           ⇒ 绿
    有差异，但没给 --allow / 有差异落在区间外 / 长度不等    ⇒ 红

退出码：0 = 通过；1 = 不通过。
报告：默认写 <cwd>/_check-repro.log（超 2 MB 下次启动轮转 .1），与屏幕逐字相同。
"""
import io
import os
import sys
import time
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(os.getcwd(), '_check-repro.log')
_fh = None
CHUNK = 1 << 20


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


def sha_of(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def diff_offsets(a, b):
    """逐块比，快的块整块跳过 —— 4 MB 的 .bit 通常只差几个字节。"""
    n = min(len(a), len(b))
    out = []
    for base in range(0, n, CHUNK):
        ca, cb = a[base:base + CHUNK], b[base:base + CHUNK]
        if ca == cb:
            continue
        for i in range(len(ca)):
            if ca[i] != cb[i]:
                out.append(base + i)
    return out


def clusters(offs):
    """把连续的偏移收成 (start, end_inclusive) 区间。"""
    got = []
    for o in offs:
        if got and o == got[-1][1] + 1:
            got[-1][1] = o
        else:
            got.append([o, o])
    return [(s, e) for s, e in got]


def parse_ranges(spec):
    """'0-9,0x100-0x1FF,42' → [(0,9),(256,511),(42,42)]"""
    out = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            lo, hi = part.split('-', 1)
            out.append((int(lo, 0), int(hi, 0)))
        else:
            v = int(part, 0)
            out.append((v, v))
    return out


def judge(da, db, allow):
    """返回 (退出码, 判定理由)。main 和 selftest 共用同一份判据 ——
    自检若另写一套，测的就不是真正在跑的那个判据了。"""
    if len(da) != len(db):
        return 1, '长度不等（A %d、B %d）—— --allow 管不了这个' % (len(da), len(db))
    offs = diff_offsets(da, db)
    if not offs:
        return 0, '逐字节完全一致（0 个差异字节）'
    if not allow:
        return 1, '有 %d 个字节不同，而你没有声明 --allow' % len(offs)
    outside = [o for o in offs if not any(lo <= o <= hi for lo, hi in allow)]
    if outside:
        return 1, '有 %d 个差异字节落在 --allow 之外（首个越界 0x%X）' % (len(outside), outside[0])
    return 0, '%d 个差异字节全部落在 --allow 区间内（区间外 0 个）' % len(offs)


def selftest():
    say('=' * 92)
    say('# check-repro 自检（证明能判红、也能判绿）   %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('#   脚本 sha16 %s' % sha16(open(__file__, 'rb').read()))
    say('=' * 92)

    base = bytes(range(256)) * 8          # 2048 字节
    tweak = bytearray(base)
    tweak[500] ^= 0xFF                    # 只改偏移 500 这一字节
    far = bytearray(base)
    far[500] ^= 0xFF
    far[1500] ^= 0xFF                     # 两个差异，一个在 0-1000 内、一个在 1000 外

    cases = [
        ('完全一致 · 无 allow',          base,  base,      [],               0, '逐字节完全一致'),
        ('差 1 字节 · 无 allow',         base,  bytes(tweak), [],            1, '没有声明'),
        ('差 1 字节 · allow 覆盖它',     base,  bytes(tweak), [(400, 600)],   0, '全部落在'),
        ('差 1 字节 · allow 不覆盖它',   base,  bytes(tweak), [(0, 100)],     1, '之外'),
        ('长度不等 · allow 全覆盖也红',  base,  base[:len(base) - 1], [(0, 9999)], 1, '长度不等'),
        ('两个差异只盖住第一个',          base,  bytes(far),   [(0, 1000)],    1, '之外'),
    ]
    allpass = True
    for name, da, db, allow, want_rc, want_in_reason in cases:
        rc, reason = judge(da, db, allow)
        ok = (rc == want_rc) and (want_in_reason in reason)
        allpass &= ok
        say('')
        say('  %-30s 期望 rc=%d 且理由含 %r' % (name, want_rc, want_in_reason))
        say('  %-30s 实得 rc=%d  %s   %s'
            % ('', rc, reason, '合格' if ok else '不合格'))
    say('')
    if allpass:
        say('【自检通过】能判绿（一致 / 允许区间内）、能判红（未声明 / 越界 / 长度不等），')
        say('            且「--allow 写得再宽也盖不住长度不等」')
    else:
        say('【自检失败】这个检查器本身不可信，别拿它的绿当结论')
    return 0 if allpass else 1


def main(argv):
    a = b = None
    allow, show = [], 10
    it = iter(argv)
    for x in it:
        if x.startswith('--allow='):
            allow = parse_ranges(x.split('=', 1)[1])
        elif x.startswith('--show='):
            show = int(x.split('=', 1)[1])
        elif x in ('-h', '--help'):
            say(__doc__)
            return 0
        elif a is None:
            a = x
        elif b is None:
            b = x
        else:
            say('多给了参数：%r' % (x,))
            return 1
    if not a or not b:
        say(__doc__)
        return 0

    say('=' * 92)
    say('# 构建可复现性比对   %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('#   主机 %s   python %s   cwd %s'
        % (os.environ.get('COMPUTERNAME', '?'), sys.version.split()[0], os.getcwd()))
    say('#   脚本 %s' % os.path.abspath(__file__))
    say('#   sha16 %s' % sha16(open(__file__, 'rb').read()))
    say('#   allow %s' % (['%d-%d' % r for r in allow] if allow else '（未声明 —— 有任何差异都判红）'))
    say('=' * 92)

    for p in (a, b):
        if not os.path.isfile(p):
            say('')
            say('[红] 文件不存在：%s' % p)
            return 1

    da, db = open(a, 'rb').read(), open(b, 'rb').read()
    say('')
    say('A  %s' % os.path.abspath(a))
    say('   %d 字节   sha256 %s' % (len(da), sha_of(a)))
    say('B  %s' % os.path.abspath(b))
    say('   %d 字节   sha256 %s' % (len(db), sha_of(b)))

    if len(da) != len(db):
        say('')
        say('[红] 长度不等：A %d、B %d（差 %+d 字节）—— 长度不同一律判红，--allow 管不了这个'
            % (len(da), len(db), len(db) - len(da)))

    offs = diff_offsets(da, db)
    if len(da) != len(db):
        # 长度差也要记进差异数里，否则「差异 0 处」会误导
        n = min(len(da), len(db))
        offs.extend(range(n, max(len(da), len(db))))

    say('')
    say('差异字节数：%d' % len(offs))

    if not offs:
        say('')
        say('【绿】逐字节完全一致（0 个差异字节）')
        say('')
        say('退出码 0（0 = 通过；1 = 不通过）')
        say('# 报告：%s' % LOG)
        return 0

    cl = clusters(offs)
    say('差异区间数：%d' % len(cl))
    say('')
    say('%-8s %-10s %-10s %-8s %s' % ('#', '起(dec)', '止(dec)', '长度', '起(hex)'))
    for i, (s, e) in enumerate(cl[:show], 1):
        say('%-8d %-10d %-10d %-8d 0x%X'
            % (i, s, e, e - s + 1, s))
    if len(cl) > show:
        say('… 还有 %d 个区间没打（用 --show=N 全看）' % (len(cl) - show))
    say('')
    say('前 %d 个差异字节（原值 → 新值）：' % min(8, len(offs)))
    for o in offs[:8]:
        va = da[o] if o < len(da) else None
        vb = db[o] if o < len(db) else None
        say('   0x%-8X  %s → %s'
            % (o,
               ('0x%02X' % va) if va is not None else '（不存在）',
               ('0x%02X' % vb) if vb is not None else '（不存在）'))

    # ── 判定 ──
    rc, reason = judge(da, db, allow)
    say('')
    say('【%s】%s' % ('绿' if rc == 0 else '红', reason))
    if rc != 0 and not allow and len(da) == len(db):
        say('     若这些字节属于构建日期区（本项目实测同一份源只差 5 个字节就是这种情况），')
        say('     把上面列出的区间写进 --allow 再跑一次；否则这就是构建不可复现。')
    elif rc == 0:
        say('     ⚠️ 这是「允许范围内的一致」，不是「逐字节一致」')

    say('')
    say('退出码 %d（0 = 通过；1 = 不通过）' % rc)
    say('')
    say('# 报告：%s' % LOG)
    return rc


if __name__ == '__main__':
    _open_log()
    try:
        rc = selftest() if sys.argv[1:2] == ['--selftest'] else main(sys.argv[1:])
    finally:
        if _fh is not None:
            _fh.close()
    sys.exit(rc)
