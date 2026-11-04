#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从本机的 Claude Code 会话记录里，把「大模型协作」的原始素材提取出来。

竞赛 §3.3.3.1 要求提交「体现大模型协作过程的交互记录，含提示词、模型回答与自我纠错轨迹」。
这份脚本不编任何东西 —— 它只回答一个问题：**这条线上真实发生过多少次人机交互、
跨度多长、用了哪些模型、人到底说了什么。** 后面的报告从这些真实材料里摘。

输入：  <用户主目录>/.claude/projects/<项目目录>/*.jsonl
        （默认取 ~/.claude/projects/d--study-competition-qian；换机器用 --dir 指定）
输出：  单文件报告（默认 _llm_log_extract.log，与屏幕逐字相同）

跑法：
    python build/extract_llm_log.py
    python build/extract_llm_log.py --dir <会话目录> --out <报告文件>
    python build/extract_llm_log.py --prompts-only     # 只出人话，不铺统计

⛔ 本机 stdout 是 GBK：所有输出走 UTF-8 字节直写，不用 print。
⛔ 报告每写一笔都 flush —— 802 MB 的输入，中途崩了也要留下已经跑过的那部分。
"""

import argparse
import datetime
import glob
import hashlib
import io
import json
import os
import socket
import sys
import traceback

DEFAULT_DIR = os.path.join(
    os.path.expanduser('~'), '.claude', 'projects', 'd--study-competition-qian')

# 这些是**系统注入**的东西，不是人打的字，不能算进「人的提示词」
NOISE_PREFIX = (
    '<command-name>', '<local-command', '<system-reminder>',
    '<ide_selection>', '[Request interrupted', 'Caveat: The messages below',
)

_LOG = {'path': None, 'fp': None}


def _open_log(path):
    _LOG['path'] = path
    _LOG['fp'] = io.open(path, 'w', encoding='utf-8', newline='')


def say(line=''):
    """屏幕用 UTF-8 字节直写（本机控制台是 GBK，print('⇒') 会直接崩且一个字节都不出）。"""
    s = line + '\n'
    if _LOG['fp'] is not None:
        _LOG['fp'].write(s)
        _LOG['fp'].flush()          # 每一笔都 flush：崩了也要留下已经跑过的那部分
    try:
        sys.stdout.buffer.write(s.encode('utf-8', 'replace'))
        sys.stdout.buffer.flush()
    except Exception:
        pass


def sha16(path, limit=None):
    h = hashlib.sha256()
    with io.open(path, 'rb') as f:
        n = 0
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            n += len(b)
            if limit and n >= limit:
                break
    return h.hexdigest()[:16]


def header(title, argv):
    say('=' * 92)
    say('# ' + title)
    say('#   %s   主机 %s   python %s' % (
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        socket.gethostname(), sys.version.split()[0]))
    say('#   cwd %s' % os.getcwd())
    say('#   脚本 %s  sha16 %s' % (os.path.abspath(__file__), sha16(os.path.abspath(__file__))))
    say('#   参数 %s' % (' '.join(argv) if argv else '(无)'))
    say('=' * 92)
    say('')


def blocks(msg):
    """把 message.content 统一成 block 列表。"""
    c = msg.get('content')
    if isinstance(c, str):
        return [{'type': 'text', 'text': c}]
    if isinstance(c, list):
        return [b for b in c if isinstance(b, dict)]
    return []


def is_real_prompt(msg):
    """人真的打了字 —— 排除工具结果、系统注入、空消息。"""
    bs = blocks(msg)
    if not bs:
        return None
    if any(b.get('type') == 'tool_result' for b in bs):
        return None
    texts = [b.get('text', '') for b in bs if b.get('type') == 'text']
    txt = '\n'.join(t for t in texts if t).strip()
    if not txt:
        return None
    if txt.startswith(NOISE_PREFIX):
        return None
    return txt


def _sig(b):
    """一个 block 的指纹 —— 用来在「同一条消息被落盘多次」时去重。"""
    t = b.get('type')
    if t == 'thinking':
        return ('thinking', hashlib.sha1((b.get('thinking') or '').encode('utf-8', 'replace')).hexdigest())
    if t == 'text':
        return ('text', hashlib.sha1((b.get('text') or '').encode('utf-8', 'replace')).hexdigest())
    if t == 'tool_use':
        return ('tool_use', b.get('name'), hashlib.sha1(
            json.dumps(b.get('input'), sort_keys=True, ensure_ascii=False).encode('utf-8', 'replace')).hexdigest())
    return (t, hashlib.sha1(json.dumps(b, sort_keys=True, ensure_ascii=False)
                            .encode('utf-8', 'replace')).hexdigest())


def collect(paths):
    """把 8 个会话读成「一条消息 = 一组去重后的 block」。

    ⛔ 不能简单地「按 message.id 去重后只留第一条」——
       实测（2026-11-01）一条回复的 thinking / text / tool_use 会**分成多行**落盘，
       共享同一个 message.id。按 id 丢重复会把 text 与 tool_use 全丢掉
       （第一版就是这么错的：13752 个思考块，工具调用 0 次）。
    正确做法：按 id 合并，块级去重。
    """
    msgs = {}
    order = []
    bad = lines = 0
    for p in paths:
        with io.open(p, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                lines += 1
                try:
                    d = json.loads(line)
                except Exception:
                    bad += 1
                    continue
                t = d.get('type')
                if t not in ('user', 'assistant'):
                    continue
                msg = d.get('message') or {}
                key = msg.get('id') or d.get('uuid') or ('ln', lines)
                rec = msgs.get(key)
                if rec is None:
                    rec = {'type': t, 'model': msg.get('model'), 'ts': d.get('timestamp') or '',
                           'file': os.path.basename(p), 'blocks': {}, 'order': []}
                    msgs[key] = rec
                    order.append(key)
                if msg.get('model'):
                    rec['model'] = msg.get('model')
                if d.get('timestamp') and (not rec['ts'] or d['timestamp'] < rec['ts']):
                    rec['ts'] = d['timestamp']
                for b in blocks(msg):
                    s = _sig(b)
                    if s not in rec['blocks']:
                        rec['blocks'][s] = b
                        rec['order'].append(s)
    return [msgs[k] for k in order], lines, bad


def real_prompt_of(rec):
    """这条 user 消息是不是「人真的打了字」。"""
    if rec['type'] != 'user':
        return None
    if any(k[0] == 'tool_result' for k in rec['blocks']):
        return None
    texts = [rec['blocks'][k].get('text', '') for k in rec['order'] if k[0] == 'text']
    txt = '\n'.join(t for t in texts if t).strip()
    if not txt:
        return None
    if txt.startswith(NOISE_PREFIX):
        return None
    return txt


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--dir', default=DEFAULT_DIR)
    ap.add_argument('--out', default='_llm_log_extract.log')
    ap.add_argument('--prompts-only', action='store_true')
    o, _unknown = ap.parse_known_args(argv)

    _open_log(o.out)
    header('大模型协作原始素材提取', argv)

    paths = sorted(glob.glob(os.path.join(o.dir, '*.jsonl')))
    if not paths:
        say('[红] %s 下没有 .jsonl' % o.dir)
        return 1

    say('会话文件 %d 个：' % len(paths))
    total_bytes = 0
    for p in paths:
        n = os.path.getsize(p)
        total_bytes += n
        say('  %-42s %10.1f MB' % (os.path.basename(p), n / 1048576.0))
    say('  合计 %.1f MB' % (total_bytes / 1048576.0))
    say('')

    per_file = {}
    models = {}
    n_user = n_asst = n_think = n_tool = n_text = 0
    prompts = []
    t_min = t_max = None
    tool_names = {}

    recs, nlines, bad = collect(paths)

    for rec in recs:
        ts = rec['ts']
        if ts:
            if t_min is None or ts < t_min:
                t_min = ts
            if t_max is None or ts > t_max:
                t_max = ts
        st = per_file.setdefault(rec['file'],
                                 {'user': 0, 'asst': 0, 'first': ts, 'last': ts})
        if ts:
            if not st['first'] or ts < st['first']:
                st['first'] = ts
            if not st['last'] or ts > st['last']:
                st['last'] = ts

        if rec['type'] == 'user':
            txt = real_prompt_of(rec)
            if txt:
                n_user += 1
                st['user'] += 1
                prompts.append((ts, txt))
        else:
            n_asst += 1
            st['asst'] += 1
            m = rec['model']
            if m:
                models[m] = models.get(m, 0) + 1
            for k in rec['order']:
                if k[0] == 'thinking':
                    n_think += 1
                elif k[0] == 'text':
                    n_text += 1
                elif k[0] == 'tool_use':
                    n_tool += 1
                    tool_names[k[1]] = tool_names.get(k[1], 0) + 1
    dup = 0

    if not o.prompts_only:
        say('─' * 92)
        say('【一】规模')
        say('  人的提示词      %6d 条' % n_user)
        say('  模型回复        %6d 条' % n_asst)
        say('  其中思考块      %6d 个' % n_think)
        say('  其中正文块      %6d 个' % n_text)
        say('  工具调用        %6d 次' % n_tool)
        say('  jsonl 总行数    %6d 行（已按 message.id 合并、块级去重）' % nlines)
        if bad:
            say('  [黄] 有 %d 行不是合法 JSON，已跳过（不截断，只计数）' % bad)
        say('')
        if tool_names:
            say('  工具用得最多的前 15 个：')
            for k, v in sorted(tool_names.items(), key=lambda kv: -kv[1])[:15]:
                say('    %-34s %6d 次' % (k, v))
            say('')
        say('  时间跨度  %s  →  %s' % ((t_min or '?')[:19], (t_max or '?')[:19]))
        say('')

        say('─' * 92)
        say('【二】用过的模型')
        if models:
            for m, c in sorted(models.items(), key=lambda kv: -kv[1]):
                say('  %-40s %6d 条' % (m, c))
        else:
            say('  （记录里没有 model 字段）')
        say('')

        say('─' * 92)
        say('【三】按会话文件')
        say('  %-42s %6s %6s  %s' % ('文件', '人话', '模型', '起止'))
        for k, v in sorted(per_file.items()):
            say('  %-42s %6d %6d  %s → %s' % (
                k, v['user'], v['asst'],
                (v['first'] or '?')[:16], (v['last'] or '?')[:16]))
        say('')

    say('─' * 92)
    say('【四】人的提示词全文（%d 条，按时间）' % len(prompts))
    say('')
    prompts.sort(key=lambda x: x[0] or '')
    for i, (ts, txt) in enumerate(prompts, 1):
        say('[P%04d] %s' % (i, (ts or '?')[:19]))
        for ln in txt.splitlines():
            say('        ' + ln)
        say('')

    say('=' * 92)
    say('结束：%d 条提示词、%d 条模型回复' % (n_user, n_asst))
    say('# 报告：%s' % os.path.abspath(o.out))
    return 0


if __name__ == '__main__':
    try:
        rc = main(sys.argv[1:])
    except Exception:
        say('')
        say('[红] 脚本抛异常 —— 全文如下，不截断：')
        say(traceback.format_exc())
        rc = 1
    finally:
        if _LOG['fp'] is not None:
            _LOG['fp'].close()
    sys.exit(rc)
