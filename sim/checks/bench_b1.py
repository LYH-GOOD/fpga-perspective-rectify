"""bench_b1.py —— B1 实验：零访存（我们）vs 落 DDR（参考实现）

在 PYNQ 上跑（Jupyter 里 `%run bench_b1.py`），约 30 秒出结果。

它做两件事：
  ① 编译并运行 bench_mem.cpp —— **只改访问模式**，同样的字节数、同一块内存，
     测顺序读 vs 双线性 4 邻域随机取数的差别（把"架构"从"CPU 快慢"里剥离）
  ② 用 OpenCV 的 cv2.remap 在本板 PS 上做**同样的重映射**（典型"落 DDR"实现），
     量出端到端 ms —— 这是"如果重映射留在 PS 上要多久"的实测值

⚠️ 口径说明（写报告时必须带上）：
  · ② 的 cv2.remap 读的是一整帧 BGR（落在 DDR），每个输出像素随机取 4 邻域；
    我们的 PL 核则是流式：每个输入字节读 1 次、每个输出字节写 1 次。
  · ② 在 PS 上跑 ⇒ CPU 有 L2 缓存帮忙，对"落 DDR"是**偏乐观**的。
  · 我们的 PL 走 DMA，是 uncached。
"""
import os
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np

for _s in (sys.stdout, sys.stderr):          # Windows 控制台默认 GBK，符号会崩在 print 上
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
IW, IH = 640, 480
OW, OH = 362, 512
REP = 7


def run_native():
    src = os.path.join(HERE, 'bench_mem.cpp')
    if not os.path.isfile(src):
        print('  [跳过] 找不到 bench_mem.cpp（请与本脚本放在同一目录）')
        return None
    exe = os.path.join('/tmp', 'bench_mem')
    cc = shutil.which('g++') or shutil.which('gcc')
    if cc is None:
        print('  [跳过] 没有 g++')
        return None
    r = subprocess.run([cc, '-O3', '-std=c++11', '-o', exe, src], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        print('  编译失败：', r.stderr[-400:])
        return None
    r = subprocess.run([exe, str(REP)], capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(r.stdout)
    return r.stdout


def bench_ps_remap():
    # 造一帧 YUYV（真机上换成相机那一帧；纯访存基准对内容不敏感）
    n = np.arange(IH * IW, dtype=np.int64)
    yuyv = np.empty((IH, IW, 2), np.uint8)
    yuyv[:, :, 0] = ((n * 37 + 11) & 0xFF).astype(np.uint8).reshape(IH, IW)
    yuyv[:, :, 1] = ((n * 53 + 200) & 0xFF).astype(np.uint8).reshape(IH, IW)

    # 预先把 map 算好（不计入重映射本身的时间）
    v, u = np.mgrid[0:OH, 0:OW].astype(np.float32)
    mapx = (u * 1.05 + v * 0.06 + 30.0).astype(np.float32)
    mapy = (u * 0.02 + v * 1.06 + 40.0).astype(np.float32)

    t = time.perf_counter()
    for _ in range(REP):
        bgr = cv2.cvtColor(yuyv, cv2.COLOR_YUV2BGR_YUY2)
    cvt_ms = (time.perf_counter() - t) / REP * 1e3

    bgr = cv2.cvtColor(yuyv, cv2.COLOR_YUV2BGR_YUY2)
    best = 1e9
    for _ in range(REP):
        t = time.perf_counter()
        out = cv2.remap(bgr, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        best = min(best, time.perf_counter() - t)
    remap_ms = best * 1e3

    print('  PS 参考实现（落 DDR）：')
    print('    cvtColor YUYV->BGR   %7.2f ms' % cvt_ms)
    print('    cv2.remap 双线性      %7.2f ms   <- 每个输出像素随机取 4 邻域' % remap_ms)
    print('    合计                  %7.2f ms/帧   (%.1f fps)' % (cvt_ms + remap_ms, 1e3 / (cvt_ms + remap_ms)))
    print('    而且这 %.1f ms 要占用 PS —— 和跟踪是【串行】的' % (cvt_ms + remap_ms))
    return cvt_ms + remap_ms


def main():
    print('=' * 70)
    print(' B1：零访存（流式 PL）vs 落 DDR（PS/OpenCV 参考实现）')
    print('=' * 70)
    print('\n[1] 访存模式微基准（同样的字节数，只改访问模式）')
    run_native()
    print('[2] PS 参考实现（cv2.remap，落 DDR）')
    total = bench_ps_remap()
    print('\n[3] 我们的实测（上板日志，static_hold p50）')
    print('    PL 核整帧 dma_wait      21.9 ms   <- 读输入 + 写输出 + 插值算术，全程片上')
    print('    系统 service            42.4 ms/帧')
    print('    PL 的重映射与 PS 的跟踪（26.9 ms）是【并行】的')
    print('\n结论口径：见 report/llm_log 的 B1 记录')


if __name__ == '__main__':
    main()
