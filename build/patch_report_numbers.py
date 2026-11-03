# -*- coding: utf-8 -*-
"""把 design_report.pdf 第 27 页的三个陈旧数字改成实测值。

  115  -> 114      （删除 ai_selftest/5094.png 后，发布目录少一个文件）
  26.5 -> 26.2 MB  （同上，26,224,111 B）
  10   -> 9        （v99_ai_selftest.json 的 cases 只有 9 条；1108.png 是未登记的孤儿图）

只改字符本身，不动版式：把旧字形 redact 掉，用同度量字体 Times New Roman 在原 origin 重写。
输出**副本** design_report_fixed.pdf，原件一个字节不碰。
自产单文件报告 build/reports/report_number_patch.txt。

⚠️ PyMuPDF 保存**不保证逐字节可复现**：同一输入重跑，页内容与体量一致但 sha256 会变。
   所以对外登记的 sha256 必须取**实际安装的那份**的现算值，不要照抄本报告的运行结果。
"""
import hashlib
import io
import os
import re
import sys

import pymupdf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'report', 'design_report.pdf')
DST = os.path.join(ROOT, 'report', 'design_report_fixed.pdf')
PNG = os.path.join(ROOT, 'build', 'reports', 'p27_preview.png')
REPORT = os.path.join(ROOT, 'build', 'reports', 'report_number_patch.txt')

_lines = []


def say(msg=''):
    _lines.append(msg)
    print(msg)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'a', encoding='utf-8', newline='\n') as f:
        f.write(msg + '\n')
        f.flush()


def main():
    if os.path.exists(REPORT):
        os.remove(REPORT)
    import time
    say('=' * 72)
    say('设计报告 PDF 数字修订')
    say('=' * 72)
    say('时间   : %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    say('源文件 : %s' % SRC)
    say('原件   : %d 字节' % os.path.getsize(SRC))
    say('')

    doc = pymupdf.open(SRC)
    page = doc[26]

    before = page.get_text()
    # 幂等保护：源里要是已经没有旧数字，说明它已经是修订版（或备份被覆盖），
    # 再跑一遍会 produce 一份"改了但又没改"的坏产物。
    if '26.5 MB' not in before and '115' not in before:
        doc.close()
        raise SystemExit('⛔ 源文件里已经没有旧数字了，它已是修订版。\n'
                         '   要重跑请先从 report/_backup/ 恢复原件')

    checks_before = {
        '共115 个文件': '共115 个文件' in before.replace(' ', ' '),
        '26.5 MB': '26.5 MB' in before,
        '包内10 条用例图': '10 条用例图' in before,
    }
    say('[1] 改前检查（原文是否含旧数字）')
    for k, v in checks_before.items():
        say('    %-22s %s' % (k, '命中' if v else '⚠ 未命中'))

    # ---- 三处补丁：(红action矩形, 新文本, 插入原点) ----
    # 整词替换：只改单个字符会让内容流里出现"半个 token"，文本层拼不回来。
    patches = [
        (pymupdf.Rect(452.04, 156.54, 469.56, 172.68), '114', (452.04, 169.009), '115 -> 114'),
        (pymupdf.Rect(114.00, 179.94, 156.67, 196.08), '26.2 MB', (114.00, 192.409), '26.5 -> 26.2 MB'),
        (pymupdf.Rect(426.00, 371.10, 438.00, 387.24), '9', (429.00, 383.569), '10 -> 9'),
    ]

    say('')
    say('[2] 打补丁')
    for rect, text, origin, label in patches:
        page.add_redact_annot(rect)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    # 必须嵌 TrueType：base-14 没有 ToUnicode，写字看得见但提取不到
    TIMES = 'C:/Windows/Fonts/times.ttf'
    if not os.path.exists(TIMES):
        raise SystemExit('找不到 Times New Roman: ' + TIMES)
    page.insert_font(fontname='TNR', fontfile=TIMES)
    for rect, text, origin, label in patches:
        page.insert_text(origin, text, fontname='TNR', fontsize=12,
                         color=(0, 0, 0), render_mode=0)
        say('    %-16s -> 写入 %r @ (%.2f, %.3f)' % (label, text, origin[0], origin[1]))

    doc.subset_fonts()          # 不 subset 会把整个 times.ttf 塞进去（+674 KB）
    doc.save(DST, garbage=3, deflate=True)
    doc.close()
    # subset_fonts() 会在文档同目录留下 MuPDF 的临时文件 _tmp_subset.pdf，别让它混进 report/
    for tmp in (os.path.join(os.path.dirname(SRC), '_tmp_subset.pdf'),
                os.path.join(os.path.dirname(DST), '_tmp_subset.pdf')):
        if os.path.exists(tmp):
            os.remove(tmp)

    # ---- 复核 ----
    say('')
    say('[3] 复核（重新打开产物）')
    d2 = pymupdf.open(DST)
    # 用 sort=True：红action 后重写的字落在内容流末尾，原序抽取会把 token 拆散
    after = d2[26].get_text(sort=True)
    say('    页数 %d（原 30）' % d2.page_count)
    ok = True
    # 去掉全部空白再比：PDF 里 "114 个文" 会跨行断成 "114 个文\n件"，
    # 只查子串 '114' 是空转门禁（文档里到处都可能出现 114）。
    flat = re.sub(r'\s+', '', after)
    for label, cond in [
        ('新 114 个文件在文中', '114个文件' in flat),
        ('旧 115 个文件已消失', '115个文件' not in flat),
        ('新 26.2MB 在文中', '26.2MB' in flat),
        ('旧 26.5MB 已消失', '26.5MB' not in flat),
        ('新 9 条用例图在文中', '9条用例图' in flat),
        ('旧 10 条用例图已消失', '10条用例图' not in flat),
    ]:
        say('    %-22s %s' % (label, '✓' if cond else '✗'))
        ok = ok and cond

    # 全文档逐页比对：除第 27 页外，正文必须逐字不变
    say('')
    say('[3b] 全文档逐页比对')
    d0 = pymupdf.open(SRC)
    diff_pages = []
    for i in range(min(d0.page_count, d2.page_count)):
        if d0[i].get_text(sort=True) != d2[i].get_text(sort=True):
            diff_pages.append(i + 1)
    d0.close()
    say('    文本有差异的页: %s' % (diff_pages or '无'))
    if diff_pages != [27]:
        ok = False
        say('    ⛔ 预期只有第 27 页变化')
    else:
        say('    ✓ 只有第 27 页变化')

    pix = d2[26].get_pixmap(dpi=150)
    pix.save(PNG)
    d2.close()
    say('')
    say('    第 27 页预览图: %s (%d 字节)' % (PNG, os.path.getsize(PNG)))
    with open(DST, 'rb') as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    say('    产物: %s (%d 字节)' % (DST, os.path.getsize(DST)))
    say('    sha256: %s' % sha)
    say('')
    say('总体: %s' % ('PASS' if ok else 'FAIL'))
    if not ok:
        say('  ⛔ 不要用这个产物，先人工看预览图')


if __name__ == '__main__':
    main()
