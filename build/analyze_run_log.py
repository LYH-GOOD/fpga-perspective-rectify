#!/usr/bin/env python3
"""读板上 run-result.log，出一份只读分析报告（不改任何东西）。

    python build/analyze_run_log.py <run-result.log 路径>

判据（照 memory 里定过的口径，别再自己发明）：
  * 帧率**只认** HDMI_PROGRESS.frames 的斜率，并在 frames 回退处切段；
    V64_FRAME / current_fps / hdmi_submit_fps / hdmi_panel_fps 都不是帧率口径。
  * 每条 V64_FRAME 是抽稀过的（日志口 "逐帧日志：每 N 帧记一条"），
    所以「条数」不等于「帧数」—— 别拿 1789 条当 1789 帧。
  * 文档里出现过的坑：分位/均值只能用均值闭合账本。
"""
import collections
import datetime as dt
import json
import sys
import traceback
from pathlib import Path

REPORT = Path(__file__).resolve().parent / "reports" / "analyze_run_log_report.txt"
OUT = None


def log(line=""):
    text = str(line) + "\n"
    if OUT is not None:
        OUT.write(text)
        OUT.flush()


def ts(r):
    return dt.datetime.fromisoformat(r["time"]).timestamp()


def main():
    global OUT
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("run-result.log")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT = open(REPORT, "w", encoding="utf-8", newline="\n")
    try:
        rows, bad = [], 0
        for ln in src.open(encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:
                bad += 1
        #  板端 run-result.log 是**追加制**：同一个文件里可能装着好几次运行。
        #  不切段的话，会话表 / 阶段条数 / 异常数的分母全跨轮混算（2026-11-02 实踩）。
        total = len(rows)
        starts = [i for i, r in enumerate(rows) if r.get("stage") == "RUN_BEGIN"]
        log(f"日志 : {src}  {src.stat().st_size:,} B")
        log(f"记录 : {total} 条 JSONL，无法解析 {bad} 行")
        if not rows:
            log("RESULT: FAIL 没有任何可解析记录")
            return 1
        if len(starts) > 1:
            rows = rows[starts[-1]:]
            log(f"       ⚠ 文件含 {len(starts)} 次运行（追加制）；只分析**最后一次**，"
                f"{len(rows)} 条，其余 {starts[-1]} 条已跳过")
        log(f"时间 : {rows[0]['time']} → {rows[-1]['time']}")
        log("")

        # ---------- 1. 生命周期 ----------
        first, last = rows[0], rows[-1]
        log("=" * 72)
        log("1. 生命周期")
        log("=" * 72)
        for r in rows:
            if r.get("stage") in ("RUN_BEGIN", "RUN_COMPLETED", "RUN_ABORTED", "RUN_FAILED"):
                log(f"  {r['time']}  {r['stage']}  "
                    + json.dumps({k: v for k, v in r.items()
                                  if k not in ("time", "stage")}, ensure_ascii=False)[:400])
        log("")
        log("  阶段条数 Top20:")
        for k, v in collections.Counter(r.get("stage") for r in rows).most_common(20):
            log(f"    {v:>6}  {k}")
        log("")

        # ---------- 1b. 关键事件时间线 ----------
        log("=" * 72)
        log("1b. 关键事件时间线（相对首条记录，秒）")
        log("=" * 72)
        t0 = ts(rows[0])
        want = {"UI_TOUCH_PRESS_ACTION", "UI_MODE_REQUEST", "UI_NAVIGATION_BEGIN",
                "UI_SESSION_BEGIN", "UI_SESSION_END", "UI_CAMERA_RETURN",
                "CAMERA_STABILITY_BEGIN", "CAMERA_STABILITY_FAILED", "UNIFIED_AUTO_ACCEPTED",
                "RECOVERY_TRIGGER", "RECOVERY_TRANSITION", "AI_INIT_FAILED", "AI_LIVE_BOUNDARY",
                "DISPLAY_CONTINUITY_BEGIN", "DISPLAY_CONTINUITY_END"}
        for r in rows:
            if r.get("stage") not in want:
                continue
            d = {k: v for k, v in r.items() if k not in ("time", "stage")}
            log(f"  {ts(r) - t0:7.2f}s {r['stage']:<32} {json.dumps(d, ensure_ascii=False)[:220]}")
        log("")

        # ---------- 2. 帧率 ----------
        log("=" * 72)
        log("2. 帧率（唯一口径：HDMI_PROGRESS.frames 斜率，回退处切段）")
        log("=" * 72)
        hp = [r for r in rows if r.get("stage") == "HDMI_PROGRESS" and "frames" in r]
        if len(hp) >= 2:
            segs, cur = [], [hp[0]]
            for prev, r in zip(hp, hp[1:]):
                if r["frames"] < prev["frames"]:
                    segs.append(cur)
                    cur = []
                cur.append(r)
            segs.append(cur)
            for i, s in enumerate(segs, 1):
                d = s[-1]["frames"] - s[0]["frames"]
                e = ts(s[-1]) - ts(s[0])
                log(f"  段{i}: frames {s[0]['frames']} -> {s[-1]['frames']}  "
                    f"帧数 {d}  时长 {e:.2f}s  =>  {(d / e if e > 0 else 0):.2f} fps")
            tot_d = sum(s[-1]["frames"] - s[0]["frames"] for s in segs)
            tot_e = sum(ts(s[-1]) - ts(s[0]) for s in segs)
            log(f"  合计: {tot_d} 帧 / {tot_e:.2f}s => {tot_d / tot_e:.2f} fps")
            log("  最后 8 条 HDMI_PROGRESS 详细字段:")
            for r in hp[-8:]:
                log("    " + json.dumps({k: v for k, v in r.items()
                                          if k != "stage"}, ensure_ascii=False)[:400])
        else:
            log("  HDMI_PROGRESS 记录不足，无法算斜率")
        log("")

        # ---------- 3. 帧明细 ----------
        log("=" * 72)
        log("3. V64_FRAME 明细（注意：这是抽稀日志，条数≠帧数）")
        log("=" * 72)
        fr = [r for r in rows if r.get("stage") == "V64_FRAME"]
        log(f"  条数 {len(fr)}；首条 {fr[0]['time']}，末条 {fr[-1]['time']}" if fr else "  无")
        if fr:
            keys = collections.Counter()
            for r in fr:
                keys.update(r.keys())
            log("  出现过的字段：" + ", ".join(sorted(keys)))
            for k in ("ok", "status", "mode", "reason"):
                if k in keys:
                    log(f"  {k} 分布: " + json.dumps(
                        collections.Counter(str(r.get(k)) for r in fr).most_common(10),
                        ensure_ascii=False))
            log("  首条 vs 末条（去掉 time/stage）:")
            for tag, r in (("首", fr[0]), ("末", fr[-1])):
                log(f"    {tag}: " + json.dumps({k: v for k, v in r.items()
                                                  if k not in ("time", "stage")},
                                                 ensure_ascii=False)[:700])
        log("")

        # ---------- 3b. 会话表 ----------
        log("=" * 72)
        log("3b. 会话表（UI_SESSION_END）—— 这里是「出校正结果的速率」，不是面板刷新率")
        log("=" * 72)
        se = [r for r in rows if r.get("stage") == "UI_SESSION_END"]
        log(f"  {'gen':>4} {'view':<10} {'frames':>7} {'current':>8} {'held':>6} "
            f"{'lost':>7} {'lost%':>6} {'corr_fps':>9} {'deliv_fps':>10} {'秒':>7}")
        tf = tc = 0
        for r in se:
            f = r.get("frames", 0) or 0
            c = r.get("current", 0) or 0
            h = r.get("held", 0) or 0
            l = r.get("lost", 0) or 0
            tf += f
            tc += c
            log(f"  {str(r.get('generation')):>4} {str(r.get('view')):<10} {f:>7} {c:>8} "
                f"{h:>6} {l:>7} {(100 * l / f if f else 0):>5.1f}% "
                f"{r.get('current_correction_fps', 0):>9.2f} {r.get('delivered_fps', 0):>10.2f} "
                f"{r.get('formal_elapsed_s', 0):>7.1f}")
        log(f"  {'合计':>4} {'':<10} {tf:>7} {tc:>8} {'':>6} {'':>7} "
            f"{(100 * (tf - tc) / tf if tf else 0):>5.1f}%")
        log("")

        # ---------- 3c. 帧状态与 LOST 归因 ----------
        log("=" * 72)
        log("3c. 帧状态与 LOST 归因（V64_FRAME 是 1/N 抽稀，看比例别数条数）")
        log("=" * 72)
        if fr:
            log("  state: " + json.dumps(collections.Counter(r.get("state") for r in fr).most_common(),
                                          ensure_ascii=False))
            log("  state × mode:")
            for k, v in collections.Counter((r.get("state"), r.get("mode")) for r in fr).most_common(10):
                log(f"    {str(k):<40} {v}")
            lost = [r for r in fr if r.get("state") == "LOST"]
            log(f"  LOST 帧 {len(lost)} 条的 track_reason：")
            for k, v in collections.Counter(str(r.get("track_reason")) for r in lost).most_common(10):
                log(f"    {v:>5}  {k}")
        log("")

        # ---------- 3d. 各 mode 的耗时 ----------
        log("=" * 72)
        log("3d. 各 mode 的关键耗时（均值，ms）")
        log("=" * 72)
        by = collections.defaultdict(list)
        for r in fr:
            by[r.get("mode")].append(r)
        fields = ("ps_prepare_s", "tracker_s", "lk_s", "dma_wait_s", "owner_s",
                  "capture_to_output_s", "preparation_wait_s")
        log("  mode                     n   " + "".join(f"{f.replace('_s',''):>12}" for f in fields))
        for m, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
            cells = ""
            for f in fields:
                vals = [r[f] for r in v if isinstance(r.get(f), (int, float))]
                cells += f"{(sum(vals) / len(vals) * 1000):>12.1f}" if vals else f"{'-':>12}"
            log(f"  {str(m):<22}{len(v):>5}" + cells)
        log("")

        # ---------- 3e. 每 5 秒窗 ----------
        log("=" * 72)
        log("3e. 每 5 秒窗：mode 分布 + 均值耗时（ms）—— 看掉帧掉在哪一段")
        log("=" * 72)
        buck = collections.defaultdict(list)
        for r in fr:
            buck[int((ts(r) - t0) // 5) * 5].append(r)
        log(f"  {'t':>5} {'n':>3} {'static':>6} {'lk':>4} {'edge':>4} {'lost':>4} "
            f"{'ps_prep':>8} {'tracker':>8} {'lk_s':>7} {'cap2out':>8} {'prepwait':>9}")
        for b in sorted(buck):
            v = buck[b]
            def mean(f):
                vals = [r[f] for r in v if isinstance(r.get(f), (int, float))]
                return (sum(vals) / len(vals) * 1000) if vals else None
            cells = ""
            for f in ("ps_prepare_s", "tracker_s", "lk_s", "capture_to_output_s", "preparation_wait_s"):
                m = mean(f)
                cells += f"{'-':>8}" if m is None else f"{m:>8.1f}"
            c = collections.Counter(r.get("mode") for r in v)
            log(f"  {b:>5} {len(v):>3} {c.get('static_hold', 0):>6} {c.get('lk_measured', 0):>4} "
                f"{c.get('edge_measured', 0):>4} {c.get(None, 0):>4}" + cells)
        log("")

        # ---------- 4. 异常 / 恢复 ----------
        log("=" * 72)
        log("4. 异常与恢复")
        log("=" * 72)
        pat = ("FAIL", "ERROR", "CRASH", "EXCEPTION", "TIMEOUT", "ABORT", "MANUAL_TRACK_FAIL")
        hits = [r for r in rows if any(p in str(r.get("stage", "")) for p in pat)]
        log(f"  命中 {len(hits)} 条")
        cnt = collections.Counter(r["stage"] for r in hits)
        for k, v in cnt.most_common():
            log(f"    {v:>4}  {k}")
        for r in hits[:12]:
            log("    - " + json.dumps({k: v for k, v in r.items() if k != "time"},
                                      ensure_ascii=False)[:500])
        log("")
        for stage in ("RECOVERY_TRIGGER", "RECOVERY_TRANSITION", "ASYNC_RECOVERY_RESULT",
                      "UNIFIED_AUTO_PHASE", "UNIFIED_AUTO_ACCEPTED", "MANUAL_TRACK_FAIL"):
            ss = [r for r in rows if r.get("stage") == stage]
            if not ss:
                continue
            log(f"  {stage}: {len(ss)} 条")
            for r in ss[:3]:
                log("    " + json.dumps({k: v for k, v in r.items() if k != "time"},
                                        ensure_ascii=False)[:400])
        log("")

        # ---------- 5. 内存 / AI ----------
        log("=" * 72)
        log("5. AI 与内存")
        log("=" * 72)
        for stage in ("AI_READY", "AI_MEMORY_ADMISSION", "AI_WORKER_RESULT", "AI_WORKER_ERROR"):
            ss = [r for r in rows if r.get("stage") == stage]
            if not ss:
                continue
            log(f"  {stage}: {len(ss)} 条")
            for r in ss[:4]:
                log("    " + json.dumps({k: v for k, v in r.items() if k != "time"},
                                        ensure_ascii=False)[:500])
        log("")

        # ---------- 6. 收尾 ----------
        log("=" * 72)
        log("6. 最后 6 条")
        log("=" * 72)
        for r in rows[-6:]:
            log("  " + json.dumps(r, ensure_ascii=False)[:600])
        log("")
        log("RESULT: OK（只读分析，未改动任何文件）")
        return 0
    except Exception:
        log("[!!] 完整堆栈（不截断）：")
        log(traceback.format_exc())
        log("RESULT: FAIL")
        return 1
    finally:
        OUT.close()
        print("report ->", REPORT, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
