#!/usr/bin/env bash
# sync-check.sh — 检查 fpga-project-development/references/ 里的整合副本
#                 是否与外部原版 skill 脱节。
#
# 用法：bash "~/.claude/skills/fpga-project-development/scripts/sync-check.sh"
#
# 原理：每个整合副本的头部 HTML 注释里记着上游路径和上游 SKILL.md 的 sha256 前 16 位。
#       本脚本重新计算上游指纹并比对。
#       头部【没有】"上游指纹"那一行的文件 = 路由型条目，跳过。

set -u

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF_DIR="$SKILL_DIR/references"

if [ ! -d "$REF_DIR" ]; then
    echo "[FAIL] 找不到 references 目录：$REF_DIR" >&2
    exit 1
fi

n_ok=0; n_drift=0; n_missing=0; n_routed=0; n_native=0

printf '\n%s\n' "═══ fpga-project-development 同步检查 ═══"
printf '%s\n\n' "整合版目录：$REF_DIR"

shopt -s nullglob
files=("$REF_DIR"/*.md)
shopt -u nullglob

if [ ${#files[@]} -eq 0 ]; then
    echo "[FAIL] references/ 里没有 .md 文件" >&2
    exit 1
fi

for f in "${files[@]}"; do
    base="$(basename "$f")"

    # —— 自有条目：本项目原创，无上游、无副本，跳过 ——
    if grep -qm1 '^类型：自有' "$f" 2>/dev/null; then
        printf '★  自有      %-30s  （本项目原创，无上游）\n' "$base"
        n_native=$((n_native + 1))
        continue
    fi

    # 头部注释里的上游路径（Windows 反斜杠 → 正斜杠，供 bash 使用）
    upstream="$(grep -m1 '^来源：' "$f" 2>/dev/null | sed 's/^来源：//' | tr -d '\r')"
    upstream="${upstream//\\//}"

    # 头部注释里的已记录指纹
    recorded="$(grep -m1 '^上游指纹' "$f" 2>/dev/null | sed 's/.*：//' | tr -d '\r ')"
    syncdate="$(grep -m1 '^同步日期：' "$f" 2>/dev/null | sed 's/^同步日期：//' | tr -d '\r')"

    # —— 路由型条目：没有"上游指纹"行 —— 只检查指针目标还在不在 ——
    if [ -z "$recorded" ]; then
        target="$(grep -m1 '^路由目标：' "$f" 2>/dev/null | sed 's/^路由目标：//' | tr -d '\r')"
        target="${target//\\//}"

        if [ -z "$target" ]; then
            printf '[FAIL] 头部格式错误  %-30s  （既无"上游指纹"、也无"路由目标"、更无"类型：自有"）\n' "$base"
            n_missing=$((n_missing + 1))
        elif [ -e "$target" ]; then
            printf '·  路由      %-30s  → 目标存在\n' "$base"
            n_routed=$((n_routed + 1))
        else
            printf '[FAIL] 路由断链  %-30s  → 目标不存在：%s\n' "$base" "$target"
            n_missing=$((n_missing + 1))
        fi
        continue
    fi

    # —— 上游文件不存在 ——
    if [ ! -f "$upstream" ]; then
        printf '[FAIL] 上游缺失  %-30s  → %s\n' "$base" "$upstream"
        n_missing=$((n_missing + 1))
        continue
    fi

    # —— 比对指纹 ——
    actual="$(sha256sum "$upstream" 2>/dev/null | cut -c1-16)"

    if [ "$actual" = "$recorded" ]; then
        printf '[OK] 一致      %-30s  （同步于 %s）\n' "$base" "${syncdate:-未知}"
        n_ok=$((n_ok + 1))
    else
        printf '[!]  上游已变  %-30s\n' "$base"
        printf '              记录=%s  实际=%s  （同步于 %s）\n' \
               "$recorded" "$actual" "${syncdate:-未知}"
        n_drift=$((n_drift + 1))
    fi
done

printf '\n%s\n' "─────────────────────────────────────────"
printf '一致 %d ｜ [!] 上游已变 %d ｜ [FAIL] 问题 %d ｜ · 路由 %d ｜ ★ 自有 %d\n' \
       "$n_ok" "$n_drift" "$n_missing" "$n_routed" "$n_native"

if [ "$n_drift" -gt 0 ] || [ "$n_missing" -gt 0 ]; then
    printf '\n%s\n' "[!]  有脱节项。先 diff 原版与整合版，再决定怎么合 —— 规程见 references/06-sync-protocol.md"
    exit 1
fi

printf '\n%s\n' "[OK] 全部同步。"
exit 0
