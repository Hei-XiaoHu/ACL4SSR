#!/usr/bin/env python3
"""每周规则报告：旧 ACL4SSR 的未审阅差异 + 关注的上游集合相比上周的增删。

用法：python3 tools/weekly_report.py --baseline-dir report-branch --out report-branch/report.md
       [--github-output $GITHUB_OUTPUT]

基准存放在 report 分支的 baseline/ 下（每周覆盖，分支保留历史）；首次运行只建立基准。
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


def watch_section(baseline: Path) -> tuple[list[str], bool, list[str]]:
    lines, changed, summary = ["## 关注的上游集合（相比上周）", ""], False, []
    baseline.mkdir(parents=True, exist_ok=True)
    for src in build.S["watch"]:
        current = sorted(set(build_rules.fetch(src)))
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
                summary.append(f"{src} +{len(added)} -{len(removed)}")
                lines.append(f"- `{src}`：新增 {len(added)}、删除 {len(removed)}（现 {len(current)} 条）")
                for title, items in (("新增", added), ("删除", removed)):
                    if items:
                        shown = ", ".join(f"`{e}`" for e in items[:MAX_LIST])
                        more = f" …共 {len(items)} 条" if len(items) > MAX_LIST else ""
                        lines.append(f"  - {title}：{shown}{more}")
        path.write_text("\n".join(current) + "\n", encoding="utf-8")
    lines.append("")
    lines.append("下载集合新增的主机已自动直连；若删除了仍在使用的下载主机，请把它加进 `rules/direct.txt`。")
    return lines, changed, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--github-output", type=Path)
    args = ap.parse_args()

    diffs, stats = legacy_diff.compute()
    kept, skipped = legacy_diff.filter_reviewed(diffs)
    watch_lines, watch_changed, summary = watch_section(args.baseline_dir / "baseline")
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
