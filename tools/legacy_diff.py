#!/usr/bin/env python3
"""对比旧 ACL4SSR 规则与当前规则：同一域名在旧版与新版下的默认去向（直连 / 代理 / 拦截）。

用法：
  python3 tools/legacy_diff.py                 打印差异摘要
  python3 tools/legacy_diff.py --markdown F    写出完整报告

旧版去向按重构前的规则顺序模拟（先命中者生效）；新版按 src/spec.yaml 的 sets 顺序，
用当日合并后的 mihomo 集合模拟。只比较 DOMAIN / DOMAIN-SUFFIX 条目；关键词、IP 等仅计数。
src/legacy-review.yaml 中已审阅的条目与整类结论不再报告。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

import build
import build_rules

ACL = "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash"
# 重构前的规则顺序（f1c38b0^ 的 dns_enhanced.yml），去向折算为新组名
LEGACY = [
    ("LocalAreaNetwork", "LocalAreaNetwork.list", "DIRECT"),
    ("UnBan", "UnBan.list", "🎯 直连"),
    ("BanAD", "BanAD.list", "🛑 广告"),
    ("BanProgramAD", "BanProgramAD.list", "🛑 广告"),
    ("GoogleFCM", "Ruleset/GoogleFCM.list", "🔍 谷歌"),
    ("GoogleCN", "GoogleCN.list", "🎯 直连"),
    ("SteamCN", "Ruleset/SteamCN.list", "🎯 直连"),
    ("Bing", "Bing.list", "Ⓜ️ 微软"),
    ("OneDrive", "OneDrive.list", "Ⓜ️ 微软"),
    ("Microsoft", "Microsoft.list", "Ⓜ️ 微软"),
    ("Apple", "Apple.list", "🍎 苹果"),
    ("Telegram", "Telegram.list", "🚀 节点选择"),
    ("AI", "Ruleset/AI.list", "🤖 AI"),
    ("OpenAi", "Ruleset/OpenAi.list", "🤖 AI"),
    ("NetEaseMusic", "Ruleset/NetEaseMusic.list", "🎯 直连"),
    ("Epic", "Ruleset/Epic.list", "🎮 游戏"),
    ("Origin", "Ruleset/Origin.list", "🎮 游戏"),
    ("Sony", "Ruleset/Sony.list", "🎮 游戏"),
    ("Steam", "Ruleset/Steam.list", "🎮 游戏"),
    ("Nintendo", "Ruleset/Nintendo.list", "🎮 游戏"),
    ("YouTube", "Ruleset/YouTube.list", "🎬 流媒体"),
    ("Netflix", "Ruleset/Netflix.list", "🎬 流媒体"),
    ("Bahamut", "Ruleset/Bahamut.list", "🎬 流媒体"),
    ("BilibiliHMT", "Ruleset/BilibiliHMT.list", "📺 B站"),
    ("Bilibili", "Ruleset/Bilibili.list", "📺 B站"),
    ("ChinaMedia", "ChinaMedia.list", "🎯 直连"),
    ("ProxyMedia", "ProxyMedia.list", "🎬 流媒体"),
    ("ProxyGFWlist", "ProxyGFWlist.list", "🚀 节点选择"),
    ("ChinaDomain", "ChinaDomain.list", "🎯 直连"),
    ("ChinaCompanyIp", "ChinaCompanyIp.list", "🎯 直连"),
    ("Download", "Download.list", "🎯 直连"),
]
DIRECT_GROUPS = {"DIRECT", "🎯 直连", "📺 B站", "Ⓜ️ 微软", "🍎 苹果"}
REVIEW = build.ROOT / "src" / "legacy-review.yaml"


def outcome(group: str | None) -> str:
    if group is None:
        return "按IP"
    if group == "🛑 广告":
        return "拦截"
    return "直连" if group in DIRECT_GROUPS else "代理"


def parse_legacy(body: str) -> tuple[list[tuple[str, str]], int]:
    rows, other = [], 0
    for line in body.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        kind, _, value = line.partition(",")
        value = value.split(",", 1)[0].strip().lower()
        if kind == "DOMAIN-SUFFIX":
            rows.append(("suffix", value))
        elif kind == "DOMAIN":
            rows.append(("exact", value))
        else:
            other += 1
    return rows, other


class Matcher:
    def __init__(self, entries: list[str]):
        self.exact, self.suffix, self.sub, self.regex = set(), set(), set(), []
        for e in entries:
            if e.startswith("DOMAIN-REGEX,"):
                self.regex.append(re.compile(e.split(",", 1)[1]))
            elif e.startswith("DOMAIN-SUFFIX,"):
                self.suffix.add(e.split(",", 1)[1])
            elif e.startswith("DOMAIN,"):
                self.exact.add(e.split(",", 1)[1])
            elif e.startswith("+."):
                self.suffix.add(e[2:])
            elif e.startswith("."):
                self.sub.add(e[1:])
            elif "*" not in e:
                self.exact.add(e)

    def match(self, host: str) -> bool:
        if host in self.exact or host in self.suffix:
            return True
        labels = host.split(".")
        for i in range(1, len(labels)):
            parent = ".".join(labels[i:])
            if parent in self.suffix or parent in self.sub:
                return True
        return any(r.search(host) for r in self.regex)


def new_route(matchers: list[tuple[str, str, Matcher]], host: str) -> tuple[str | None, str | None]:
    for name, to, m in matchers:
        if m.match(host):
            return name, to
    return None, None


def load_review() -> tuple[dict, dict]:
    if not REVIEW.exists():
        return {}, {}
    data = yaml.safe_load(REVIEW.read_text(encoding="utf-8")) or {}
    return data.get("lists") or {}, data.get("domains") or {}


def compute():
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        bodies = dict(zip([n for n, _, _ in LEGACY],
                          pool.map(lambda item: build_rules._download(f"{ACL}/{item[1]}"), LEGACY)))
        needed = sorted({s for n in build.SETS if build.has_provider(n, "meta") for s in build.fetched_sources(n, "meta")})
        cache = dict(zip(needed, pool.map(build_rules.fetch, needed)))
    sets = build_rules.collect("meta", cache)
    matchers = [(item["name"], item["to"], Matcher(sets[item["name"]])) for item in build.S["sets"]
                if isinstance(item, dict) and item.get("to") and item["name"] in sets
                and build.set_type(item["name"]) != "ip"]
    legacy = []
    stats = {}
    for name, _, group in LEGACY:
        rows, other = parse_legacy(bodies[name])
        legacy.append((name, group, rows))
        stats[name] = {"domains": len(rows), "other": other}
    # 旧版：按顺序先命中者生效
    seen, diffs = set(), []
    for name, group, rows in legacy:
        for kind, host in rows:
            key = (kind, host)
            if key in seen:
                continue
            seen.add(key)
            new_set, new_group = new_route(matchers, host)
            old_o, new_o = outcome(group), outcome(new_group)
            if old_o != new_o:
                diffs.append({"list": name, "entry": ("+." if kind == "suffix" else "") + host,
                              "old": group, "new": new_group or "（未命中，按 IP / 漏网之鱼）",
                              "new_set": new_set or "-", "change": f"{old_o}→{new_o}"})
    return diffs, stats


def filter_reviewed(diffs: list[dict]) -> tuple[list[dict], int]:
    lists, domains = load_review()
    kept, skipped = [], 0
    for d in diffs:
        changes = set((lists.get("*") or {}).get("changes", [])) | set((lists.get(d["list"]) or {}).get("changes", []))
        if domains.get(d["entry"]) == d["list"] or d["change"] in changes:
            skipped += 1
            continue
        kept.append(d)
    return kept, skipped


def markdown(diffs: list[dict], stats: dict, skipped: int) -> str:
    out = ["## 旧 ACL4SSR 与当前规则的默认去向差异", ""]
    out.append(f"未审阅差异 **{len(diffs)}** 条（已审阅忽略 {skipped} 条）。只比较 DOMAIN/DOMAIN-SUFFIX；"
               "“按IP”表示新版域名规则都未命中，取决于 IP 是否在国内。")
    groups = defaultdict(list)
    for d in diffs:
        groups[(d["list"], d["change"])].append(d)
    if groups:
        out += ["", "| 旧列表 | 变化 | 条数 | 示例 |", "|---|---|---|---|"]
        for (lst, change), items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            sample = ", ".join(f"`{i['entry']}`" for i in items[:5])
            out.append(f"| {lst} | {change} | {len(items)} | {sample} |")
        out += ["", "<details><summary>全部条目</summary>", "", "| 条目 | 旧列表 / 旧组 | 新集合 / 新组 |", "|---|---|---|"]
        for d in diffs:
            out.append(f"| `{d['entry']}` | {d['list']} / {d['old']} | {d['new_set']} / {d['new']} |")
        out += ["", "</details>"]
    other = sum(s["other"] for s in stats.values())
    out += ["", f"旧列表共 {sum(s['domains'] for s in stats.values())} 条域名规则；另有 {other} 条关键词/IP/其他规则未比较。"]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", type=Path)
    ap.add_argument("--all", action="store_true", help="不过滤已审阅条目")
    args = ap.parse_args()
    diffs, stats = compute()
    kept, skipped = (diffs, 0) if args.all else filter_reviewed(diffs)
    if args.markdown:
        args.markdown.write_text(markdown(kept, stats, skipped), encoding="utf-8")
    summary = defaultdict(int)
    for d in kept:
        summary[(d["list"], d["change"])] += 1
    for (lst, change), n in sorted(summary.items(), key=lambda kv: -kv[1]):
        print(f"{lst:16s} {change:8s} {n}")
    print(f"未审阅差异 {len(kept)} 条，已忽略 {skipped} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
