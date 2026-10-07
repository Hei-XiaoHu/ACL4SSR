#!/usr/bin/env python3
"""联网核对本地规则与当日上游列表的交互（离线回归无法覆盖的部分）。

用法：python3 tools/check_upstream.py

失败条件：
  1. Claude / AI 相关域名被 geosite:cn 收录：本地解析（UDP、fake-ip-filter、IP 规则）会改用国内 DNS，
     且 Stash 的 GEOSITE,cn 兜底可能把它判为直连。
  2. 排在广告规则之后的本地 AI 域名（rules/ai.txt）被广告源整域拦截：
     会被 REJECT 而不是走 AI。需要的端点应挪进 rules/ai-essential.txt。
  3. 本地直连/游戏/代理补充条目（rules/direct.txt、game-proxy.txt、proxy.txt、bilibili.txt）被广告源拦截。
广告源只拦截某个子域（如 Intercom 的分析上报）属预期，不算失败。
"""
from __future__ import annotations

import concurrent.futures
import sys
import urllib.request

import yaml

import build

GEO = "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite"
SOURCES = {
    "geosite:cn": (f"{GEO}/cn.yaml", "yaml"),
    "AdRules": ("https://raw.githubusercontent.com/Cats-Team/AdRules/main/adrules_domainset.txt", "text"),
    "anti-AD": ("https://anti-ad.net/domains.txt", "text"),
    "AWAvenue": ("https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/main/Filters/AWAvenue-Ads-Rule-Clash.yaml", "yaml"),
}
# anti-AD 的纯域名在 mihomo/Stash 中按后缀生效；AWAvenue 与 cn 的无前缀条目为精确匹配
SUFFIX_PLAIN = {"anti-AD"}


def fetch(name: str) -> tuple[set[str], set[str]]:
    url, kind = SOURCES[name]
    req = urllib.request.Request(url, headers={"User-Agent": "ACL4SSR-upstream-check"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8", "replace")
    rows = yaml.safe_load(body)["payload"] if kind == "yaml" else [
        line.strip() for line in body.splitlines() if line.strip() and not line.startswith(("#", "!"))
    ]
    exact, suffix = set(), set()
    for row in rows:
        row = str(row).strip().lower()
        if row.startswith("+."):
            suffix.add(row[2:])
        elif row.startswith("."):
            suffix.add(row[1:])
        elif name in SUFFIX_PLAIN:
            suffix.add(row)
        else:
            exact.add(row)
    return exact, suffix


def covers(lists: tuple[set[str], set[str]], domain: str) -> str | None:
    """返回覆盖该域名（自身或其父域）的条目；只拦子域的不算。"""
    exact, suffix = lists
    host = domain[2:] if domain.startswith("+.") else domain
    if host in exact and not domain.startswith("+."):
        return host
    labels = host.split(".")
    for i in range(len(labels) - 1):
        parent = ".".join(labels[i:])
        if parent in suffix:
            return f"+.{parent}"
    return None


def local(name: str) -> list[str]:
    return [d.lower() for d in build.local_rows(name)]


def main() -> int:
    with concurrent.futures.ThreadPoolExecutor(len(SOURCES)) as pool:
        data = dict(zip(SOURCES, pool.map(fetch, SOURCES)))
    problems = []
    ai_like = {n: local(n) for n in ("ai-essential", "ai", "auth", "telemetry")}
    for name, domains in ai_like.items():
        for domain in domains:
            hit = covers(data["geosite:cn"], domain)
            if hit:
                problems.append(f"[cn] {name}: {domain} 被 geosite:cn 的 {hit} 收录")
    after_ads = {n: local(n) for n in ("ai", "direct", "game-proxy", "proxy", "bilibili")}
    for source in ("AdRules", "anti-AD", "AWAvenue"):
        for name, domains in after_ads.items():
            for domain in domains:
                hit = covers(data[source], domain)
                if hit:
                    problems.append(f"[广告] {name}: {domain} 被 {source} 的 {hit} 拦截")
    # 仅提示：essential 被广告源收录是预期（它排在广告前），列出来便于了解覆盖关系
    for source in ("AdRules", "anti-AD", "AWAvenue"):
        for domain in ai_like["ai-essential"]:
            hit = covers(data[source], domain)
            if hit:
                print(f"i {domain} 也在 {source}（{hit}），由排在广告前的 ai-essential 放行到 AI")
    if problems:
        print("\n".join(problems))
        return 1
    print("✓ Claude/AI 域名均不在 geosite:cn；广告之后的 AI 与游戏补充条目未被广告源整域拦截")
    return 0


if __name__ == "__main__":
    sys.exit(main())
