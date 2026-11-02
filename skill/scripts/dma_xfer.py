#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AXI DMA 搬运 + 缓存一致性封装 —— **带超时**，出错时自己去读寄存器定位。

对应竞赛《选题指南（AMD）》3.3.2 的加分项：
「可复用的 DMA 搬运与缓存一致性处理封装，含常见出错情形的定位方法」。

用法（板上，PS 侧 Python）：

    from dma_xfer import transfer_np, DmaXfer

    # ① 一步到位：numpy 进、numpy 出
    out = transfer_np(ol.axi_dma_0, frame)

    # ② 想自己管缓冲（省掉每帧 allocate）
    x = DmaXfer(ol.axi_dma_0, timeout=2.0)
    x.transfer(buf_in, buf_out)          # 内含 sync_to_device / 两次 transfer /
                                         # 带超时的等待 / sync_from_device
    print(x.status())                    # S2MM_DMASR 原始值 + 置位的中文名

自检（**不需要 pynq，也不需要板子**）：

    python dma_xfer.py --selftest

⚠️ 已实测到什么程度（如实写）：
    · 这两条 `sync` 的方向、`allocate` 的必要性、`wait` 无超时会挂死 —— 都是本项目
      在 PYNQ-Z2 上真踩过并修好的，依据见 references/19-pynq-runtime.md 第三、四节。
    · **但这份「通用封装」本身没有单独上板跑过** —— 它是从跑通的代码里提炼的。
      自检用的是假对象，验的是**调用顺序 / 超时 / 定位信息**，不是硬件行为。
      第一次上板请先拿一个已知输入跑通，再接到主流程里。

为什么这些细节值得封装：
    忘 `sync_to_device()` ⇒ PL 读到**旧数据**；忘 `sync_from_device()` ⇒ CPU 读到**旧数据**。
    两条都**不报错**，只是结果不对。而 `wait()` 不带超时 ⇒ 出问题时**整帧挂死**，
    看起来像板子死了。三种失败模式都是静默的 —— 所以写成封装，比写在文档里可靠。
"""
import io
import os
import sys
import time
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(os.getcwd(), '_dma_xfer.log')
_fh = None

DEFAULT_TIMEOUT = 2.0          # 秒。2 s 对一帧 DMA 是很宽裕的上限，真超了就是出事了
POLL = 0.0005                  # 轮询间隔

CR_OFF = 0x30                  # S2MM_DMACR
SR_OFF = 0x34                  # S2MM_DMASR
MM2S_SR_OFF = 0x04             # MM2S_DMASR（send 通道）
CR_RESET = 0x4                 # DMACR bit2 = Reset

# S2MM_DMASR 位表 —— 2026-11-01 从真 `.hwh`（`axi_dma_0`）解析得到，不是翻手册抄的。
# 换 IP / 换版本时**从你自己的 `.hwh` 重新读一遍**（取法见 references/19 §4.1）。
SR_BITS = ((0, 'Halted'), (1, 'Idle'), (3, 'SGIncld'),
           (4, 'DMAIntErr'), (5, 'DMASlvErr'), (6, 'DMADecErr'),
           (8, 'SGIntErr'), (9, 'SGSlvErr'), (10, 'SGDecErr'),
           (12, 'IOC_Irq'), (13, 'Dly_Irq'), (14, 'Err_Irq'))

ERR_BITS = ('DMAIntErr', 'DMASlvErr', 'DMADecErr',
            'SGIntErr', 'SGSlvErr', 'SGDecErr')


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


def decode_sr(v):
    """把 S2MM_DMASR 的原始值翻成「置位了哪些位」。返回中文名列表。"""
    if v is None:
        return []
    return [name for bit, name in SR_BITS if (int(v) >> bit) & 1]


def diagnose(v):
    """返回一句人话。⛔ 判据只用 SR，不猜。"""
    if v is None:
        return '拿不到状态寄存器（没有 mmio 句柄，或读失败）—— 先解决读不到，再谈结论'
    on = decode_sr(v)
    bad = [n for n in on if n in ERR_BITS]
    if bad:
        return 'SR=0x%08X 有错误位：%s —— DMA 已经把错误报出来了，先查地址/长度对齐' % (v, ', '.join(bad))
    if v & 1:                                     # bit0 Halted
        return ('SR=0x%08X Halted=1 ⇒ **DMA 已经停了，传输没有完成**。'
                '常见于：上次被 SIGKILL 没停车、或有人写过 Reset、或根本没 start' % v)
    if not (v & 2):                               # bit1 Idle
        return ('SR=0x%08X Idle=0 且 Halted=0 ⇒ **还在跑，是超时不是失败**。'
                '要么数据量超预期，要么 PL 侧核没把 TLAST 拉起来（帧永远不完成）' % v)
    return 'SR=0x%08X Idle=1 Halted=0 ⇒ 通道空闲，正常' % v


class DmaError(RuntimeError):
    def __init__(self, msg, sr=None, channel=''):
        self.sr = sr
        self.channel = channel
        RuntimeError.__init__(self, msg)


class DmaXfer(object):
    """把「刷 cache → 起两路 → 带超时地等 → 失效 cache」封成一次调用。

    ⚠️ 只做**简单模式**（Simple DMA，一次一块）。Scatter-Gather、多缓冲环、
    中断模式都**没有**做，见 references/19 §6。
    """

    def __init__(self, dma, mmio=None, timeout=DEFAULT_TIMEOUT, poll=POLL, log=None):
        self.dma = dma
        # DMA 的寄存器走 mmio 按字节偏移读写；register_map 那边不保证能写（见 19 §2.5）
        self.mmio = mmio if mmio is not None else getattr(dma, 'mmio', None)
        self.timeout = float(timeout)
        self.poll = float(poll)
        self.log = log                      # None = 不打印；传 say 就打印

    # ── 状态 ──────────────────────────────────────────────────────────
    def _read(self, off):
        if self.mmio is None:
            return None
        try:
            return int(self.mmio.read(off))
        except Exception:
            return None

    def status(self):
        v = self._read(SR_OFF)
        return {'raw': v, 'on': decode_sr(v), 'text': diagnose(v)}

    def reset(self, settle=0.2):
        """往 S2MM_DMACR 写 Reset(0x4)，等 settle 秒后复核。

        ⛔ 这是「上次把自己搞死了」的救法，不是常规操作。
        本项目真事故：脚本被 SIGKILL 后采集 VDMA 还在往已释放的物理内存写，
        症状是 `import cv2` 段错误 / `free(): invalid next size` —— 看着像环境坏了。
        """
        if self.mmio is None:
            raise DmaError('没有 mmio 句柄，无法复位（构造时传 mmio=…）')
        self.mmio.write(CR_OFF, CR_RESET)
        time.sleep(settle)
        v = self._read(SR_OFF)
        if v is None:
            raise DmaError('复位后读不到 S2MM_DMASR')
        if not (v & 1):
            raise DmaError('写了 Reset(0x4) 但 SR=0x%08X 里 Halted 仍为 0 —— '
                           '复位没生效，或这个 IP 的 Reset 位不在 DMACR bit2' % v, v, 'S2MM')
        return v

    # ── 主流程 ────────────────────────────────────────────────────────
    def _log(self, s):
        if self.log:
            self.log(s)

    def _wait(self, ch, name, sr_off, deadline):
        """带超时的等待。

        为什么不用 `ch.wait()`：PYNQ 的 `DMAChannel.wait()` **没有超时参数**。
        挂住的时候它就一直挂着 —— 整帧停死，看起来像板子坏了。
        这里改成轮询 `ch.running`（它读的就是 SR 的 Halted/Idle 两位）+ 死线。
        """
        n = 0
        while getattr(ch, 'running', False):
            if time.monotonic() > deadline:
                v = self._read(sr_off)
                raise DmaError(
                    '%s 通道等待超过 %.3f s 仍未完成。%s' % (name, self.timeout, diagnose(v)),
                    v, name)
            n += 1
            time.sleep(self.poll)
        return n

    def transfer(self, src, dst, timeout=None):
        """把 src 搬给 PL，把结果收进 dst。返回 dst。

        ⛔ 顺序不能动：sync_to_device **必须**在 sendchannel.transfer 之前，
           sync_from_device **必须**在两次等待之后。
        """
        t = self.timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + t

        self._log('① sync_to_device()  —— 少这一句，PL 读到的是 cache 里的旧数据')
        src.sync_to_device()

        self._log('② 起两路传输')
        self.dma.sendchannel.transfer(src)
        self.dma.recvchannel.transfer(dst)

        self._log('③ 带超时等待（默认 %.3f s）' % t)
        self._wait(self.dma.sendchannel, 'MM2S', MM2S_SR_OFF, deadline)
        self._wait(self.dma.recvchannel, 'S2MM', SR_OFF, deadline)

        # ↓ 走到这里才说明传输真完成了。超时抛异常时**绝不能**执行下面两句，
        #   否则调用方会拿到一个「看起来正常」的缓冲区，而里面是垃圾。
        self._log('④ sync_from_device() —— 少这一句，CPU 读到的是 cache 里的旧数据')
        dst.sync_from_device()
        return dst


def transfer_np(dma, frame, out_shape=None, timeout=DEFAULT_TIMEOUT):
    """numpy 进、numpy 出。自己 allocate / 拷贝 / 释放。

    ⛔ **普通 numpy 数组不能直接喂 m_axi** —— 它不保证物理连续；
       画布的 ROI 视图（`img[y0:y1, x0:x1]`）更是跨行非连续。必须先拷进 CMA 缓冲。
    """
    import numpy as np                    # 延迟导入：本模块在没装 pynq 的机器上也要能 import
    from pynq import allocate

    oshape = tuple(out_shape) if out_shape else tuple(frame.shape)
    src = allocate(shape=tuple(frame.shape), dtype=frame.dtype)
    dst = allocate(shape=oshape, dtype=frame.dtype)
    try:
        np.copyto(src, frame)
        DmaXfer(dma, timeout=timeout).transfer(src, dst)
        return np.asarray(dst).copy()     # 必须 .copy()：freebuffer 之后这块内存就还给池子了
    finally:
        src.freebuffer()
        dst.freebuffer()


# ── 自检：不需要 pynq，也不需要板子 ──────────────────────────────────
# 验的是**调用顺序 / 超时 / 定位信息**，不是硬件行为（硬件那部分要上板）。
class _FakeMmio(object):
    def __init__(self, sr=0x2):
        self.sr = sr
        self.reads = []
        self.writes = []

    def read(self, off):
        self.reads.append(off)
        return self.sr

    def write(self, off, val):
        self.writes.append((off, val))
        # ⛔ 这里必须写**字面量** 0x30 / 0x4，不能写 CR_OFF / CR_RESET：
        #    假对象要模拟的是**硬件规格**，不是被测代码自己。用同一个常数，
        #    代码里常数写错时两边一起错，这条臂就永远绿 —— 空转门就是这么来的。
        if off == 0x30 and val == 0x4:
            self.sr = 0x1          # 复位后 Halted=1


class _FakeBuf(object):
    def __init__(self, tag, calls):
        self.tag = tag
        self.calls = calls

    def sync_to_device(self):
        self.calls.append(self.tag + '.sync_to_device')

    def sync_from_device(self):
        self.calls.append(self.tag + '.sync_from_device')


class _FakeChan(object):
    """sr_seq 决定每次被问 `running` 时看到的 SR。默认 0x2（Idle）⇒ 一次就结束。"""

    def __init__(self, name, calls, sr_seq=None, max_poll=5000):
        self.name = name
        self.calls = calls
        self.sr_seq = list(sr_seq or [0x2])
        self.i = 0
        self.max_poll = max_poll

    def transfer(self, buf):
        self.calls.append(self.name + '.transfer')

    @property
    def running(self):
        if self.i == 0:
            self.calls.append(self.name + '.wait')     # 只记第一下，代表「开始等了」
        if self.i > self.max_poll:
            raise RuntimeError('%s 轮询超过 %d 次 —— 超时没有生效' % (self.name, self.max_poll))
        v = self.sr_seq[min(self.i, len(self.sr_seq) - 1)]
        self.i += 1
        return (v & 1) == 0 and (v & 2) == 0


class _FakeDma(object):
    def __init__(self, calls, send_sr=None, recv_sr=None):
        self.sendchannel = _FakeChan('MM2S', calls, send_sr)
        self.recvchannel = _FakeChan('S2MM', calls, recv_sr)


def _arm(name, cond, detail=''):
    say('')
    say('  %-26s %s%s' % (name, '合格' if cond else '不合格',
                          '' if cond else ('   ← ' + str(detail))))
    return bool(cond)


def selftest():
    say('=' * 92)
    say('# dma_xfer 自检（不需要 pynq，也不需要板子）   %s'
        % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('#   主机 %s   python %s   cwd %s'
        % (os.environ.get('COMPUTERNAME', '?'), sys.version.split()[0], os.getcwd()))
    say('#   脚本 %s' % os.path.abspath(__file__))
    say('#   sha16 %s' % sha16(open(__file__, 'rb').read()))
    say('=' * 92)
    ok = True

    # ① 调用顺序：两条 sync 的位置就是这条封装的**全部价值**
    calls = []
    dma = _FakeDma(calls)
    x = DmaXfer(dma, mmio=_FakeMmio(0x2), timeout=1.0)
    x.transfer(_FakeBuf('in', calls), _FakeBuf('out', calls))
    want = ['in.sync_to_device', 'MM2S.transfer', 'S2MM.transfer',
            'MM2S.wait', 'S2MM.wait', 'out.sync_from_device']
    ok &= _arm('顺序：先刷cache→起两路→等→失效', calls == want, calls)

    # ② 超时必须抛，且**不能** sync_from_device —— 否则调用方拿到垃圾却以为成功
    calls = []
    dma = _FakeDma(calls, recv_sr=[0x0])          # S2MM 永远「还在跑」
    x = DmaXfer(dma, mmio=_FakeMmio(0x0), timeout=0.02, poll=0.001)
    t0 = time.time()
    err = None
    try:
        x.transfer(_FakeBuf('in', calls), _FakeBuf('out', calls))
    except Exception as e:      # ⛔ 不能只捕 DmaError：抛出别的类型本身就是缺陷，
                                #    只捕 DmaError 会让自检**崩掉**而不是判红，看着像"臂没跑到"
        err = e
    dt = time.time() - t0
    ok &= _arm('超时：抛 DmaError',
               isinstance(err, DmaError) and err.channel == 'S2MM',
               '%s: %s' % (type(err).__name__, err))
    ok &= _arm('超时：绝不 sync_from_device', 'out.sync_from_device' not in calls, calls)
    ok &= _arm('超时：消息里带 SR 与判读',
               isinstance(err, DmaError) and 'SR=' in str(err) and '还在跑' in str(err), str(err))
    ok &= _arm('超时：真的到点就停', dt < 2.0, '%.3f s' % dt)

    # ③ Halted=1 与错误位：判读必须区分「停了 / 还在跑 / 报错」
    ok &= _arm('判读：Halted=1 说「停了」', '已经停了' in diagnose(0x1), diagnose(0x1))
    ok &= _arm('判读：Idle=0 说「还在跑」', '还在跑' in diagnose(0x0), diagnose(0x0))
    ok &= _arm('判读：错误位优先报',
               '错误位' in diagnose(0x2 | (1 << 4)), diagnose(0x2 | (1 << 4)))
    ok &= _arm('位表：0x1001 = Halted + IOC_Irq',
               decode_sr(0x1001) == ['Halted', 'IOC_Irq'], decode_sr(0x1001))

    # ④ reset：必须往 DMACR(0x30) 写 0x4，且写之前不能拿旧 SR 糊弄
    mm = _FakeMmio(0x2)
    x = DmaXfer(_FakeDma([]), mmio=mm)
    rerr = None
    got = None
    try:
        got = x.reset(settle=0.0)
    except Exception as e:      # 同上：抛异常也要判红，不能让自检崩掉
        rerr = e
    # ⛔ 期望值写**字面量**：写成 (CR_OFF, CR_RESET) 就是拿被测常数自证，
    #    常数改成 0x2 时两边一起变，这条臂永远绿（2026-11-01 变异测试当场抓到）
    ok &= _arm('reset：写 (0x30, 0x4)', mm.writes == [(0x30, 0x4)],
               '%r %s' % (mm.writes, rerr))
    ok &= _arm('reset：复位后 SR 读到 Halted',
               got is not None and (got & 1) == 1, '%s' % (rerr or ('SR=%r' % got)))

    # ⑤ 没有 mmio 时要明确报错，不能静默返回 None 让人以为「正常」
    x = DmaXfer(_FakeDma([]), mmio=None)
    try:
        x.reset(settle=0.0)
        bad = False
    except DmaError:
        bad = True
    ok &= _arm('无 mmio：reset 明确报错', bad, '静默通过了')

    say('')
    if ok:
        say('【自检通过】调用顺序、超时、出错判读、复位都真的走过一遍')
        say('            ⚠️ 硬件行为**没有**验 —— 这份封装未单独上板，第一次用请先拿已知输入跑通')
    else:
        say('【自检失败】这份封装不可信，别拿它的绿当结论')
    return 0 if ok else 1


if __name__ == '__main__':
    _open_log()
    try:
        a = sys.argv[1:]
        rc = selftest() if a[:1] == ['--selftest'] else 0
        if a[:1] != ['--selftest']:
            say(__doc__)
    finally:
        if _fh is not None:
            _fh.close()
    sys.exit(rc)
