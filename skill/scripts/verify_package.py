#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_package.py —— 交付包完整性自检：清单 ↔ 目录 ↔ ZIP 三方一致

适用场景
    把工程/程序打成压缩包发给别人，对方那边"装不上"或"跑起来不对"。
    90% 的原因是**清单、目录、压缩包三者的文件集或哈希对不上**，
    而错误信息往往只说其中一处，改了一处又断另一处。

它查什么
    1. 清单里列出的每个文件，在目标里存不存在、哈希对不对
    2. 目标里有没有**清单之外**的多余文件（多一个也会让严格安装器拒绝）
    3. 目录与 ZIP 的文件集是否一致

用法
    # 校验一个目录
    python3 verify_package.py --dir ./software --manifest manifest.json

    # 校验一个 zip（读内部清单）
    python3 verify_package.py --zip package.zip --member-root pkg/

    # 只列文件集、不做哈希（快）
    python3 verify_package.py --dir ./software --manifest manifest.json --no-hash

清单格式（两种都支持）
    {"a.py": "sha256..."}                       # 简单映射
    {"sha256": {"a.py": "sha256..."}, ...}      # 带包了一层（common）

退出码
    0 = 完全一致    1 = 有缺失/不符/多余    3 = 参数或文件问题

失效条件
    · 清单不是"路径 -> sha256"这种结构 —— 用 --dump-keys 先看看它长什么样
"""
import argparse
import hashlib
import json
import os
import sys
try:                       # Windows 控制台默认 GBK，遇到 ⚠️ 之类会 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import zipfile

CHUNK = 1 << 20


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(CHUNK), b''):
            h.update(c)
    return h.hexdigest()


def normalise(man):
    """把两种清单格式都归一成 {相对路径: sha256}。"""
    if not isinstance(man, dict):
        raise ValueError('清单不是 JSON 对象')
    if 'sha256' in man and isinstance(man['sha256'], dict):
        man = man['sha256']
    out = {}
    for k, v in man.items():
        if isinstance(v, str):
            out[k] = v
        elif isinstance(v, dict) and 'sha256' in v:
            out[k] = v['sha256']
        else:
            raise ValueError(f'清单项格式不认识：{k} -> {type(v).__name__}')
    return out


def walk(root):
    got = set()
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in ('.git', '__pycache__', '.Xil', '.vivado-ai')]
        for f in fn:
            got.add(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, '/'))
    return got


def report(missing, bad, extra, checked):
    print(f'清单 {len(checked)} 项')
    for title, items in (('缺失', missing), ('哈希不符', bad), ('清单外多余', extra)):
        if items:
            print(f'❌ {title} {len(items)} 项：')
            for x in items[:20]:
                print('   ', x)
            if len(items) > 20:
                print(f'    ...还有 {len(items) - 20} 项')
        else:
            print(f'✅ {title} 0 项')
    return 0 if not (missing or bad or extra) else 1


def main():
    ap = argparse.ArgumentParser(description='交付包完整性自检')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--dir', help='要校验的目录')
    src.add_argument('--zip', help='要校验的 zip')
    ap.add_argument('--manifest', default='release_manifest.json',
                    help='清单路径（--dir 时相对 --dir；--zip 时用 --member-root 拼）')
    ap.add_argument('--member-root', default='', help='zip 内的根目录前缀，如 pkg/')
    ap.add_argument('--no-hash', action='store_true', help='只比文件集，不算哈希')
    ap.add_argument('--dump-keys', action='store_true', help='打印清单的顶层键后退出')
    args = ap.parse_args()

    try:
        if args.dir:
            mpath = os.path.join(args.dir, args.manifest) if not os.path.isabs(args.manifest) else args.manifest
            man = json.load(open(mpath, encoding='utf-8'))
            if args.dump_keys:
                print(list(man)[:30]); return 0
            expect = normalise(man)
            got = walk(args.dir)
            missing = sorted(set(expect) - got)
            extra = sorted(got - set(expect))
            bad = []
            if not args.no_hash:
                for rel in sorted(set(expect) & got):
                    if sha_file(os.path.join(args.dir, rel.replace('/', os.sep))) != expect[rel]:
                        bad.append(rel)
            return report(missing, bad, extra, expect)

        z = zipfile.ZipFile(args.zip)
        names = [n for n in z.namelist() if not n.endswith('/')]
        root = args.member_root
        inner = root + args.manifest if root else args.manifest
        if inner not in names:
            print(f'❌ zip 里没有 {inner}')
            return 3
        man = json.loads(z.read(inner))
        if args.dump_keys:
            print(list(man)[:30]); return 0
        expect = normalise(man)
        prefix = root if root else (inner.rsplit('/', 1)[0] + '/' if '/' in inner else '')
        got = set()
        for n in names:
            if prefix and not n.startswith(prefix):
                continue
            rel = n[len(prefix):]
            if rel and rel != args.manifest:
                got.add(rel)
        missing = sorted(set(expect) - got)
        extra = sorted(got - set(expect))
        bad = []
        if not args.no_hash:
            for rel in sorted(set(expect) & got):
                if sha_bytes(z.read(prefix + rel)) != expect[rel]:
                    bad.append(rel)
        return report(missing, bad, extra, expect)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        print(f'❌ {type(e).__name__}: {e}')
        return 3


if __name__ == '__main__':
    sys.exit(main())
