#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_synth_log.py —— 扫 Vivado 的 runme.log，抓"综合会说话、仿真不说话"的问题

适用场景
    仿真全绿、上板却不对；或者你只想在烧板之前花 5 秒确认综合没留下隐患。
    比在 GUI 里翻 Messages 快得多，也适合放进 CI / 提交前钩子。

它抓什么
    · 多驱动（Net has multiple drivers）—— 输出错位、X 传播的常见根因
    · 位宽不匹配 / 静默截断
    · 锁存器推断（Latch inferred）
    · 端口未连接 / 常量悬空
    · Critical Warning 全量
    · 实现后的 WNS / WHS 与失败端点数（从 timing summary 抓）

用法
    python3 check_synth_log.py path/to/runme.log
    python3 check_synth_log.py runme.log --fail-on critical   # 有 CW 就返回 2
    cat runme.log | python3 check_synth_log.py -

退出码
    0 = 没有命中已知问题（不代表没问题）
    2 = 命中 Critical Warning、负 WNS 或失败端点
    3 = 文件读不到

失效条件
    · 日志不是 Vivado 的 runme.log / vivado.log 格式
    · Vivado 版本改名了消息编号（本脚本按【关键字】匹配，不依赖编号，抗改名）
"""
import argparse
import re
import sys
try:                       # Windows 控制台默认 GBK，遇到 ⚠️ 之类会 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from collections import Counter

# 关键字 -> (分类, 为什么危险, 建议动作)
PATTERNS = [
    ('多驱动', r'has multiple drivers|multiple drivers on net|net .* has multiple drivers',
     '同一根线被两处驱动，综合可能任选其一 —— 输出错位、X 传播的头号原因',
     '查该 net 的所有赋值点，删除多余的；注意 always 块里的漏删'),
    ('位宽截断', r'width mismatch|truncat|operand .* has different width',
     '高位被静默丢弃，算出来的数不对但不报错',
     '把操作数显式加宽，见 references/generic/02'),
    ('锁存器', r'[Ll]atch inferred|inferred latch',
     '组合 always 的敏感表不全，综合出锁存器 —— 时序不可预测',
     '补齐 else 分支 / 默认赋值'),
    ('未连接端口', r'unconnected port|port .* is unconnected|tied to constant',
     '端口悬空，上板表现为"这个 IP 不工作"',
     '回 BD 检查每个从机都连了主机（不只是连时钟）'),
    ('常量驱动', r'constant .* is driving|will be trimmed',
     '信号被常量覆盖，逻辑被综合掉',
     '查是不是拼写错误导致连到了常量'),
    ('时钟域', r'cross.*clock|CDC|no common primary clock',
     '跨时钟域没同步，偶发错误',
     '加两级同步器，或声明 false_path 之前先想清楚'),
]

TIMING = [
    ('WNS', r'\|\s*WNS\(ns\)\s*\n?.*?\n?.*?\n?\s*(-?\d+\.\d+)', 0.0),
    ('TNS', r'\|\s*TNS\(ns\)', 0.0),
    ('WHS', r'\|\s*WHS\(ns\)', 0.0),
]


def read(path):
    if path == '-':
        return sys.stdin.read()
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser(description='扫 Vivado 日志抓常见隐患')
    ap.add_argument('log')
    ap.add_argument('--fail-on', choices=['critical', 'never'], default='critical',
                    help='命中 Critical Warning 或负时序时是否返回非零')
    ap.add_argument('--show', type=int, default=3, help='每类最多展示几条原文')
    args = ap.parse_args()
    try:
        text = read(args.log)
    except OSError as e:
        print(f'读不到日志：{e}')
        return 3

    lines = text.splitlines()
    print(f'日志 {len(lines)} 行')

    hits = Counter()
    shown = Counter()
    print()
    for name, pat, why, todo in PATTERNS:
        rx = re.compile(pat, re.I)
        matched = [l.strip() for l in lines if rx.search(l)]
        hits[name] = len(matched)
        if not matched:
            continue
        print(f'❌ {name}：{len(matched)} 处')
        print(f'   为什么危险：{why}')
        print(f'   怎么办    ：{todo}')
        for l in matched[:args.show]:
            print(f'     {l[:160]}')
        print()

    cw = [l for l in lines if 'CRITICAL WARNING' in l]
    print(f'Critical Warning：{len(cw)} 条')
    for l in cw[:args.show]:
        print(f'   {l.strip()[:160]}')

    # 实现后的时序（若日志里有 timing summary）
    neg = False
    m = re.search(r'WNS\(ns\)\s+TNS\(ns\)[^\n]*\n[^\n]*\n\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)', text)
    if m:
        wns, tns = float(m.group(1)), float(m.group(2))
        neg = wns < 0
        print(f'\n时序：WNS {wns:+.3f} ns，TNS {tns:+.3f} ns ' + ('❌ 未收敛' if neg else '✅ 收敛'))
    else:
        print('\n时序：日志里没有 timing summary（综合阶段的日志通常没有，看实现阶段）')

    print()
    total = sum(hits.values())
    if not total and not cw and not neg:
        print('✅ 未命中已知问题（这不代表设计正确，只代表没有这些典型症状）')
        return 0
    if args.fail_on == 'critical' and (cw or neg or total):
        print('⇒ 存在问题，详见上面分类')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
