#!/usr/bin/env python3
"""给「按层合并」发布包生成 release_manifest.json。

做法：以旧包（114 模块版）的 manifest 为元数据底本，只改四处：
  * layout = 'layers-6'
  * sha256 里删掉 114 个模块的 .py，换成 6 个合并文件的 .py
  * runtime_modules 改成 6 个层名
  * **sha256 收敛成「包内文件的精确快照」** —— 底本里 130 条指向包里根本不存在的文件
    （ai_selftest/*.png、hardware_light27/* …），verify_package 只核 required 所以一直
    没被发现；而 v84_prebuilt.export_ready_upload 会遍历 sha256 逐个 read_bytes()，
    幽灵条目在那条路径上直接 FileNotFoundError。⇒ 包里有什么就列什么，一个不多一个不少。
  * **`v98_ai_manifest.json` 同样收敛**，且必须排在发布清单之前（它会改写磁盘文件）。
    2026-11-02 板上实炸：AI 子进程 validate_assets() 逐条 read_bytes()，清单里那 33 条
    已剔除的 model_zoo/utils/dist-info 直接让 AI_INIT_FAILED。
其余 150+ 条设计说明原样保留（它们是给人看的，不是校验用的）。

    python build/make_release_manifest.py <运行目录> <旧 release_manifest.json>
"""
import datetime
import hashlib
import io
import json
import platform
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORT = REPO / "build" / "reports" / "make_release_manifest_report.txt"
LAYER_MODULES = ("core", "geometry", "tracking", "display", "ai", "ui")
# 不是模块、但必须是真实文件的（子进程入口），与 p11_contract.LAYER_EXTRA_FILES 对应
LAYER_EXTRA = ("v99_ai_worker.py", "v99_ai_selftest.py")
_REPORT = None


def log(line=""):
    text = str(line) + "\n"
    if _REPORT is not None:
        _REPORT.write(text)
        _REPORT.flush()
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def _present_files(runtime):
    """包内应当进清单的文件（相对路径，posix 分隔，已排序）。

    release_manifest.json 自己不算（它的 sha 写在它里面，永远自相矛盾）；
    __pycache__ 是本机构建残留，第 10 步会清掉，不进清单。
    """
    return sorted(
        p.relative_to(runtime).as_posix()
        for p in runtime.rglob("*")
        if p.is_file()
        and p.name != "release_manifest.json"
        and "__pycache__" not in p.parts
        and p.suffix != ".pyc"
    )


def _reconcile(runtime, sha):
    """把 sha 原地收敛成「包内文件的精确快照」，返回 (删掉的幽灵, 补上的漏登, 重算过的)。

    ⚠️ 已存在的条目也要**按实际文件重算**：`_reconcile_ai_manifest()` 会在本函数之前
    改写 `v98_ai_manifest.json`，只补不重算就会留下旧 sha ⇒ verify_package 报
    「文件版本或内容不一致：v98_ai_manifest.json」（2026-11-02 实踩）。
    """
    present = _present_files(runtime)
    present_set = set(present)
    ghost = sorted(k for k in sha if k not in present_set)
    for name in ghost:
        del sha[name]
    added, updated = [], []
    for name in present:
        actual = hashlib.sha256((runtime / name).read_bytes()).hexdigest()
        if name not in sha:
            sha[name] = actual
            added.append(name)
        elif sha[name] != actual:
            updated.append((name, sha[name], actual))
            sha[name] = actual
    # 后置条件①：收敛完不许还有条目指向不存在的文件
    still = sorted(k for k in sha if not (runtime / k).is_file())
    if still:
        raise RuntimeError("收敛后仍有条目指向包内不存在的文件：" + ", ".join(still))
    # 后置条件②：包内每个文件都必须被清单覆盖
    uncovered = sorted(present_set - set(sha))
    if uncovered:
        raise RuntimeError("包内文件没进清单：" + ", ".join(uncovered))
    return ghost, added, updated


def _reconcile_ai_manifest(runtime):
    """收敛 `v98_ai_manifest.json`：只留包内真实存在的 ai/ 资产，并核每个 sha256。

    为什么必须做：AI 子进程 `validate_assets()`（v99_ai_worker.py:77）会
    `for name,digest in manifest['sha256'].items(): read_bytes()`，少一个文件就
    AI_INIT_FAILED。2026-11-02 实炸：RELEASE_EXCLUDE 剔掉 model_zoo/utils/dist-info 后，
    清单里那 33 条让整个 AI 通路起不来；而 check_merged 的 AI 门在 x86 上先撞平台断言
    （`machine != 'armv7l'`）就退了，**遍历资产的循环只有板上才跑得到**。

    返回 (改过的 manifest, 删掉的幽灵, 补上的漏登)。
    """
    path = runtime / "v98_ai_manifest.json"
    if not path.is_file():
        raise FileNotFoundError("运行目录里没有 v98_ai_manifest.json（AI 子进程的资产门要用）")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    sha = manifest.get("sha256")
    if not isinstance(sha, dict):
        raise ValueError("v98_ai_manifest.json 没有 sha256 字典")
    present = sorted(
        p.relative_to(runtime).as_posix()
        for p in (runtime / "ai").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
    present_set = set(present)
    ghost = sorted(k for k in sha if k not in present_set)
    for name in ghost:
        del sha[name]
    added, changed = [], []
    for name in present:
        if not name.startswith("ai/"):
            raise ValueError("AI 清单条目不在 ai/ 下：" + name)
        actual = hashlib.sha256((runtime / name).read_bytes()).hexdigest()
        if name not in sha:
            sha[name] = actual
            added.append(name)
        elif sha[name] != actual:
            changed.append((name, sha[name], actual))
    # 资产是不可变输入：sha 对不上就是资产被改过，⛔ 不许像幽灵条目那样静默重写
    if changed:
        raise ValueError("AI 资产与清单 sha256 不符（资产不该被改）："
                         + ", ".join(f"{n}: 清单{c[:16]}≠实际{a[:16]}" for n, c, a in changed))
    if set(sha) != present_set:
        raise RuntimeError("AI 清单与包内 ai/ 不一致：多 "
                           + ", ".join(sorted(set(sha) - present_set))
                           + "；缺 " + ", ".join(sorted(present_set - set(sha))))
    manifest["sha256"] = {k: sha[k] for k in sorted(sha)}
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest, ghost, added


def _ai_rule_selftest():
    """判红：AI 清单的「幽灵」「漏登」「资产被改」三条判据都必须能报出来。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "ai").mkdir()
        (root / "ai" / "a.bin").write_bytes(b"aaa")
        (root / "ai" / "b.bin").write_bytes(b"bbb")
        m = {"release_id": "x", "format": 1, "sha256": {
            "ai/a.bin": hashlib.sha256(b"aaa").hexdigest(), "ai/ghost.bin": "0" * 64}}
        (root / "v98_ai_manifest.json").write_text(json.dumps(m), encoding="utf-8")
        _, ghost, added = _reconcile_ai_manifest(root)
        if ghost != ["ai/ghost.bin"] or added != ["ai/b.bin"]:
            raise RuntimeError(f"判红失败：幽灵/漏登没抓全（{ghost} / {added}）")
        after = json.loads((root / "v98_ai_manifest.json").read_text(encoding="utf-8"))
        if after["sha256"].get("ai/b.bin") != hashlib.sha256(b"bbb").hexdigest():
            raise RuntimeError("判红失败：补登条目 sha256 算错")
        (root / "ai" / "a.bin").write_bytes(b"aab")   # 资产被改，必须报错而不是静默改写
        try:
            _reconcile_ai_manifest(root)
        except ValueError:
            pass
        else:
            raise RuntimeError("判红失败：资产被改却没报 sha256 不符")
        return ghost, added


def _rule_selftest():
    """判红：造一个幽灵条目 + 一个漏登文件，两条判据必须都能报出来。

    没有这一步，`_reconcile` 可能是个永远返回空列表的空转规则，而报告照样全绿。
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.txt").write_text("aaa", encoding="utf-8")
        (root / "sub").mkdir()
        (root / "sub" / "b.txt").write_text("bbb", encoding="utf-8")
        sha = {"a.txt": hashlib.sha256(b"aaa").hexdigest(), "ghost.txt": "0" * 64}
        ghost, added, updated = _reconcile(root, sha)
        if ghost != ["ghost.txt"]:
            raise RuntimeError(f"判红失败：幽灵条目没被抓到，实际 {ghost}")
        if added != ["sub/b.txt"]:
            raise RuntimeError(f"判红失败：漏登文件没被抓到，实际 {added}")
        if updated:
            raise RuntimeError(f"判红失败：没改过文件却重算了 sha，实际 {updated}")
        if "ghost.txt" in sha or sha.get("a.txt") != hashlib.sha256(b"aaa").hexdigest():
            raise RuntimeError("判红失败：收敛改坏了原有条目")
        (root / "a.txt").write_text("aab", encoding="utf-8")   # 文件变了，sha 必须跟着变
        _, _, updated2 = _reconcile(root, {"a.txt": sha["a.txt"]})
        if [n for n, _, _ in updated2] != ["a.txt"]:
            raise RuntimeError(f"判红失败：文件变了却没重算 sha，实际 {updated2}")
        if hashlib.sha256(b"bbb").hexdigest() != sha.get("sub/b.txt"):
            raise RuntimeError("判红失败：补登条目的 sha256 算错")
        return ghost, added


def main():
    global _REPORT
    if len(sys.argv) != 3:
        print("用法: python build/make_release_manifest.py <运行目录> <旧 manifest>")
        return 2
    runtime = Path(sys.argv[1]).resolve()
    base = Path(sys.argv[2]).resolve()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT = io.open(REPORT, "w", encoding="utf-8", newline="\n")
    for h in ["=" * 70,
              "  make_release_manifest.py —— 合并版发布清单",
              "=" * 70,
              f"时间   : {datetime.datetime.now().isoformat(timespec='seconds')}",
              f"机器   : {platform.node()} / {platform.platform()}",
              f"Python : {sys.version.split()[0]}",
              f"脚本   : {Path(__file__).name}  sha16={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}",
              f"运行目录: {runtime}",
              f"底本    : {base}",
              "=" * 70, ""]:
        log(h)
    try:
        log("[0] 收敛规则自检（每条判据都先造一次失败，必须能报出来）")
        g, a = _rule_selftest()
        log(f"    发布清单：幽灵 {g} / 漏登 {a} / 原条目未被改坏 —— 判红有效")
        ag, aa = _ai_rule_selftest()
        log(f"    AI 资产清单：幽灵 {ag} / 漏登 {aa} / 资产被改必须报 sha 不符 —— 判红有效")
        log("")

        manifest = json.loads(base.read_text(encoding="utf-8"))
        sha = manifest["sha256"]
        removed = []
        for name in list(sha):
            if name.endswith(".py"):
                removed.append(name)
                del sha[name]
        log(f"[1] 从底本删掉 {len(removed)} 个 .py 条目")
        for n in LAYER_MODULES:
            p = runtime / (n + ".py")
            if not p.is_file():
                raise FileNotFoundError(f"运行目录里没有 {p.name}")
            sha[n + ".py"] = hashlib.sha256(p.read_bytes()).hexdigest()
            log(f"    + {n}.py  {sha[n + '.py'][:16]}  {p.stat().st_size:,} B")
        for n in LAYER_EXTRA:
            p = runtime / n
            if not p.is_file():
                raise FileNotFoundError(f"运行目录里没有 {n}")
            sha[n] = hashlib.sha256(p.read_bytes()).hexdigest()
            log(f"    + {n}  {sha[n][:16]}  {p.stat().st_size:,} B  （子进程入口，非模块）")
        log("")

        # ⚠️ 顺序不能换：AI 清单会**改写磁盘上的文件**，必须在发布清单算它的 sha 之前做
        log("[2] 收敛 AI 资产清单 v98_ai_manifest.json（AI 子进程 check_assets 逐条 read_bytes）")
        _, ai_ghost, ai_added = _reconcile_ai_manifest(runtime)
        log(f"    删掉幽灵条目 {len(ai_ghost)} 个（包内没有的 ai/ 资产）：")
        for name in ai_ghost:
            log(f"      - {name}")
        log(f"    补上漏登资产 {len(ai_added)} 个：")
        for name in ai_added:
            log(f"      + {name}")
        log("")

        log("[3] 收敛发布清单：只列包内真实存在的文件")
        ghost, added, updated = _reconcile(runtime, sha)
        log(f"    删掉幽灵条目 {len(ghost)} 个（底本里有、包里没有）：")
        for name in ghost:
            log(f"      - {name}")
        log(f"    补上漏登文件 {len(added)} 个（包里有、底本里没有）：")
        for name in added:
            log(f"      + {name}  {sha[name][:16]}")
        log(f"    重算 sha 的条目 {len(updated)} 个（包里内容与底本不同）：")
        for name, old, new in updated:
            log(f"      ~ {name}  {old[:16]} -> {new[:16]}")
        manifest["sha256"] = {k: sha[k] for k in sorted(sha)}
        sha = manifest["sha256"]
        log("")

        manifest["layout"] = "layers-6"
        manifest["runtime_modules"] = list(LAYER_MODULES)
        manifest["merge_note"] = ("按依赖层合并：core/geometry/tracking/ui/display/ai 六个文件，"
                                  "逐字保留原 114 个模块的全部注释与代码；"
                                  "另附 v99_ai_worker.py 作为 AI 子进程入口（自包含，不导入任何层文件）；"
                                  "合并正确性＝AST 逐条语句比对 0 差异（build/verify_merge.py）"
                                  "＋原版与合并版检查链结果比对（build/compare_checks.py）。")
        out = runtime / "release_manifest.json"
        out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log("")
        log(f"[4] 写入 {out}")
        log(f"    sha256 条目 {len(sha)} 个（= 包内除 release_manifest.json 外的全部文件，"
            f"一个不多一个不少）")
        log("")
        log("RESULT: OK")
        return 0
    except Exception:
        log("")
        log("[!!] 失败，完整堆栈如下（不截断）：")
        log(traceback.format_exc())
        log("RESULT: FAIL")
        return 1
    finally:
        _REPORT.close()


if __name__ == "__main__":
    sys.exit(main())
