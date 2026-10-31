#!/usr/bin/env python3
"""联网核对本地规则与当日上游列表的交互（离线回归无法覆盖的部分）。

用法：python3 tools/check_upstream.py
发布时 tools/build_rules.py 也会用同一份下载数据调用 check()，不通过则不发布（客户端继续用上一版）。

失败条件：
  1. Claude / AI 相关本地域名被 geosite:cn 收录：本地解析（UDP、fake-ip-filter、IP 规则）会改用国内 DNS，
     QUIC 规则会把它当国内放行。
  2. 任一本地条目（rules/*.txt）被排在前面、去向不同的集合整体截走（Stash 的规则是 mihomo 的子集，只需查一遍）：
     这条本地规则永远不会生效。最常见的是广告源收录了 AI / 直连补充条目——
     确属必需的端点应挪进排在广告前的 ai-essential.txt（AI）或 local-direct.txt（直连）。
前面的集合只截走某个子域（如 Intercom 的分析上报被广告源拦截）属预期，不算失败。
"""
from __future__ import annotations

import sys

import build
import build_rules

# 必须保持境外归属的本地集合（进入 cn 会影响 DNS 与 QUIC 判断）
AI_LIKE = ("ai-essential", "ai", "auth", "telemetry")


def check(cache: dict[str, list[str]], sets: dict[str, list[str]] | None = None) -> tuple[list[str], list[str]]:
    """返回 (失败, 提示)。sets 为 build_rules.collect 的结果，省略时现算。"""
    sets = sets or build_rules.collect(cache)
    problems, notes = [], []
    cn = build_rules.DomainMatcher(cache["geosite:cn"])
    for name in AI_LIKE:
        for row in build.local_rows(name):
            if cn.covers(row):
                problems.append(f"[cn] rules/{name}.txt: {row} 被 geosite:cn 收录")
    table = build_rules.route_table(sets)
    for i, (name, to, _) in enumerate(table):
        for row in build.local_rows(name):
            for earlier, earlier_to, matcher in table[:i]:
                if earlier_to != to and matcher.covers(row):
                    problems.append(f"rules/{name}.txt: {row} 被前面的 {earlier}（{earlier_to}）整体截走，不会走 {to}")
                    break
    # 仅提示：essential 被广告源收录是预期（它排在广告前），列出来便于了解覆盖关系
    ads = build_rules.DomainMatcher(sets["ads"])
    hits = [row for row in build.local_rows("ai-essential") if ads.covers(row)]
    if hits:
        notes.append(f"i 广告源也收录、由排在前面的 ai-essential 放行：{', '.join(hits)}")
    return problems, notes


def main() -> int:
    problems, notes = check(build_rules.fetch_all())
    if notes:
        print("\n".join(notes))
    if problems:
        print("\n".join(problems))
        return 1
    print("✓ Claude/AI 本地域名均不在 geosite:cn；本地条目都没有被前面的集合整体截走")
    return 0


if __name__ == "__main__":
    sys.exit(main())
