#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 .hwh 生成主机侧调用骨架 —— 基地址表 + 寄存器表 + 只会跑对的读写封装。

用法：
    python gen-host-skeleton.py <design.hwh> [--out 目录] [--ip 名字]
    python gen-host-skeleton.py --selftest

为什么要有它
------------
`.hwh` 里**已经写着**每个 IP 的基地址、每个寄存器的字节偏移和访问权限。
手抄这三样，本项目已经错过至少三次：

  · 把 write-only 的地址寄存器当可读 —— 读回一个「看着像地址」的垃圾
  · 把「4 字节步长」当通则 —— 同一个工程里实测到 8 字节步长的 HLS 核
  · 把 `<FIELD>` 的位号当字节偏移 —— 扁平正则扒出来的表自相矛盾却没报错

让脚本读、让脚本写，人只负责核对。**生成的骨架里把这三条都编进去了**：
write-only 的寄存器只能在 `w()` 里写、`r()` 会直接拒绝；偏移从文件里取不推算；
64 位地址自动拆成低/高两个 32 位。

它判什么（三态）
----------------
    PASS  解析成功，结构检查全过，骨架写到磁盘
    FAIL  下列任一：不是合法 XML / 同一地址块内寄存器偏移重复 /
          寄存器超出地址块 RANGE / IP 有寄存器表但找不到 MEMRANGE 基地址 / 写盘失败
    N/A   **这份 .hwh 里没有任何带寄存器表的 IP** —— 没东西可生成，
          明确记成「没做」，不算通过

    ⛔ N/A 不计入通过率。本项目踩过「量不了的项算进分母」把通过率稀释得漂亮。

⛔ 判红时**不写盘** —— 一份偏移重复的骨架比没有骨架更危险。
⛔ 退出码：0 = 没有 FAIL；1 = 有 FAIL；2 = 参数错。
⛔ 报告：默认写 <cwd>/_gen-host-skeleton.log（超 2 MB 下次启动轮转 .1），与屏幕逐字相同。
"""
import io
import os
import sys
import time
import hashlib
import argparse
import traceback
import xml.etree.ElementTree as ET

LOG = os.path.join(os.getcwd(), '_gen-host-skeleton.log')
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
    """屏幕与报告**逐字相同**：同一份字符串，先落盘 flush，再写屏幕。"""
    t = (s if isinstance(s, str) else str(s)) + '\n'
    if _fh is not None:
        _fh.write(t)
        _fh.flush()
    sys.stdout.buffer.write(t.encode('utf-8', 'replace'))
    sys.stdout.buffer.flush()


def sha16(b):
    return hashlib.sha256(b).hexdigest()[:16]


def sha16_file(p):
    try:
        with io.open(p, 'rb') as f:
            return sha16(f.read())
    except OSError as e:
        return '读不到(%s)' % e


# ── 解析 ────────────────────────────────────────────────────────────────
def _prop_map(reg):
    """只取 REGISTER 的**直接子** PROPERTY。

    ⛔ 不能写成 reg.iter('PROPERTY')，也不能用扁平正则 —— `<REGISTER>` 里嵌着
       `<FIELDS><FIELD><PROPERTY NAME="ADDRESS_OFFSET" .../>`，而**字段的
       ADDRESS_OFFSET 是位号，不是字节偏移**。混进来就会得到「两个寄存器同偏移」
       这种自相矛盾的结果，而且不报错。本项目 2026-11-01 正是这么错的。
    """
    return {p.get('NAME'): p.get('VALUE') for p in reg.findall('PROPERTY')}


def _int0(v, default=None):
    """`ADDRESS_OFFSET` 在同一份 .hwh 里可能一个 IP 写 '0x30'、另一个写 '16'。

    ⇒ 一律 int(v, 0)。⛔ 别写 int(v, 16)（把 '16' 解成 22），也别写 int(v)（'0x30' 直接抛）。
    """
    if v is None:
        return default
    try:
        return int(str(v).strip(), 0)
    except ValueError:
        return default


def parse_hwh(path):
    """返回 (modules, mems)。异常往上抛，由 main 记**全文**（含 traceback）。"""
    root = ET.parse(path).getroot()

    mems = {}
    for mr in root.iter('MEMRANGE'):
        if mr.get('MEMTYPE') != 'REGISTER':
            continue                      # MEMTYPE="MEMORY" 是 DDR 映射，不是外设
        inst = mr.get('INSTANCE')
        base = _int0(mr.get('BASEVALUE'))
        if inst is None or base is None:
            continue
        if inst not in mems:              # 同一 IP 多个地址块时取第一个
            mems[inst] = {'base': base,
                          'high': _int0(mr.get('HIGHVALUE')),
                          'iface': mr.get('SLAVEBUSINTERFACE')}

    mods = []
    for mod in root.iter('MODULE'):
        blocks = []
        for ab in mod.findall('ADDRESSBLOCKS/ADDRESSBLOCK'):
            regs = []
            for reg in ab.findall('REGISTERS/REGISTER'):
                props = _prop_map(reg)
                off = _int0(props.get('ADDRESS_OFFSET'))
                if off is None:
                    continue
                regs.append({'name': reg.get('NAME'),
                             'off': off,
                             'bits': _int0(props.get('SIZE'), 32),
                             'access': (props.get('ACCESS') or '?').strip()})
            if regs:
                blocks.append({'name': ab.get('NAME'),
                               'iface': ab.get('INTERFACE'),
                               'range': _int0(ab.get('RANGE'), 0),
                               'regs': regs})
        if blocks:
            mods.append({'inst': mod.get('INSTANCE'),
                         'full': mod.get('FULLNAME'),
                         'vlnv': mod.get('VLNV'),
                         'blocks': blocks})
    return mods, mems


# ── 判定 ────────────────────────────────────────────────────────────────
def audit(mods, mems):
    """返回 (verdict, fails, notes)。verdict ∈ {PASS, FAIL, N/A}。"""
    fails, notes = [], []

    for m in mods:
        inst = m['inst']
        if inst not in mems:
            fails.append('%s（%s）：有寄存器表，但 .hwh 里没有它的 MEMRANGE 基地址'
                         ' ⇒ 生成出来的骨架没有可用基址' % (inst, m['vlnv']))
            continue
        for b in m['blocks']:
            seen = {}
            for r in b['regs']:
                if r['off'] in seen:
                    fails.append(
                        '%s 的地址块 %s：寄存器 %s 与 %s 落在同一个偏移 %s'
                        ' ⇒ 结构上不可能，几乎一定是解析错了（先查有没有把 <FIELD> 的'
                        '位号当成字节偏移）'
                        % (inst, b['name'], r['name'], seen[r['off']], hex(r['off'])))
                seen[r['off']] = r['name']
                width = max(r['bits'] // 8, 4)
                if b['range'] and r['off'] + width > b['range']:
                    fails.append('%s 的地址块 %s：寄存器 %s 在 %s，宽 %d 字节，'
                                 '超出地址块 RANGE=%s'
                                 % (inst, b['name'], r['name'], hex(r['off']),
                                    width, b['range']))
                if r['off'] % 4:
                    notes.append('%s.%s 的偏移 %s 不是 4 的倍数 —— 对 32 位 AXI-Lite '
                                 '寄存器而言不正常，人工看一眼'
                                 % (inst, r['name'], hex(r['off'])))

    if fails:
        return 'FAIL', fails, notes
    if not mods:
        return 'N/A', [], ['这份 .hwh 里没有任何 IP 带寄存器表 —— 没东西可生成。'
                           '（常见原因：纯 video / DMA 走 Vitis 库，或用的是只有'
                           ' MEMORY 映射的裸 AXI 流设计）']
    return 'PASS', [], notes


def find_u64_pairs(mod):
    """找 `x_1` / `x_2` 这种低/高 32 位成对的 64 位寄存器（HLS 的 m_axi 指针就这样）。

    只用于生成更安全的写函数，**不参与判定** —— 认错了也不会判红，最多多给一个提示。
    """
    pairs = []
    for b in mod['blocks']:
        by = {r['name']: r for r in b['regs']}
        for r in b['regs']:
            if not r['name'].endswith('_1'):
                continue
            hi = by.get(r['name'][:-2] + '_2')
            if hi and hi['off'] == r['off'] + 4:
                pairs.append((r['name'], hi['name'], r['off']))
    return pairs


# ── 生成 ────────────────────────────────────────────────────────────────
def render(mods, mems, src, src_sha):
    L = []
    A = L.append
    A('# -*- coding: utf-8 -*-')
    # ⚠️ 这个 docstring 必须写成 **raw 字符串**：里面要放源码的绝对路径，
    #    而 Windows 上 `D:\Users\...` 的 `\U` 会被当成 `\UXXXXXXXX` 转义，
    #    生成物直接 SyntaxError（2026-11-01 自检当场抓到）。
    A('r"""%s 的主机侧调用骨架 —— **由 gen-host-skeleton.py 自动生成**。' % os.path.basename(src))
    A('')
    A('    源文件 %s' % os.path.abspath(src))
    A('    源 sha16 %s' % src_sha)
    A('    生成于 %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    A('')
    A('⛔ 这是**生成物**。改它没用 —— 要改就改 .hwh 然后重新生成，')
    A('   或者改生成器 scripts/gen-host-skeleton.py。')
    A('')
    A('三条已经编进来的规矩（都是踩过的）：')
    A('  ① write-only 的寄存器**读不回来**，读它得到的是垃圾 ⇒ r() 会直接拒绝')
    A('  ② 偏移一律从 .hwh 取，**不按 4 字节推算** ⇒ 同一个工程里见过 4 和 8 两种步长')
    A('  ③ 64 位地址必须**拆成低/高两个 32 位依次写** ⇒ 用 w_u64()，别自己拼')
    A('"""')
    A('')
    A('# ── 基地址（来自 .hwh 的 MEMRANGE，MEMTYPE="REGISTER"）──────────────')
    A('#    ⛔ 别照抄别处的 0x43C00000 —— 那个数是常见，不是规定。')
    A('BASE = {')
    for m in mods:
        A("    %r: 0x%08X,   # %s" % (m['inst'], mems[m['inst']]['base'], m['full']))
    A('}')
    A('')
    A('# ── 寄存器表：名字 -> (字节偏移, 位宽, 访问权限) ─────────────────────')
    A('REG = {')
    for m in mods:
        A("    %r: {" % m['inst'])
        for b in m['blocks']:
            for r in b['regs']:
                A("        %-12r: (%s, %d, %r),"
                  % (r['name'], '0x%02X' % r['off'], r['bits'], r['access']))
        A('    },')
    A('}')
    A('')
    A('# ── write-only：只能写，读回来不是你以为的那个值 ──────────────────────')
    A('WRITE_ONLY = {')
    for m in mods:
        wo = [r['name'] for b in m['blocks'] for r in b['regs']
              if r['access'] == 'write-only']
        if wo:
            A('    %r: %r,' % (m['inst'], wo))
    A('}')
    A('')
    u64any = False
    for m in mods:
        if find_u64_pairs(m):
            u64any = True
    if u64any:
        A('# ── 64 位寄存器对：(低半名, 高半名, 低半偏移) ────────────────────────')
        A('U64_PAIRS = {')
        for m in mods:
            ps = find_u64_pairs(m)
            if ps:
                A('    %r: %r,' % (m['inst'], ps))
        A('}')
        A('')
    A('')
    A('# ── 封装 ────────────────────────────────────────────────────────────')
    A('class Ip(object):')
    A('    """按 .hwh 生成的读写封装 —— 用错方向会当场抛，不会静默给垃圾。"""')
    A('')
    A('    def __init__(self, overlay, name=None):')
    A('        self.name = name or type(self).__name__')
    A('        self.base = BASE[self.name]')
    A('        self.ip = getattr(overlay, self.name)      # PYNQ 按 .hwh 的 INSTANCE 命名')
    A('        self.mmio = self.ip.mmio')
    A('')
    A('    def w(self, reg, value):')
    A('        off, bits, acc = REG[self.name][reg]')
    A("        if acc == 'read-only':")
    A("            raise ValueError('%s.%s 是只读寄存器，写它没有意义' % (self.name, reg))")
    A('        self.mmio.write(off, int(value) & ((1 << bits) - 1))')
    A('')
    A('    def r(self, reg):')
    A('        off, bits, acc = REG[self.name][reg]')
    A("        if acc == 'write-only':")
    A("            raise ValueError('%s.%s 是 write-only，读回来不是你以为的那个值；"
      "要确认写没写进去，请用输出数据判' % (self.name, reg))")
    A('        return self.mmio.read(off)')
    A('')
    A('    def w_u64(self, reg_lo, value):')
    A('        """写 64 位寄存器：**低半在前、高半在后，两个 32 位分两次写**。')
    A('')
    A('        register_map 不会把 `x_1` + `x_2` 合并成一个 64 位属性，别指望它。')
    A('        """')
    A('        lo, hi = REG[self.name][reg_lo][0], REG[self.name][reg_lo][0] + 4')
    A('        v = int(value)')
    A('        self.mmio.write(lo, v & 0xFFFFFFFF)')
    A('        self.mmio.write(hi, (v >> 32) & 0xFFFFFFFF)')
    A('')
    A('')
    A('# ── Overlay 校验：**加载成功不等于配对了** ────────────────────────────')
    A('def verify_overlay(overlay):')
    A('    """核每个 IP 的实际基地址与 .hwh 一致。')
    A('')
    A('    PYNQ 建 ip_dict 时只读 .hwh，它没有办法知道这个 .hwh 是不是跟 .bit')
    A('    同一次构建的 ⇒ **.hwh 是旧的时候，加载照样成功、地址表照样错、一声不吭**。')
    A('    所以这行断言必须跑。')
    A('    """')
    A('    bad = []')
    A('    for name, want in BASE.items():')
    A("        got = overlay.ip_dict.get(name, {}).get('phys_addr')")
    A('        if got != want:')
    A("            bad.append('%s: 期望 0x%08X，实际 %r' % (name, want, got))")
    A('    if bad:')
    A("        raise RuntimeError('基地址与 .hwh 对不上（.bit 和 .hwh 可能不是同一次构建）："
      "\\n  ' + '\\n  '.join(bad))")
    A('    return True')
    A('')
    A('')
    A('# ── 冒烟测试骨架：把 TODO 换成你核的第一条判据 ────────────────────────')
    A('def smoke(overlay):')
    A('    """最小数据通路冒烟。**必须比对数值**，不能只看 kernel 跑完了。')
    A('')
    A('    ⚠️ 别用「读回寄存器看写没写进去」当冒烟 —— write-only 的寄存器读不回来，')
    A('       而 kernel 拿着地址 0 原地跑完时**照样会正常置 AP_DONE**。')
    A('    """')
    A('    verify_overlay(overlay)')
    A('    # TODO 1: 造一个**答案唯一**的输入（恒定灰度 / 已知向量）')
    A('    # TODO 2: 跑一遍 kernel')
    A('    # TODO 3: 断言输出等于期望值 —— 只判数值，不判"跑完了"')
    A('    # TODO 4: 第一次跑通后记下输出指纹（sha256 或逐元素和），以后每次核它')
    A('    raise NotImplementedError("补齐 smoke() 里的 TODO 再上板")')
    A('')
    return '\n'.join(L) + '\n'


# ── 自检：先证明能判红，且**判红的理由是预期的那一个** ──────────────────
FIX_HEAD = '<EDKSYSTEM><MODULES>'
FIX_TAIL = '</MODULES></EDKSYSTEM>'


def _fix(module_xml, memrange_xml=''):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + FIX_HEAD + module_xml +
            '</MODULES><MEMRANGES>' + memrange_xml + '</MEMRANGES></EDKSYSTEM>')


def _reg(name, off, access='read-write', bits=32, fields=None):
    s = ('<REGISTER NAME="%s">'
         '<PROPERTY NAME="ADDRESS_OFFSET" VALUE="%s"/>'
         '<PROPERTY NAME="SIZE" VALUE="%d"/>'
         '<PROPERTY NAME="ACCESS" VALUE="%s"/>'
         % (name, off, bits, access))
    if fields:
        s += '<FIELDS>'
        for fn, foff in fields:
            s += ('<FIELD NAME="%s">'
                  '<PROPERTY NAME="ADDRESS_OFFSET" VALUE="%s"/>'
                  '<PROPERTY NAME="BIT_OFFSET" VALUE="%s"/>'
                  '</FIELD>' % (fn, foff, foff))
        s += '</FIELDS>'
    return s + '</REGISTER>'


def _mod(inst, regs, rng=65536):
    return ('<MODULE FULLNAME="/%s" INSTANCE="%s" VLNV="test:ip:%s:1.0">'
            '<ADDRESSBLOCKS><ADDRESSBLOCK NAME="Reg" INTERFACE="s_axi" RANGE="%d">'
            '<REGISTERS>%s</REGISTERS></ADDRESSBLOCK></ADDRESSBLOCKS></MODULE>'
            % (inst, inst, inst, rng, regs))


def _mem(inst, base):
    return ('<MEMRANGE INSTANCE="%s" MEMTYPE="REGISTER" BASEVALUE="%s" '
            'HIGHVALUE="0x%08X" SLAVEBUSINTERFACE="s_axi"/>' % (inst, base, int(base, 0) + 0xFFF))


def _write_tmp(d, name, text):
    p = os.path.join(d, name)
    with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return p


def selftest():
    import tempfile
    import shutil

    say('=' * 92)
    say('# gen-host-skeleton 自检（证明能判红、也能判绿）   %s'
        % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('#   主机 %s   python %s' % (os.environ.get('COMPUTERNAME', '?'),
                                    sys.version.split()[0]))
    say('#   脚本 sha16 %s' % sha16_file(os.path.abspath(__file__)))
    say('=' * 92)

    tmp = tempfile.mkdtemp(prefix='ghs_')
    ok = bad = 0

    def arm(label, fn, want, reason=''):
        nonlocal ok, bad
        try:
            got, fails, _notes = fn()
        except Exception:
            got, fails = 'EXC', [traceback.format_exc()]
        # 理由只在**判红**时才要求核对 —— PASS / N/A 本来就没有 fails
        # （第一版这里无条件核理由，于是 4 条判绿的臂全被自己判成 BAD）
        hit = (got == want) and (got != 'FAIL' or not reason
                                 or any(reason in f for f in fails))
        if hit:
            ok += 1
            say('  [OK ] %-46s → %s' % (label, got))
        else:
            bad += 1
            say('  [BAD] %-46s → %s（期望 %s%s）'
                % (label, got, want, '，理由含「%s」' % reason if reason else ''))
            for f in fails:
                say('           %s' % f)

    def judge(text, **kw):
        p = _write_tmp(tmp, 'f%d.hwh' % (len(os.listdir(tmp))), text)
        mods, mems = parse_hwh(p)
        return audit(mods, mems)

    # 1) FIELD 陷阱：字段的 ADDRESS_OFFSET 是**位号**，绝不能串进寄存器偏移
    t = _fix(_mod('k', _reg('CTRL', '0', fields=[('AP_START', '0'), ('AP_DONE', '1')]) +
                  _reg('w_out', '16', 'write-only')), _mem('k', '0x40030000'))
    def a1():
        mods, mems = parse_hwh(_write_tmp(tmp, 'a1.hwh', t))
        offs = [r['off'] for r in mods[0]['blocks'][0]['regs']]
        if offs == [0, 16]:
            return 'PASS', [], []
        return 'FAIL', ['寄存器偏移解析成了 %r（应当 [0, 16]）——字段位号串进来了' % offs], []
    arm('FIELD 位号不得串进寄存器偏移', a1, 'PASS', '字段位号')

    # 2) 同一文件里 0x30 与 16 两种写法都要解对
    t2 = _fix(_mod('k', _reg('A', '0x30') + _reg('B', '16')), _mem('k', '0x40000000'))
    def a2():
        mods, _ = parse_hwh(_write_tmp(tmp, 'a2.hwh', t2))
        got = sorted(r['off'] for r in mods[0]['blocks'][0]['regs'])
        if got == [16, 48]:
            return 'PASS', [], []
        return 'FAIL', ['偏移解析成 %r（应当 [16, 48]）——十进制/十六进制没同时支持' % got], []
    arm('十进制与十六进制偏移都要解对', a2, 'PASS', '十进制')

    # 3) 偏移重复 ⇒ 必须判红（这正是"字段位号串进来"产生的症状）
    t3 = _fix(_mod('k', _reg('w_out', '16') + _reg('h_out', '16')), _mem('k', '0x40030000'))
    arm('两个寄存器同偏移 ⇒ 判红', lambda: judge(t3), 'FAIL', '同一个偏移')

    # 4) 超地址块 RANGE ⇒ 判红
    t4 = _fix(_mod('k', _reg('X', '0x20000'), rng=65536), _mem('k', '0x40000000'))
    arm('寄存器超出地址块 RANGE ⇒ 判红', lambda: judge(t4), 'FAIL', '超出地址块')

    # 5) 有寄存器表但没有基地址 ⇒ 判红
    t5 = _fix(_mod('k', _reg('X', '0')), '')
    arm('有寄存器表却无 MEMRANGE 基址 ⇒ 判红', lambda: judge(t5), 'FAIL', '没有它的 MEMRANGE')

    # 6) 只有 MEMORY 映射 ⇒ N/A，**不算通过**
    t6 = ('<?xml version="1.0" encoding="UTF-8"?><EDKSYSTEM><MODULES/>'
          '<MEMRANGES><MEMRANGE INSTANCE="ps7" MEMTYPE="MEMORY" BASEVALUE="0x0" '
          'HIGHVALUE="0x1FFFFFFF"/></MEMRANGES></EDKSYSTEM>')
    arm('没有任何寄存器表 ⇒ N/A（不算通过）', lambda: judge(t6), 'N/A')

    # ── 7) 生成物**真的执行一遍**：读写方向错了必须当场抛 ────────────────
    #    ⚠️ 第一版这里只做 `"acc == 'write-only'" in txt` 的字符串检查 —— 那是
    #       在验「模板里有没有这行字」，不是在验「它真的会拒绝」。故意删掉那行守卫，
    #       自检依然全绿（当时用 sed 注入缺陷实测过）。字符串检查会空转，行为检查不会。
    class _Mmio(object):
        def __init__(self):
            self.log = []

        def write(self, off, v):
            self.log.append(('w', off, v))

        def read(self, off):
            self.log.append(('r', off))
            return 0

    def _load(txt, inst='k'):
        ns = {}
        exec(compile(txt, '<gen>', 'exec'), ns)
        ov = type('FakeOverlay', (), {})()
        setattr(ov, inst, type('FakeIp', (), {'mmio': _Mmio()})())
        obj = ns['Ip'](ov, inst)
        return ns, obj

    t7 = _fix(_mod('k', _reg('CTRL', '0') + _reg('w', '16', 'write-only') +
                   _reg('mask_1', '20', 'write-only') +
                   _reg('mask_2', '24', 'write-only') +
                   _reg('ST', '32', 'read-only')), _mem('k', '0x40030000'))

    def a7():
        mods, mems = parse_hwh(_write_tmp(tmp, 'a7.hwh', t7))
        ns, obj = _load(render(mods, mems, 'x.hwh', 'deadbeefdeadbeef'))
        errs = []
        try:
            obj.r('w')
            errs.append("r('w') 没有拒绝 write-only —— 这条正是本项目踩过的坑")
        except ValueError:
            pass
        try:
            obj.w('ST', 1)
            errs.append("w('ST') 没有拒绝 read-only")
        except ValueError:
            pass
        obj.w('CTRL', 0x1)                      # 合法的写要真的落到 mmio
        obj.r('ST')                             # 合法的读要真的走到 mmio
        ops = obj.ip.mmio.log
        if ('w', 0, 1) not in ops:
            errs.append('合法的 w() 没写进 mmio，实际操作 %r' % (ops,))
        if not any(o[0] == 'r' and o[1] == 32 for o in ops):
            errs.append('合法的 r() 没读 mmio，实际操作 %r' % (ops,))
        return ('FAIL' if errs else 'PASS'), errs, []
    arm('生成物必须拒掉「读 write-only / 写 read-only」', a7, 'PASS', '没有拒绝')

    # 8) 64 位：**执行** w_u64，必须写两次、低半在前
    def a8():
        mods, mems = parse_hwh(_write_tmp(tmp, 'a7.hwh', t7))
        ns, obj = _load(render(mods, mems, 'x.hwh', 'deadbeefdeadbeef'))
        errs = []
        if ns.get('U64_PAIRS', {}).get('k') != [('mask_1', 'mask_2', 20)]:
            errs.append('64 位成对识别成 %r（应当 [("mask_1","mask_2",20)]）'
                        % (ns.get('U64_PAIRS', {}).get('k'),))
        obj.ip.mmio.log[:] = []
        obj.w_u64('mask_1', 0x1122334455667788)
        ops = obj.ip.mmio.log
        if ops != [('w', 20, 0x55667788), ('w', 24, 0x11223344)]:
            errs.append('w_u64 写了 %r（应当先低半 20/0x55667788、再高半 24/0x11223344）'
                        % (ops,))
        return ('FAIL' if errs else 'PASS'), errs, []
    arm('w_u64 必须拆两次写、低半在前', a8, 'PASS', '64 位成对')

    # 9) 基地址必须照抄 .hwh，**不许**出现「常见默认值」0x43C00000
    t9 = _fix(_mod('k', _reg('X', '0')), _mem('k', '0x40030000'))
    def a9():
        mods, mems = parse_hwh(_write_tmp(tmp, 'a9.hwh', t9))
        txt = render(mods, mems, 'x.hwh', 'deadbeefdeadbeef')
        # ⚠️ 只看 BASE 字典那一段。整篇找 0x43C00000 会误报 —— 生成物里那句
        #    "⛔ 别照抄 0x43C00000" 的提示注释自己就会命中（第一版正是这么误判的）。
        blk = txt.split('BASE = {', 1)[-1].split('}', 1)[0]
        if '0x40030000' in blk and '0x43C00000' not in blk:
            return 'PASS', [], []
        return 'FAIL', ['BASE 字典没照 .hwh 写：%r' % blk.strip()], []
    arm('基地址只从 .hwh 来，不用 0x43C00000', a9, 'PASS', '0x43C00000')

    # 9b) 源码路径含 `\U`（Windows 的 D:\Users\...）时，生成物必须仍然能编译
    #     —— 第一版不是 raw docstring，这里会 SyntaxError
    def a9b():
        mods, mems = parse_hwh(_write_tmp(tmp, 'a9.hwh', t9))
        txt = render(mods, mems, r'D:\Users\someone\design.hwh', 'deadbeefdeadbeef')
        try:
            compile(txt, '<gen>', 'exec')
        except SyntaxError:
            return 'FAIL', ['生成物编译不过（路径里的 \\U 被当成转义）：\n'
                            + traceback.format_exc()], []
        return 'PASS', [], []
    arm('源码路径含 \\U 时生成物仍要能编译', a9b, 'PASS', '编译不过')

    # 10) 非 XML ⇒ 必须炸（而不是静默当没事）
    def a10():
        p = _write_tmp(tmp, 'a10.hwh', 'this is not xml\n')
        try:
            parse_hwh(p)
        except ET.ParseError as e:
            return 'FAIL', ['不是合法 XML：%s' % e], []
        return 'PASS', [], []
    arm('非 XML ⇒ 解析必须抛错', a10, 'FAIL', '不是合法 XML')

    shutil.rmtree(tmp, ignore_errors=True)

    say('')
    say('自检 %d 条：通过 %d，失败 %d' % (ok + bad, ok, bad))
    if bad:
        say('【自检失败】这个生成器本身不可信，别拿它的输出当结论')
        return 1
    say('【自检通过】能判绿（正常 .hwh）、能判红（重复偏移 / 超范围 / 无基址 / 非 XML），'
        '且判红的**理由**都是预期的那一条')
    return 0


# ── main ────────────────────────────────────────────────────────────────
def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('hwh', nargs='?', help='.hwh 文件（Overlay 用的那份）')
    ap.add_argument('--out', default=os.getcwd(), help='生成物放哪（默认当前目录）')
    ap.add_argument('--ip', default=None, help='只生成这个名字的 IP')
    ap.add_argument('--name', default=None,
                    help='生成物文件名（默认 <hwh 主名>_host_skeleton.py）。'
                         '⚠️ 每份 BD 的 .hwh 都叫 system.hwh，不做区分会互相覆盖')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)

    _open_log()
    try:
        if a.selftest:
            return selftest()
        if not a.hwh:
            say('用法：python gen-host-skeleton.py <design.hwh> [--out 目录] [--ip 名字]')
            say('      python gen-host-skeleton.py --selftest')
            return 2

        src = os.path.abspath(a.hwh)
        say('=' * 92)
        say('# 主机侧骨架生成   %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
        say('#   主机 %s   python %s   cwd %s'
            % (os.environ.get('COMPUTERNAME', '?'), sys.version.split()[0], os.getcwd()))
        say('#   脚本 %s' % os.path.abspath(__file__))
        say('#   sha16 %s' % sha16_file(os.path.abspath(__file__)))
        say('#   输入 %s' % src)
        say('=' * 92)

        if not os.path.exists(src):
            say('')
            say('[FAIL] 输入不存在：%s' % src)
            return 2

        src_sha = sha16_file(src)
        say('#   输入 sha16 %s（%d 字节）' % (src_sha, os.path.getsize(src)))

        try:
            mods, mems = parse_hwh(src)
        except ET.ParseError as e:
            say('')
            say('[FAIL] .hwh 不是合法 XML —— PYNQ 的 Overlay() 用的是 ElementTree，'
                '非 XML 的 .hwh 一定加载不了')
            say(traceback.format_exc())
            return 1

        verdict, fails, notes = audit(mods, mems)

        say('')
        say('解析到：%d 个带寄存器表的 IP，%d 个 MEMRANGE（MEMTYPE=REGISTER）'
            % (len(mods), len(mems)))
        for m in mods:
            say('')
            say('  %-32s base=%s  %s' % (m['inst'], hex(mems[m['inst']]['base'])
                                         if m['inst'] in mems else '(无)', m['vlnv']))
            for b in m['blocks']:
                say('    地址块 %-10s 接口 %-14s RANGE=%d'
                    % (b['name'], b['iface'], b['range']))
                for r in b['regs']:
                    say('      %-12s off=%-8s %2d bit  %s'
                        % (r['name'], hex(r['off']), r['bits'], r['access']))

        if notes:
            say('')
            say('提示（不判红，但请人工看一眼）：')
            for n in notes:
                say('  · %s' % n)

        say('')
        if verdict == 'FAIL':
            say('[FAIL] 结构检查没过 —— **不写盘**。一份偏移重复的骨架比没有骨架更危险：')
            for f in fails:
                say('  · %s' % f)
            return 1
        if verdict == 'N/A':
            for n in fails or notes:
                say('  · %s' % n)
            say('[N/A] 没生成任何东西 —— 这**不算通过**，只是这份 .hwh 没东西可生成')
            return 0

        if a.ip:
            mods = [m for m in mods if m['inst'] == a.ip]
            if not mods:
                say('[FAIL] --ip %s 不在 .hwh 里' % a.ip)
                return 2

        text = render(mods, mems, src, src_sha)
        os.makedirs(a.out, exist_ok=True)
        name = a.name or (os.path.splitext(os.path.basename(src))[0] + '_host_skeleton.py')
        if not name.endswith('.py'):
            name += '.py'
        dst = os.path.join(a.out, name)
        if os.path.exists(dst):
            # ⚠️ 每份 BD 导出的 .hwh 都叫 system.hwh ⇒ 不提示的话，两份不同设计的骨架
            #    会静默互相覆盖。覆盖本身是有意的（生成物就该可重建），但要说一声。
            say('#   注意：覆盖了已存在的 %s' % dst)
        with io.open(dst, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())

        # 存盘后回读复核 —— 写失败 / 编码坏掉当场暴露，而不是等到板上 import 才炸
        back = io.open(dst, encoding='utf-8').read()
        if back != text:
            say('[FAIL] 回读与写入内容不一致：%s' % dst)
            return 1
        try:
            compile(back, dst, 'exec')
        except SyntaxError:
            say('[FAIL] 生成物语法有问题（生成器自己的 bug）：')
            say(traceback.format_exc())
            return 1

        say('[PASS] 生成 %d 个 IP 的骨架：%s（%d 字节，回读一致、能编译）'
            % (len(mods), dst, os.path.getsize(dst)))
        say('#   生成物 sha16 %s' % sha16_file(dst))
        say('')
        say('下一步（**别跳过**）：打开生成物，把 smoke() 里的 TODO 换成你核自己的判据，')
        say('然后跑一次 —— verify_overlay() 会把「.bit 和 .hwh 不是同一次构建」当场揪出来。')
        return 0
    except Exception:
        say('')
        say('[FAIL] 未预期的异常 —— 全文如下，未截断：')
        say(traceback.format_exc())
        return 1
    finally:
        if _fh is not None:
            _fh.flush()
            _fh.close()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
