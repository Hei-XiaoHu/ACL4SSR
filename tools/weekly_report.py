#!/usr/bin/env python3
"""每周规则报告：旧 ACL4SSR 的未审阅差异 + 关注的上游集合相比上周的增删。

用法：python3 tools/weekly_report.py --baseline-dir report-branch --out report-branch/report.md
       [--github-output $GITHUB_OUTPUT]

基准存放在 report 分支的 baseline/ 下（每周覆盖，分支保留历史）；首次运行只建立基准。
增删条目会按当日合并后的 mihomo 规则算出实际去向：与该上游所在集合的去向不同（被前面的集合截走，
或删除后不再命中）时标 ⚠️，需要人工判断。
输出 has_new=true 表示有需要关注的新条目（Action 据此决定是否在 issue 追加评论）。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import build
import build_rules
import legacy_diff

MAX_LIST = 200  # 单个集合最多列出的增删条目


def intended(src: str) -> tuple[str, str] | None:
    """该上游在 mihomo 下所属的 (集合, 去向)。"""
    for item in build.S["sets"]:
        if isinstance(item, dict) and item.get("to") and src in build.sources(item["name"], "meta"):
            return item["name"], item["to"]
    return None


def describe(entry: str, table, want: tuple[str, str] | None) -> tuple[str, bool]:
    """返回 (Markdown 片段, 是否偏离预期去向)。"""
    host = build_rules._host(entry)
    if "*" in host or not want:
        return f"`{entry}`", False
    name, to = build_rules.route(table, host)
    if to == want[1]:
        return f"`{entry}`", False
    where = f"{name} / {to}" if to else "域名规则未命中，按 IP / 漏网之鱼"
    return f"`{entry}`（⚠️ 实际 → {where}）", True


def watch_section(baseline: Path, cache: dict, table) -> tuple[list[str], bool, list[str]]:
    lines, changed, summary = ["## 关注的上游集合（相比上周）", ""], False, []
    baseline.mkdir(parents=True, exist_ok=True)
    for src in build.S["watch"]:
        current = sorted(set(cache[src]))
        want = intended(src)
        path = baseline / (src.replace(":", "_").replace("/", "_") + ".txt")
        if not path.exists():
            lines.append(f"- `{src}`：首次建立基准（{len(current)} 条）")
        else:
            old = set(path.read_text(encoding="utf-8").split())
            added = [e for e in current if e not in old]
            removed = sorted(old - set(current))
            if not added and not removed:
                lines.append(f"- `{src}`：无变化（{len(current)} 条）")
            else:
                changed = True
                flagged = 0
                head = f"- `{src}`：新增 {len(added)}、删除 {len(removed)}（现 {len(current)} 条"
                lines.append(head + (f"，预期去向 {want[1]}）" if want else "）"))
                for title, items in (("新增", added), ("删除", removed)):
                    if not items:
                        continue
                    shown = []
                    for entry in items[:MAX_LIST]:
                        text, off = describe(entry, table, want)
                        flagged += off
                        shown.append(text)
                    more = f" …共 {len(items)} 条" if len(items) > MAX_LIST else ""
                    lines.append(f"  - {title}：{', '.join(shown)}{more}")
                summary.append(f"{src} +{len(added)} -{len(removed)}" + (f"（⚠️ {flagged}）" if flagged else ""))
        path.write_text("\n".join(current) + "\n", encoding="utf-8")
    lines += [
        "",
        "新增条目已自动进入对应集合。⚠️ 表示实际去向与该集合不同：新增的被排在前面的集合截走"
        "（如遥测被 🛑 拦截属预期），删除的已不再命中原去向。",
        "删除的主机若仍在使用，加进对应的 `rules/*.txt`（下载主机加进 `rules/direct.txt`）；"
        "Claude 家族新域名同步到 `rules/ai.txt`。",
    ]
    return lines, changed, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--github-output", type=Path)
    args = ap.parse_args()

    # 只下载一次：旧规则对比、去向计算与关注集合共用
    cache = build_rules.fetch_all(sorted({*build_rules.needed_sources(), *build.S["watch"]}))
    table = build_rules.route_table(build_rules.collect("meta", cache))
    diffs, stats = legacy_diff.compute(cache, table)
    kept, skipped = legacy_diff.filter_reviewed(diffs)
    watch_lines, watch_changed, summary = watch_section(args.baseline_dir / "baseline", cache, table)
    if kept:
        summary.insert(0, f"旧 ACL4SSR 未审阅差异 {len(kept)} 条")

    beijing = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    body = [
        f"# 每周规则报告（{beijing} 北京时间）",
        "",
        "**本周需要关注：** " + ("；".join(summary) if summary else "无"),
        "",
        *watch_lines,
        "",
        legacy_diff.markdown(kept, stats, skipped),
        "---",
        "处理方式：确需调整的条目加进 `rules/` 下对应文件；有意不同的条目连同理由记入 `src/legacy-review.yaml`，下周不再出现。",
    ]
    args.out.write_text("\n".join(body) + "\n", encoding="utf-8")
    has_new = bool(kept) or watch_changed
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as f:
            f.write(f"has_new={'true' if has_new else 'false'}\n")
            f.write(f"summary={'；'.join(summary) if summary else '无'}\n")
    print("\n".join(body[:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
