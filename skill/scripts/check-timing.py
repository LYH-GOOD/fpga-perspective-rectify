#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 Vivado 报告的资源与时序 —— 先证明它能判红，再相信它的绿。

用法：
    python check-timing.py <报告文件或目录> [...]
    python check-timing.py --selftest                 # 证明本工具能判红、也能判绿

    # 采集模式：让 Vivado 自己把报告生成出来，再**交给同一套判据**
    python check-timing.py --collect --dcp <design.dcp> [--out 目录]
    python check-timing.py --collect --xpr <proj.xpr> [--run impl_1]
    python check-timing.py --collect ... --dry-run    # 只打印要跑的 Tcl，不动 Vivado

    --collect 额外选项：
      --vivado PATH     vivado 可执行文件（默认依次找 $VIVADO、PATH、
                        C:/Xilinx/Vivado/*/bin、F:/vivado/*/Vivado/bin，取版本号最大的）
      --timeout SEC     单次 Vivado 的超时（默认 1800）
      --out DIR         报告放哪（默认 <cwd>/_vivado_reports）
      --threads N       传给 set_param general.maxThreads（**默认 1**）。
                        2026-11-01 实测：默认多线程时序更新在本机会让 Vivado 直接崩
                        （0xC0000374 堆损坏，死点固定在 "Multithreading enabled for timing update"
                        之后）；同一条 Tcl 只加 set_param general.maxThreads 1 就正常出报告。
    ⛔ 采集模式**不是**「Vivado 退出码 0 就算过」—— 退出码 0 只说明它跑完了，
       出来的报告照样要过下面那套判据；报告缺了 / 空的 / 解析不了，一律判红。

    ⚠️ 已实测的范围（2026-11-01）：`--dcp` 对真 routed DCP 端到端跑通 35.7 s。
       **`--xpr` 只验到 Tcl 生成，没有对真工程跑过** —— 第一次用请留意 run 名对不对。

能认的两种报告（按**内容**自动识别，不看文件名）：
    [时序] report_timing_summary 的 Design Timing Summary 段
           —— 认「同一行里同时有 WNS(ns) 和 WHS(ns)」；
              行内会出现的 Intra Clock Table 只有 WNS 没有 WHS，自动排除
    [资源] report_utilization 的表格
           —— 认「| 名称 | Used | Fixed | Prohibited | Available | Util% |」六列

判据：
    WNS < --min-wns（默认 0）或 WHS < --min-whs（默认 0）              ⇒ 红
    Slice LUTs / Slice Registers / Block RAM Tile / DSPs / Bonded IOB
        的 Util% > --max-util（默认 90）                               ⇒ 红
    报告被截断 / 按列宽切完拼不回原行 / 一个可判定的报告都没找到        ⇒ 红
        ⛔ 「解析不到」绝不当通过 —— 那正是空转门的形成方式

退出码：0 = 全部通过；1 = 有红（含解析失败）。
报告：默认写 <cwd>/_check-timing.log（超 2 MB 下次启动轮转 .1），与屏幕逐字相同。

不支持：HLS 的 *_csynth.rpt（列名与列宽都不同，顶层报告名是 <top>_csynth.rpt）。
        遇到会明确判红并说明，不静默跳过。
"""
import io
import os
import re
import sys
import time
import glob
import hashlib
import tempfile
import shutil
import subprocess
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(os.getcwd(), '_check-timing.log')
_fh = None

RES = ('Slice LUTs', 'Slice Registers', 'Block RAM Tile', 'DSPs', 'Bonded IOB')
DASH = re.compile(r'-{3,}')


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


def read_text(p):
    return open(p, 'rb').read().decode('utf-8', 'replace')


class ParseError(Exception):
    pass


# ── 时序：按短横线行的列宽切片 ──────────────────────────────────────
def parse_timing(text):
    """返回 ({列名: 浮点值}, 表头行号, 数值行号)。切不准就 raise ParseError。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        # 同一行同时有 WNS(ns) 和 WHS(ns) 才是总表；Intra Clock Table 只有 WNS
        if 'WNS(ns)' in ln and 'WHS(ns)' in ln:
            k = i + 1
            cols = None
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines):
                s = lines[k].strip()
                if s and set(s) <= set('- '):
                    cols = [(m.start(), m.end()) for m in DASH.finditer(lines[k])]
                    k += 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            if cols is None:
                raise ParseError('第 %d 行是总表表头，但下面没有短横线分隔行，列宽无法确定'
                                 ' —— 不敢猜' % (i + 1))
            if k >= len(lines):
                raise ParseError('第 %d 行是总表表头，但后面没有数值行（报告被截断？）' % (i + 1))
            vline = lines[k]
            names = [ln[s:e].strip() for s, e in cols]
            vals = [vline[s:e].strip() for s, e in cols]
            if ''.join(vals) != vline.replace(' ', ''):
                raise ParseError('按列宽切完拼不回原行（第 %d 行）—— 有数值超出了自己的列宽，'
                                 '切出来的可能是错的，不敢用' % (k + 1))
            out = {}
            for n, v in zip(names, vals):
                try:
                    out[n] = float(v)
                except ValueError:
                    raise ParseError('第 %d 行 列 %r 的值 %r 不是数字' % (k + 1, n, v))
            return out, i + 1, k + 1
    raise ParseError('没找到同时含 WNS(ns) 和 WHS(ns) 的那一行')


def parse_util(text):
    """返回 {资源名: (Used, Available, Util%)}。认不出就返回空 dict。"""
    got = {}
    for ln in text.splitlines():
        if not ln.startswith('|'):
            continue
        f = [x.strip() for x in ln.split('|')]
        if len(f) < 7 or f[1] not in RES:
            continue
        try:
            got.setdefault(f[1], (float(f[2]), float(f[5]), float(f[6])))
        except ValueError:
            continue
    return got


# ── 检查一个文件 ────────────────────────────────────────────────────
def check_file(p, min_wns, min_whs, max_util, strict=True):
    """strict=True：点名的文件，判不了必须红。
    strict=False：扫目录扫到的，判不了就安静跳过 —— 目录里本来就有一堆
                  route_status / clock_utilization，把它们全判红等于让检查器变成噪音。"""
    text = read_text(p)
    found = []

    # 时序
    try:
        tv, hl, vl = parse_timing(text)
    except ParseError as e:
        if 'WNS(ns)' in text:
            found.append(('红', p, 0, '有时序表但解析失败：%s' % e))
        tv = None
    else:
        for key, lim, what in (('WNS(ns)', min_wns, 'WNS'), ('WHS(ns)', min_whs, 'WHS')):
            if key not in tv:
                found.append(('红', p, vl, '总表里没有 %s 这一列 —— 判不了，不当通过' % key))
                continue
            v = tv[key]
            ok = v >= lim
            found.append(('绿' if ok else '红', p, vl,
                          '%s = %+.3f ns（判据 ≥ %+.3f）%s' % (what, v, lim,
                                                              '' if ok else ' ⇒ 时序不满足')))
        found.append(('·', p, hl, '时序表取自第 %d~%d 行' % (hl, vl)))

    # 资源
    uv = parse_util(text)
    if uv:
        for name in RES:
            if name not in uv:
                continue
            used, avail, pct = uv[name]
            ok = pct <= max_util
            found.append(('绿' if ok else '红', p, 0,
                          '%-18s %7.1f / %-7.1f = %5.2f%%（判据 ≤ %.1f%%）%s'
                          % (name, used, avail, pct, max_util,
                             '' if ok else ' ⇒ 资源告急')))
    elif 'Slice LUTs' in text:
        found.append(('红', p, 0, '有资源表但一列都没认出来 —— 判不了，不当通过'))

    if not found:
        is_hls = 'csynth' in text[:2000].lower() or '_csynth' in os.path.basename(p).lower()
        if is_hls:
            found.append(('红', p, 0, 'HLS 报告（csynth）本工具不支持 —— 列名与列宽都不同，'
                                      '请用 Vivado 的 report_utilization / report_timing_summary'))
        elif strict:
            found.append(('红', p, 0, '既没有时序总表也没有资源表 —— 不是一个能判定的报告'))
    return found


def walk(targets):
    for t in targets:
        if os.path.isfile(t):
            yield t, True
        else:
            for root, dirs, files in os.walk(t):
                dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', '.venv')]
                for f in files:
                    if f.lower().endswith(('.rpt', '.log', '.txt')):
                        yield os.path.join(root, f), False


def banner(title, extra=()):
    say('=' * 92)
    say('# %s   %s' % (title, time.strftime('%Y-%m-%d %H:%M:%S')))
    say('#   主机 %s   python %s   cwd %s'
        % (os.environ.get('COMPUTERNAME', '?'), sys.version.split()[0], os.getcwd()))
    say('#   脚本 %s' % os.path.abspath(__file__))
    say('#   sha16 %s' % sha16(open(__file__, 'rb').read()))
    for e in extra:
        say('#   %s' % e)
    say('=' * 92)


# ── --collect：让 Vivado 自己出报告，再交给上面那套判据 ────────────────────
# 为什么要有这一段：竞赛点名的第四类工具是「性能与资源数据**自动采集**并生成报告」。
# 只判报告 = 判别人交来的东西；能自己驱动 Vivado 采一遍 = 整条链闭合。
# ⛔ 但采集**本身不算判据** —— Vivado 退出码 0 只说明它跑完了，报告还得过判据。
def find_vivado(explicit=None):
    """找 vivado 可执行文件。找不到就返回 None，由调用方判红并给出该填什么。"""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    env = os.environ.get('VIVADO')
    if env and os.path.exists(env):
        return env
    for name in ('vivado', 'vivado.bat'):
        p = shutil.which(name)
        if p:
            return p
    pats = ('C:/Xilinx/Vivado/*/bin/vivado.bat',
            'D:/Xilinx/Vivado/*/bin/vivado.bat',
            'E:/Xilinx/Vivado/*/bin/vivado.bat',
            'F:/Xilinx/Vivado/*/bin/vivado.bat',
            'C:/Program Files/Xilinx/Vivado/*/bin/vivado.bat',
            'C:/AMD/Vivado/*/bin/vivado.bat',
            'F:/vivado/*/Vivado/bin/vivado.bat')
    hits = []
    for pat in pats:
        hits.extend(glob.glob(pat))
    if not hits:
        return None

    def ver(p):
        m = re.search(r'/(\d{4}\.\d)/', p.replace('\\', '/'))
        return m.group(1) if m else '0000.0'

    hits.sort(key=ver)                 # 取版本号最大的那个 —— 别默认挑到旧版
    return hits[-1]


def build_tcl(o):
    """生成驱动 Vivado 的 Tcl。**路径一律正斜杠**，用 {} 包住以防空格。"""
    f = lambda p: p.replace('\\', '/')          # noqa: E731
    L = ['# 由 check-timing.py --collect 自动生成，勿手改']
    if o['dcp']:
        L.append('open_checkpoint {%s}' % f(o['dcp']))
    else:
        L.append('open_project {%s}' % f(o['xpr']))
        L.append('open_run {%s}' % o['run'])
    # ⛔ 这一行是 2026-11-01 实测加上去的，不是保守起见：
    #    默认多线程时序更新在**本机**会让 Vivado 直接崩（0xC0000374 heap corruption），
    #    死点固定在 "Multithreading enabled for timing update using a maximum of 2 CPUs"
    #    之后。同一条 Tcl 只加这一行就正常出 95 KB 报告。--threads 可以改回去。
    L.append('set_param general.maxThreads %d' % int(o.get('threads', 1)))
    L.append('report_timing_summary -file {%s} -warn_on_violation' % f(o['timing_rpt']))
    L.append('report_utilization -file {%s}' % f(o['util_rpt']))
    L.append('puts "COLLECT_DONE"')
    L.append('exit 0')
    return '\n'.join(L) + '\n'


def _dec(b):
    """Vivado 在 Windows 上的输出是本地代码页；本项目 stdout 又是 GBK。
    两种都试，别让解码把真正的报错吃掉。"""
    for enc in ('utf-8', 'gbk', 'latin-1'):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, AttributeError):
            continue
    return repr(b)


def do_collect(o):
    """跑一遍 Vivado 采报告。返回 (verdict, produced_paths, note)。

    verdict ∈ {PASS, FAIL, SKIP}；SKIP 只在 --dry-run 时出现。
    ⛔ 失败时把 Vivado 的输出**全文**写进报告，不截断 —— 截掉的那几行正是要看的。
    """
    viv = find_vivado(o['vivado'])
    if not viv:
        say('[红] 找不到 vivado 可执行文件。')
        say('     --vivado 没给、$VIVADO 没设、PATH 里没有、常见安装目录也没扫到。')
        say('     请显式指定，例如：--vivado "F:/vivado/2026.1/Vivado/bin/vivado.bat"')
        return 'FAIL', [], '找不到 vivado'
    if o['dcp'] and not os.path.exists(o['dcp']):
        say('[红] --dcp 不存在：%s' % o['dcp'])
        return 'FAIL', [], '--dcp 不存在'
    if o['xpr'] and not os.path.exists(o['xpr']):
        say('[红] --xpr 不存在：%s' % o['xpr'])
        return 'FAIL', [], '--xpr 不存在'

    out = os.path.abspath(o['out'])
    o['timing_rpt'] = os.path.join(out, 'timing_summary.rpt')
    o['util_rpt'] = os.path.join(out, 'utilization.rpt')
    # 采之前先删旧的：否则「上次的报告还在」会让采集失败也显示成绿的
    for p in (o['timing_rpt'], o['util_rpt']):
        if os.path.exists(p):
            os.remove(p)

    tcl = build_tcl(o)
    say('  vivado : %s' % viv)
    say('  输入   : %s' % (o['dcp'] or ('%s / run %s' % (o['xpr'], o['run']))))
    say('  输出   : %s' % out)
    say('  Tcl    :')
    for line in tcl.rstrip('\n').split('\n'):
        say('      %s' % line)

    if o['dry_run']:
        say('  --dry-run：只打印，没有真的调用 Vivado')
        return 'SKIP', [], 'dry-run 没有调用 Vivado'

    os.makedirs(out, exist_ok=True)
    tmpd = tempfile.mkdtemp(prefix='_ctcollect_')
    tclp = os.path.join(tmpd, 'collect.tcl')
    logp = os.path.join(tmpd, 'vivado.log')
    with io.open(tclp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(tcl)

    cmd = [viv, '-mode', 'batch', '-notrace', '-nojournal', '-log', logp, '-source', tclp]
    say('  命令   : %s' % ' '.join('"%s"' % c if ' ' in c else c for c in cmd))
    t0 = time.time()
    try:
        pr = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=o['timeout'])
        outb, rc = pr.stdout or b'', pr.returncode
    except subprocess.TimeoutExpired as e:
        outb, rc = (e.output or b''), 'TIMEOUT'
    except Exception:
        say('[红] 调用 Vivado 失败，全文如下（未截断）：')
        say(traceback.format_exc())
        shutil.rmtree(tmpd, ignore_errors=True)
        return 'FAIL', [], '调用 Vivado 抛异常'
    dt = time.time() - t0
    txt = _dec(outb)

    say('  Vivado 退出码 %s，用时 %.1f s' % (rc, dt))
    ok_run = (rc == 0)
    if not ok_run:
        # 失败路径：全文进报告，一个字符都不截
        say('  ── Vivado 输出全文（失败路径不截断）──────────────')
        for line in txt.splitlines():
            say('  | %s' % line)
        say('  ── 全文结束 ──────────────────────────────────')

    missing = [p for p in (o['timing_rpt'], o['util_rpt'])
               if not os.path.exists(p) or os.path.getsize(p) == 0]
    say('  timing_summary.rpt：%s'
        % ('缺失或 0 字节' if o['timing_rpt'] in missing
           else '%d 字节' % os.path.getsize(o['timing_rpt'])))
    say('  utilization.rpt   ：%s'
        % ('缺失或 0 字节' if o['util_rpt'] in missing
           else '%d 字节' % os.path.getsize(o['util_rpt'])))
    say('  Vivado 日志（全文留档）：%s' % logp)

    if not ok_run:
        say('[红] Vivado 没正常结束（退出码 %s）⇒ 采集失败，不进入判据' % rc)
        return 'FAIL', [], 'Vivado 没正常结束'
    if missing:
        say('[红] 采集跑完了，但报告没出来：%s' % ', '.join(os.path.basename(m) for m in missing))
        say('     常见原因：DCP 是 OOC 的子模块（没有完整实现）、run 名写错、')
        say('     或 report_timing_summary 需要先 open_run 一个已实现的设计。')
        return 'FAIL', [], '报告没出来'
    say('[采到] 两份报告都在，交给下面的判据')
    return 'PASS', [o['timing_rpt'], o['util_rpt']], '采到两份报告'


def run(argv):
    min_wns, min_whs, max_util, targets = 0.0, 0.0, 90.0, []
    o = {'dcp': None, 'xpr': None, 'run': 'impl_1', 'vivado': None,
         'timeout': 1800.0, 'out': None, 'dry_run': False, 'threads': 1,
         'timing_rpt': None, 'util_rpt': None}
    collect = False
    # 带值的选项**两种写法都认**：`--dcp=X` 与 `--dcp X`。
    # 用法说明里写的是空格形式，只认 `=` 的话照说明抄会静默掉进 targets —— 当场踩过一次。
    VALUED = ('--min-wns', '--min-whs', '--max-util',
              '--dcp', '--xpr', '--run', '--vivado', '--timeout', '--out', '--threads')
    short = dict(zip(VALUED, ('min_wns', 'min_whs', 'max_util',
                              'dcp', 'xpr', 'run', 'vivado', 'timeout', 'out', 'threads')))
    it = iter(argv)
    for a in it:
        k, eq, v = a.partition('=')
        if k in VALUED:
            if not eq:
                v = next(it, None)
                if v is None:
                    say('[红] %s 后面缺一个值' % k)
                    return 1
            if k == '--min-wns':
                min_wns = float(v)
            elif k == '--min-whs':
                min_whs = float(v)
            elif k == '--max-util':
                max_util = float(v)
            elif k == '--timeout':
                o['timeout'] = float(v)
            elif k == '--threads':
                o['threads'] = int(v)
            else:
                o[short[k]] = v
        elif a == '--collect':
            collect = True
        elif a == '--dry-run':
            o['dry_run'] = True
        elif a in ('-h', '--help'):
            say(__doc__)
            return 0
        else:
            targets.append(a)

    # --collect 与手给报告是两条入口，但**判据是同一套**（见下方 targets 汇合处）
    if collect and targets:
        say('[红] --collect 与直接给报告文件不能混用：采完的报告会自己进判据。')
        return 1
    if not collect and not targets:
        say(__doc__)
        return 0

    banner('Vivado 资源与时序检查',
           ['判据：WNS ≥ %+.3f ns，WHS ≥ %+.3f ns，资源 Util%% ≤ %.1f%%'
            % (min_wns, min_whs, max_util)])

    if collect:
        if bool(o['dcp']) == bool(o['xpr']):
            say('[红] --collect 需要且只需要 --dcp 或 --xpr 其中之一。')
            say('     --dcp  已布线设计：open_checkpoint，最快，适合出 bit 前的终检')
            say('     --xpr  工程：open_project + open_run，适合 run 还没导出 DCP 时')
            return 1
        if not o['out']:
            o['out'] = os.path.join(os.getcwd(), '_vivado_reports')
        say('')
        say('── 采集模式 ─────────────────────────────────────')
        verdict, _produced, _tcl = do_collect(o)
        if verdict == 'SKIP':
            say('退出码 0（--dry-run 没做任何判定 —— 这不是「通过」）')
            say('')
            say('# 报告：%s' % LOG)
            return 0
        if verdict != 'PASS':
            say('')
            say('【红】采集失败 ⇒ 一条判据都没跑出来')
            say('退出码 1（0 = 通过；1 = 不通过，别往下跑）')
            say('')
            say('# 报告：%s' % LOG)
            return 1
        targets = [o['timing_rpt'], o['util_rpt']]
        say('────────────────────────────────────────────────')
        say('')

    nf = nred = nok = nskip = 0
    rows = []
    for p, strict in walk(targets):
        nf += 1
        try:
            got = check_file(p, min_wns, min_whs, max_util, strict)
        except Exception as e:
            got = [('红', p, 0, '检查器自己抛了 %s: %s' % (type(e).__name__, e))]
        if not got:
            nskip += 1
            continue
        rows.extend(got)

    say('')
    say('扫了 %d 个文件：认得 %d 个，%d 个不是时序/资源报告（安静跳过）'
        % (nf, nf - nskip, nskip))
    for sev, p, ln, msg in rows:
        if sev == '红':
            nred += 1
        elif sev == '绿':
            nok += 1
        if sev == '·':
            continue
        say('')
        say('[%s] %s%s' % (sev, p, (':%d' % ln) if ln else ''))
        say('      %s' % msg)

    say('')
    if nok == 0:
        say('【红】一条可判定的判据都没有跑出来 ⇒ 不能当通过')
        rc = 1
    elif nred:
        say('【红】通过 %d 条，不通过 %d 条' % (nok, nred))
        rc = 1
    else:
        say('【绿】通过 %d 条，不通过 0 条' % nok)
        rc = 0
    say('退出码 %d（0 = 通过；1 = 不通过，别往下跑）' % rc)
    say('')
    say('# 报告：%s' % LOG)
    return rc


# ── 自检：先证明能判红，再证明能判绿 ────────────────────────────────
# 下面三行是从真实 report_timing_summary 里逐字复制的一行，
# 列宽必须与真报告一致，否则这个自检本身就在骗人。
TIM_HDR = ('    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints      '
           'WHS(ns)      THS(ns)  THS Failing Endpoints  THS Total Endpoints     '
           'WPWS(ns)     TPWS(ns)  WPWS Failing Endpoints  TPWS Total Endpoints  ')
TIM_DASH = ('    -------      -------  ---------------------  -------------------      '
            '-------      -------  ---------------------  -------------------     '
            '--------     --------  ----------------------  --------------------  ')
TIM_GOOD = ('      0.488        0.000                      0                79515        '
            '0.018        0.000                      0                79053        '
            '0.333        0.000                       0                 28701  ')
# 同一个模板，只把 WNS 由 +0.488 改成 -1.234。
# 必须**右对齐填进 7 格宽的那一列**：'  0.488'(2 空格+5 字符) → ' -1.234'(1 空格+6 字符)。
# 若图省事写成 TIM_GOOD.replace('0.488','-1.234')，会把 -1.234 右移一格、挤进列间的空隙，
# 解析器会（正确地）报「拼不回原行」—— 那样测到的就不是「负 WNS 判红」了。
TIM_BAD = TIM_GOOD.replace('  0.488', ' -1.234')

UTIL_GOOD = '\n'.join((
    '| Site Type              | Used | Fixed | Prohibited | Available | Util% |',
    '|------------------------|------|-------|------------|-----------|-------|',
    '| Slice LUTs             | 18839 |     0 |          0 |     53200 | 35.41 |',
    '| Slice Registers        | 26217 |     0 |          0 |    106400 | 24.64 |',
    '| Block RAM Tile         | 112.5 |     0 |          0 |       140 | 80.36 |',
    '| DSPs                   |    59 |     0 |          0 |       220 | 26.82 |',
))
UTIL_BAD = UTIL_GOOD.replace('80.36', '96.00')   # 等宽替换


def _case(name, body, want_red, tmp, expect=None):
    """want_red=True 时，expect 是判红理由**必须命中的关键词**。

    只判「有红」是不够的 —— 曾经就是这样：负 WNS 那个用例其实是因别的原因判红，
    看着全绿，实际根本没测到「负 WNS 会被抓」。
    """
    fp = os.path.join(tmp, name)
    io.open(fp, 'w', encoding='utf-8', newline='').write(body)
    try:
        got = check_file(fp, 0.0, 0.0, 90.0)
    except Exception as e:
        got = [('红', fp, 0, '抛异常 %s: %s' % (type(e).__name__, e))]
    reds = sum(1 for g in got if g[0] == '红')
    oks = sum(1 for g in got if g[0] == '绿')
    if want_red:
        ok = reds > 0
        if ok and expect:
            hit = any(expect in msg for sev, _p, _l, msg in got if sev == '红')
            ok = hit
    else:
        ok = (reds == 0 and oks > 0)
    say('')
    say('  %-22s 期望 %s ⇒ 实得 红%d 绿%d   %s'
        % (name,
           ('有红且理由含 %r' % expect) if expect else ('有绿且无红' if not want_red else '有红'),
           reds, oks, '合格' if ok else '不合格'))
    for sev, _p, _l, msg in got:
        say('      [%s] %s' % (sev, msg))
    return ok


def _collect_arms(d):
    """--collect 的臂。⛔ 一条都不启动真的 Vivado —— 用假的 subprocess.run 驱动逻辑本身，
    为的是把「找不到 Vivado / 报告没出来 / 报告出来但有负 WNS」这三条路都**真的走一遍**，
    而不是只检查生成的字符串长得像不像。"""
    ok = True

    def chk(name, cond, detail=''):
        nonlocal ok
        say('')
        say('  %-22s %s%s' % (name, '合格' if cond else '不合格',
                             '' if cond else ('   ← ' + detail)))
        ok = ok and bool(cond)

    # ① Tcl 生成：--dcp 与 --xpr 走不同入口；路径一律正斜杠（Windows 反斜杠进了 Tcl 容易出事）
    t1 = build_tcl({'dcp': r'D:\a b\design.dcp', 'xpr': None, 'run': 'impl_1',
                    'timing_rpt': r'D:\out\t.rpt', 'util_rpt': r'D:\out\u.rpt'})
    chk('Tcl/--dcp', 'open_checkpoint {D:/a b/design.dcp}' in t1
        and 'open_project' not in t1 and '\\' not in t1, t1)
    t2 = build_tcl({'dcp': None, 'xpr': r'E:\p\proj.xpr', 'run': 'impl_2',
                    'timing_rpt': r'E:\o\t.rpt', 'util_rpt': r'E:\o\u.rpt'})
    chk('Tcl/--xpr', 'open_project {E:/p/proj.xpr}' in t2 and 'open_run {impl_2}' in t2, t2)
    # ② 默认必须带限线程那一行（它挡的是本机真实存在的崩溃），且 --threads 能改掉它
    chk('Tcl/默认限单线程', 'set_param general.maxThreads 1' in t1, t1)
    t3 = build_tcl({'dcp': 'D:/a/b.dcp', 'xpr': None, 'run': 'impl_1', 'threads': 4,
                    'timing_rpt': 'D:/o/t.rpt', 'util_rpt': 'D:/o/u.rpt'})
    chk('Tcl/--threads 可改', 'set_param general.maxThreads 4' in t3, t3)

    def base(**kw):
        o = {'dcp': os.path.join(d, 'f.dcp'), 'xpr': None, 'run': 'impl_1',
             'vivado': sys.executable, 'timeout': 30,
             'out': os.path.join(d, 'o_' + kw.pop('tag', 'x')),
             'dry_run': False, 'timing_rpt': None, 'util_rpt': None}
        o.update(kw)
        return o

    open(os.path.join(d, 'f.dcp'), 'wb').close()          # 假 DCP：只要存在就行

    # ② 找不到 Vivado ⇒ 必须红，且**理由必须是「找不到 vivado」**（不是别的原因碰巧红）
    _v, _p, n = do_collect(base(tag='nomed', vivado=os.path.join(d, 'no_such_vivado.bat')))
    chk('无Vivado→红', _v == 'FAIL' and n == '找不到 vivado', '实际 %r / %r' % (_v, n))

    # ③ --dry-run ⇒ 不调用 Vivado，也不冒充「通过」
    _v, _p, n = do_collect(base(tag='dry', dry_run=True))
    chk('dry-run→SKIP', _v == 'SKIP', '实际 %r / %r' % (_v, n))

    # ④ 采集跑完（rc=0）但报告没落盘 ⇒ 必须红。这正是「退出码 0 就算过」那个坑。
    _real = subprocess.run

    class _R:
        returncode = 0
        stdout = b'fake vivado, no reports written\n'

    subprocess.run = lambda *a, **k: _R()
    try:
        _v, _p, n = do_collect(base(tag='empty'))
        chk('报告没出来→红', _v == 'FAIL' and n == '报告没出来', '实际 %r / %r' % (_v, n))

        # ⑤ 采集真的产出了报告 ⇒ 采集这关过，但**判定还得看报告内容**
        o5 = base(tag='good')

        def _fake_good(*a, **k):
            io.open(o5['timing_rpt'], 'w', encoding='utf-8', newline='')\
                .write(TIM_HDR + '\n' + TIM_DASH + '\n' + TIM_GOOD + '\n')
            io.open(o5['util_rpt'], 'w', encoding='utf-8', newline='')\
                .write(UTIL_GOOD + '\n')
            return _R()

        subprocess.run = _fake_good
        _v, ps, _n = do_collect(o5)
        got = check_file(ps[0], 0.0, 0.0, 90.0) + check_file(ps[1], 0.0, 0.0, 90.0)
        chk('采集绿→判据绿',
            _v == 'PASS' and any(g[0] == '绿' for g in got)
            and not any(g[0] == '红' for g in got),
            '实际 %r / %r' % (_v, got))

        # ⑥ 同一套假采集，只把时序报告换成负 WNS ⇒ 判据必须翻红
        #    这条证明「采集通过 ≠ 判定通过」，否则 ④⑤ 测到的就只是文件在不在
        o6 = base(tag='bad')

        def _fake_bad(*a, **k):
            io.open(o6['timing_rpt'], 'w', encoding='utf-8', newline='')\
                .write(TIM_HDR + '\n' + TIM_DASH + '\n' + TIM_BAD + '\n')
            io.open(o6['util_rpt'], 'w', encoding='utf-8', newline='')\
                .write(UTIL_GOOD + '\n')
            return _R()

        subprocess.run = _fake_bad
        _v, ps, _n = do_collect(o6)
        got = check_file(ps[0], 0.0, 0.0, 90.0)
        chk('采集出的负WNS→红', _v == 'PASS' and any(g[0] == '红' for g in got),
            '实际 %r / %r' % (_v, got))
    finally:
        subprocess.run = _real
    return ok


def selftest():
    banner('check-timing 自检（证明能判红、也能判绿）')
    d = tempfile.mkdtemp()
    try:
        cases = [
            # 文件, 内容, 期望有红, 判红理由必须命中的关键词
            ('tim_good.rpt',      TIM_HDR + '\n' + TIM_DASH + '\n' + TIM_GOOD + '\n', False, None),
            ('tim_bad_wns.rpt',   TIM_HDR + '\n' + TIM_DASH + '\n' + TIM_BAD + '\n',  True,  'WNS = -1.234'),
            ('tim_truncated.rpt', TIM_HDR + '\n',                                     True,  '没有短横线'),
            ('util_good.rpt',     UTIL_GOOD + '\n',                                   False, None),
            ('util_bad_bram.rpt', UTIL_BAD + '\n',                                    True,  '96.00'),
            ('garbage.rpt',       'hello world\nthis is not a report\n',              True,  '不是一个能判定的报告'),
        ]
        allpass = True
        for name, body, want_red, expect in cases:
            allpass &= _case(name, body, want_red, d, expect)
        say('')
        say('── --collect 的臂（假 subprocess.run，不启动真的 Vivado）──────')
        allpass &= _collect_arms(d)
        say('')
        if allpass:
            say('【自检通过】能判红（负 WNS / 超阈值资源 / 截断 / 非报告 全都报红）')
            say('            也能判绿（正 WNS + 资源充足 报绿），且「解析不到」不会冒充通过')
            say('            --collect：找不到 Vivado 判红、报告没落盘判红、采集出的负 WNS 判红')
        else:
            say('【自检失败】这个检查器本身不可信，别拿它的绿当结论')
        return 0 if allpass else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    _open_log()
    try:
        a = sys.argv[1:]
        rc = selftest() if a[:1] == ['--selftest'] else run(a)
    finally:
        if _fh is not None:
            _fh.close()
    sys.exit(rc)
