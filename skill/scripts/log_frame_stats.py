#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""log_frame_stats.py —— 从 JSONL 日志里算【真实帧率】与丢帧率

适用场景
    程序把每帧记录成一行 JSON（本项目、以及大多数自建采集/推理程序都是这样），
    你想知道"实际出了多少帧、丢了多少、慢在哪"，而不是靠 `1000/耗时` 去折算。

为什么不能自己拍脑袋算
    · 帧率 = 帧数 ÷ 墙钟，**不是 1000/中位数**（会高估 15~20%）
    · 采样日志通常每 N 帧才记一条 ⇒ 周期要 Δt/N，不是 Δt
    · 帧率由**均值和长尾**决定，中位数只代表"典型帧"

用法
    python3 log_frame_stats.py run.log
    python3 log_frame_stats.py run.log \\
        --seq camera_sequence --time capture_ready_at \\
        --only state=CURRENT --sample 4 --segment-gap 0.5

    # 没有序号字段（相机/上游不提供）时，只能看周期：
    python3 log_frame_stats.py run.log --seq none

输出
    每个会话一行；末尾给全局汇总。退出码恒为 0（这是分析工具，不是检查器）。

失效条件
    · 日志不是 JSONL（一行一个对象）
    · 记录的字段名与 --seq/--time 不符 —— 先跑一次 print_keys() 看看
    · 采样比不是常数（有的帧记有的不记）⇒ --sample 会失效，见输出的提示
"""
import argparse
import json
import re
import sys
try:                       # Windows 控制台默认 GBK，遇到 ⚠️ 之类会 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from collections import Counter, defaultdict

Q = lambda v, p: (lambda s: s[min(int((len(s) - 1) * p), len(s) - 1)])(sorted(v)) if v else float('nan')


def percentile(v, p):
    """线性插值分位数；比 nearest 更稳，和 numpy 默认一致。"""
    if not v:
        return float('nan')
    s = sorted(v)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def load(path, only):
    """读 JSONL，按 '字段=值' 过滤。解析不了的行跳过并计数。"""
    rows, bad = [], 0
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line.startswith('{'):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if only:
                k, _, v = only.partition('=')
                if str(d.get(k)) != v:
                    continue
            rows.append(d)
    return rows, bad


def infer_sample(rows, key, seq):
    """从主键步长推断日志采样比（每 N 帧记一条）。"""
    if key not in rows[0] or len(rows) < 3:
        return 1
    idx = [r[key] for r in rows if key in r]
    steps = [b - a for a, b in zip(idx, idx[1:]) if b > a]
    if not steps:
        return 1
    c = Counter(steps).most_common(1)[0][0]
    return c if isinstance(c, int) and c >= 1 else 1


def segments(rows, time_key, gap):
    """按时间间隙切会话（程序重启、场景切换都会造成大间隙）。"""
    rows = [r for r in rows if time_key in r]
    if not rows:
        return []
    segs, cur = [], [rows[0]]
    for a, b in zip(rows, rows[1:]):
        if b[time_key] - a[time_key] > gap:
            segs.append(cur)
            cur = []
        cur.append(b)
    segs.append(cur)
    return segs


def main():
    ap = argparse.ArgumentParser(description='从 JSONL 日志算真实帧率与丢帧率')
    ap.add_argument('log')
    ap.add_argument('--time', default='capture_ready_at', help='单调时间戳字段（秒）')
    ap.add_argument('--seq', default='camera_sequence',
                    help='上游序号字段；没有就写 none')
    ap.add_argument('--key', default='index', help='单调递增主键，用于推断采样比')
    ap.add_argument('--only', default=None, help="只统计满足条件的行，如 state=CURRENT")
    ap.add_argument('--sample', type=int, default=0, help='日志采样比；0=自动推断')
    ap.add_argument('--segment-gap', type=float, default=0.5, help='切会话的时间间隙（秒）')
    ap.add_argument('--cost', default='service_s', help='单帧耗时字段；none=不算')
    args = ap.parse_args()

    rows, bad = load(args.log, args.only)
    if not rows:
        print('没有可解析的记录；先用 --only 去掉过滤，或检查字段名')
        return 0
    print(f'记录 {len(rows)} 条' + (f'（跳过 {bad} 条坏行）' if bad else ''))

    sample = args.sample or infer_sample(rows, args.key, args.seq)
    if sample > 1:
        print(f'采样比 {sample}（每 {sample} 帧记一条）—— 周期与 step 都要除以它')

    hdr = (f"{'会话':>4}{'记录':>6}{'帧':>7}{'上游fps':>9}{'本机fps':>9}"
           f"{'周期ms':>8}{'丢帧率':>8}{'每帧跳':>7}")
    print()
    print(hdr)
    print('-' * len(hdr))

    tot_frames = tot_span = 0
    allcost = []
    for i, seg in enumerate(segments(rows, args.time, args.segment_gap)):
        if len(seg) < 3:
            continue
        t = [r[args.time] for r in seg]
        span = t[-1] - t[0]
        nf = (len(seg) - 1) * sample
        if span <= 0 or nf <= 0:
            continue
        fps = nf / span
        cfps = float('nan')
        step = float('nan')
        drop = float('nan')
        if args.seq != 'none' and args.seq in seg[0]:
            dseq = seg[-1][args.seq] - seg[0][args.seq]
            if dseq > 0:
                cfps = dseq / span
                step = dseq / nf
                drop = (1 - nf / dseq) * 100
        if args.cost != 'none':
            allcost += [r[args.cost] * 1000 for r in seg if args.cost in r]
        tot_frames += nf
        tot_span += span
        print(f'{i:>4}{len(seg):>6}{nf:>7}{cfps:>9.2f}{fps:>9.2f}'
              f'{span / nf * 1000:>8.1f}{drop:>7.1f}%{step:>7.2f}')

    print()
    if tot_span > 0:
        print(f'全局：{tot_frames} 帧 / {tot_span:.1f} s = {tot_frames / tot_span:.2f} fps')
    if allcost:
        print(f'单帧耗时 ms：中位 {percentile(allcost, .5):.1f}  均值 {sum(allcost) / len(allcost):.1f}  '
              f'p90 {percentile(allcost, .9):.1f}  p99 {percentile(allcost, .99):.1f}')
        print('  ⚠️ 帧率不取 1/中位；看"均值 + p90"，再看与周期差多少')
    if sample > 1:
        print(f'  ⚠️ 本日志每 {sample} 帧记一条，已按此换算；若采样比不是常数，结果偏小')
    return 0


if __name__ == '__main__':
    sys.exit(main())
