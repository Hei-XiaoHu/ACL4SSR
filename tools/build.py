#!/usr/bin/env python3
"""从 src/spec.yaml 生成全部客户端配置。

用法：
  python3 tools/build.py          生成/覆盖输出文件
  python3 tools/build.py --check  只检查输出是否与源头一致（CI 用），不一致时退出码 1
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "src" / "spec.yaml"
TARGETS = ("meta", "stash")
GEO = "MetaCubeX/meta-rules-dat@meta/geo"
RAW_SELF = "https://raw.githubusercontent.com/Hei-XiaoHu/ACL4SSR/master"

S = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
CDN = S["cdn"]
GENERATED = "本文件由 tools/build.py 从 src/spec.yaml 生成，请勿手改；改规则请改 src/spec.yaml"


# ---------------------------------------------------------------- 节点筛选正则
def _expand(match: str) -> str:
    # {XX} -> 前后不挨英文字母的 XX
    return re.sub(r"\{([A-Za-z]+)\}", r"(?<![A-Za-z])\1(?![A-Za-z])", match)


EXCL = f"^(?!.*({S['node_exclude']}))"
NODES_RE = EXCL + ".*"
REGION_RE = {r["name"]: f"{EXCL}.*({_expand(r['match'])})" for r in S["regions"]}
REGIONS = [r["name"] for r in S["regions"]]


# ---------------------------------------------------------------- 规则集
def _provider(name: str, spec: dict, target: str) -> dict | None:
    if target in spec:
        spec = spec[target]
    elif any(t in spec for t in TARGETS):
        return None  # 仅对其他客户端生效
    ext_mrs = target == "meta"
    if "geosite" in spec or "geoip" in spec:
        kind = "geosite" if "geosite" in spec else "geoip"
        behavior = "domain" if kind == "geosite" else "ipcidr"
        fmt, ext = ("mrs", "mrs") if ext_mrs else ("yaml", "yaml")
        url = f"{CDN}/{GEO}/{kind}/{spec[kind]}.{ext}"
    elif "acl" in spec:
        behavior, fmt, ext = "classical", "text", "list"
        url = f"{CDN}/ACL4SSR/ACL4SSR@master/{spec['acl']}"
    elif "self" in spec:
        behavior, fmt, ext = "classical", "yaml", "yaml"
        url = f"{CDN}/{S['self_repo']}/{spec['self']}"
    else:
        behavior, fmt = spec["behavior"], spec["format"]
        ext = {"mrs": "mrs", "yaml": "yaml", "text": "list"}[fmt]
        url = spec["url"].replace("{cdn}", CDN)
    return {
        "type": "http",
        "behavior": behavior,
        "format": fmt,
        "interval": S["provider_interval"],
        "path": f"./ruleset/{name}.{ext}",
        "url": url,
    }


def providers(target: str) -> dict:
    out = {}
    for name, spec in S["providers"].items():
        p = _provider(name, spec, target)
        if p:
            out[name] = p
    return out


def render_rules(rule_list: list, target: str, avail: dict) -> list[str]:
    out = []
    for r in rule_list:
        if r.get("only") and r["only"] != target:
            continue
        if "raw" in r:
            out.append(r["raw"])
            continue
        if r["set"] not in avail:
            continue
        line = f"RULE-SET,{r['set']},{r['to']}"
        if r.get("no_resolve"):
            line += ",no-resolve"
        out.append(line)
    return out


def rules(target: str) -> list[str]:
    avail = providers(target)
    out = []
    if target == "stash":
        # Stash 无 mihomo 的 "nameserver#组" 语法：follow-rule + 把 DoH IP 指向 🛰️ DNS-Proxy 等价实现
        for u in S["dns_remote"]:
            ip = re.match(r"https://([\d.]+)/", u).group(1)
            out.append(f"IP-CIDR,{ip}/32,🛰️ DNS-Proxy,no-resolve")
    out += render_rules(S["rules"], target, avail)
    # 引用的规则集必须存在
    used = set(re.findall(r"RULE-SET,([^,)]+)", "\n".join(out)))
    missing = used - set(avail)
    if missing:
        sys.exit(f"[{target}] rules 引用了未定义的规则集: {sorted(missing)}")
    return out


# ---------------------------------------------------------------- 策略组
def _members(g: dict) -> list:
    items = []
    for p in g["proxies"]:
        if p == "$regions":
            items += [("name", n) for n in REGIONS]
        elif p == "$nodes":
            items.append(("regex", NODES_RE))
        else:
            items.append(("name", p))
    return items


def _all_groups() -> list[dict]:
    out = []
    for g in S["groups"]:
        if g == "$regions":
            for r in S["regions"]:
                out.append({"name": r["name"], "type": "url-test", "region": True, "tolerance": r["tolerance"]})
        else:
            out.append(g)
    return out


def xboard_groups() -> list[dict]:
    """Xboard：/正则/i 为节点筛选；不含正则的组 Xboard 会自动追加全部节点，用 /^$/ 阻止。"""
    out = []
    for g in _all_groups():
        typ = g.get("type", "select")
        if g.get("region"):
            proxies = [f"/{REGION_RE[g['name']]}/i", "REJECT"]  # REJECT 保活：无匹配节点时组不被删除
        else:
            proxies = []
            for kind, v in _members(g):
                proxies.append(f"/{v}/i" if kind == "regex" else v)
            if not any(k == "regex" for k, _ in _members(g)):
                proxies.append("/^$/")  # 不匹配任何节点
        d = {"name": g["name"], "type": typ}
        if typ == "url-test":
            d |= {"url": S["test_url"], "interval": S["test_interval"], "tolerance": g.get("tolerance", 50), "lazy": True}
        d["proxies"] = proxies
        out.append(d)
    return out


def ini_groups() -> list[str]:
    out = []
    for g in _all_groups():
        typ = g.get("type", "select")
        if g.get("region"):
            parts = [f"(?i){REGION_RE[g['name']]}"]
        else:
            parts = [f"(?i){v}" if k == "regex" else f"[]{v}" for k, v in _members(g)]
        line = f"custom_proxy_group={g['name']}`{typ}`" + "`".join(parts)
        if typ == "url-test":
            line += f"`{S['test_url']}`{S['test_interval']},,{g.get('tolerance', 50)}"
        out.append(line)
    return out


# ---------------------------------------------------------------- 全局与 DNS
def fake_ip_filter() -> list:
    return list(S["fake_ip_filter"])


def meta_general() -> dict:
    return {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "find-process-mode": "off",
        "tcp-concurrent": True,
        "unified-delay": True,
        "external-controller": "127.0.0.1:9090",
        "profile": {"store-selected": True, "store-fake-ip": True},
    }


def meta_sniffer() -> dict:
    return {
        "sniffer": {
            "enable": True,
            "force-dns-mapping": True,
            "parse-pure-ip": True,
            "override-destination": False,
            "sniff": {
                "HTTP": {"ports": [80, "8080-8880"]},
                "TLS": {"ports": [443, 8443]},
                "QUIC": {"ports": [443, 8443]},
            },
            "skip-domain": ["+.push.apple.com", "Mijia Cloud"],
        }
    }


def meta_dns() -> dict:
    china = S["dns_china"]
    return {
        "dns": {
            "enable": True,
            "listen": "127.0.0.1:1053",
            "ipv6": False,
            "prefer-h3": False,
            "respect-rules": True,
            "use-hosts": True,
            "use-system-hosts": True,
            "cache-algorithm": "arc",
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "fake-ip-filter-mode": "blacklist",
            "fake-ip-filter": fake_ip_filter(),
            "default-nameserver": S["dns_bootstrap"],
            "nameserver": [f"{u}#🛰️ DNS-Proxy" for u in S["dns_remote"]],
            "proxy-server-nameserver": china,
            "direct-nameserver": china,
            "direct-nameserver-follow-policy": False,
            "nameserver-policy": {"rule-set:private": ["system"], "rule-set:cn": china},
        }
    }


def stash_general() -> dict:
    return {
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "profile": {"store-selected": True, "store-fake-ip": True},
    }


def stash_dns() -> dict:
    return {
        "dns": {
            "enable": True,
            "ipv6": False,
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            # Stash 不保证支持中间位置的 * 通配，只保留无 * 的条目
            "fake-ip-filter": [x for x in fake_ip_filter() if "*" not in x],
            "follow-rule": True,
            "default-nameserver": S["dns_bootstrap"],
            "nameserver": S["dns_remote"],
            "nameserver-policy": {"geosite:cn": S["dns_china"]},  # 需 Stash iOS 3.4.0+
        }
    }


# ---------------------------------------------------------------- YAML 输出
def _dump(obj, flow=False) -> str:
    return yaml.safe_dump(
        obj, allow_unicode=True, sort_keys=False, width=100000,
        default_flow_style=None if flow else False,
    )


def _comment(lines: list[str], mark="#") -> str:
    return "".join(f"{mark} {l}".rstrip() + "\n" for l in lines)


def yaml_doc(header: list[str], *sections: tuple[str, str]) -> str:
    out = _comment(header)
    for note, body in sections:
        out += "\n"
        if note:
            out += _comment(note.splitlines())
        out += body
    return out


def full_config(target: str, *, with_groups: bool, final: bool) -> list[tuple[str, str]]:
    gen, dns = (meta_general(), meta_dns()) if target == "meta" else (stash_general(), stash_dns())
    sec = [("", _dump(gen))]
    if target == "meta":
        sec.append(("嗅探：浏览器自带 DoH 或直接按 IP 连接时，从 TLS/QUIC/HTTP 握手中取回域名再分流", _dump(meta_sniffer())))
    sec.append(("", _dump(dns)))
    if with_groups:
        sec.append(("节点由 Xboard 注入", "proxies: []\n"))
        sec.append(("", _dump({"proxy-groups": xboard_groups()})))
    sec.append(("", _dump({"rule-providers": providers(target)}, flow=True)))
    r = rules(target)
    if not final:
        r = [x for x in r if not x.startswith("MATCH,")]  # FINAL 由 ini 生成
    sec.append(("", _dump({"rules": r})))
    return sec


HDR_META = [
    "规则：MetaCubeX/meta-rules-dat（v2fly 社区，每日同步）mrs 二进制规则集，匹配快、内存小",
    "去广告：AdRules + anti-AD（mrs）；QUIC 走代理时拒绝，自动回落 TCP",
    "DNS：国外域名经 🛰️ DNS-Proxy 组走 1.1.1.1 / 8.8.8.8 DoH；国内域名与节点域名用国内 DoH",
    "安全：allow-lan 关闭，DNS 仅监听 127.0.0.1；find-process-mode off（无进程规则，省 CPU）",
    f"规则 CDN 为 {CDN}，失效时全局替换为 https://fastly.jsdelivr.net/gh",
]
HDR_STASH = [
    "规则：MetaCubeX/meta-rules-dat 的 yaml 版（Stash 不支持 mrs）；国内域名用 ACL4SSR ChinaDomain + GEOIP,CN",
    "  （geosite:cn 文本版 11 万行，iOS 网络扩展约 50MB 内存上限装不下）",
    "去广告：AWAvenue 秋风规则（约 900 条，含广告+隐私跟踪+流氓推广）",
    "DNS：follow-rule + 规则把 DoH IP 指向 🛰️ DNS-Proxy，等价 mihomo 的 nameserver#组；nameserver-policy 的 geosite 需 Stash iOS 3.4.0+",
    f"规则 CDN 为 {CDN}，失效时全局替换为 https://fastly.jsdelivr.net/gh",
]


def xboard(target: str) -> str:
    name = "custom.clashmeta.yaml" if target == "meta" else "custom.stash.yaml"
    who = "Clash Meta / mihomo（Clash Party、CMFA 等）" if target == "meta" else "Stash（iOS / macOS）"
    hdr = [f"Xboard 订阅模板 - {who}（{name}）", GENERATED,
           "策略组内 /正则/i 为 Xboard 侧节点筛选；/^$/ 表示不追加任何节点", *(HDR_META if target == "meta" else HDR_STASH)]
    return yaml_doc(hdr, *full_config(target, with_groups=True, final=True))


def base(target: str) -> str:
    ini = "ACL4SSR_Online_Full_AdblockPlus.ini" if target == "meta" else "ACL4SSR_Online_Full_AdblockPlus_Stash.ini"
    hdr = [f"subconverter 底包（{'mihomo' if target == 'meta' else 'Stash'}），需配合 {ini} 使用（依赖其中的策略组）",
           GENERATED, "MATCH 兜底由 ini 生成，排在本文件 rules 之后", *(HDR_META if target == "meta" else HDR_STASH)]
    return yaml_doc(hdr, *full_config(target, with_groups=False, final=False))


def ini(target: str) -> str:
    base_name = "dns_enhanced.yml" if target == "meta" else "dns_enhanced_stash.yml"
    lines = [
        "[custom]",
        f";{GENERATED}",
        f";acl4SSR规则 - Full_AdblockPlus（{'mihomo' if target == 'meta' else 'Stash / iOS'}）",
        f";全部分流规则在底包 {base_name} 的 rule-providers 中，本 ini 仅提供策略组与 FINAL 兜底",
        "",
        "ruleset=🐟 漏网之鱼,[]FINAL",
        "",
        *ini_groups(),
        "",
        "enable_rule_generator=true",
        "overwrite_original_rules=false",
        "",
        # 由 subconverter 服务端拉取，直接用 GitHub 原地址，改动即时生效
        f"clash_rule_base={RAW_SELF}/Clash/customBaseConfigs/{base_name}",
    ]
    return "\n".join(lines) + "\n"


def overseas() -> str:
    o = S["overseas"]
    dns = dict(o["dns"])
    dns["fake-ip-filter"] = fake_ip_filter()
    r = render_rules(o["rules"], "meta", providers("meta"))
    hdr = [
        "Clash Party 远程覆写 · 国外模式", GENERATED,
        "效果：AI 走 💬 Ai平台（自己选节点），广告拦截，其余全部直连；DNS 整段换成国外 DoH，不含任何国内 DNS",
        "用法：Clash Party → 覆写 → 导入远程链接：",
        f"  {CDN}/{S['self_repo']}/Clash/override/overseas.yaml",
        "  然后在订阅的「编辑信息」里勾选此覆写；回国后取消勾选即可",
        "前提：设置里关闭「控制 DNS 设置」，否则软件自身 DNS 设置优先级更高，本文件的 dns! 不生效",
        "+rules 插在原规则最前面；dns! 强制整段替换",
    ]
    return yaml_doc(hdr, ("", _dump({"+rules": r})), ("", _dump({"dns!": dns})))


OUTPUTS = {
    "Clash/config/ACL4SSR_Online_Full_AdblockPlus.ini": lambda: ini("meta"),
    "Clash/config/ACL4SSR_Online_Full_AdblockPlus_Stash.ini": lambda: ini("stash"),
    "Clash/customBaseConfigs/dns_enhanced.yml": lambda: base("meta"),
    "Clash/customBaseConfigs/dns_enhanced_stash.yml": lambda: base("stash"),
    "Xboard/custom.clashmeta.yaml": lambda: xboard("meta"),
    "Xboard/custom.stash.yaml": lambda: xboard("stash"),
    "Clash/override/overseas.yaml": overseas,
}


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for rel, fn in OUTPUTS.items():
        path = ROOT / rel
        text = fn()
        yaml.safe_load(text) if not rel.endswith(".ini") else None  # 自检：输出必须是合法 YAML
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        stale.append(rel)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if check and stale:
        print("以下文件与 src/spec.yaml 不一致，请运行 python3 tools/build.py 并提交：")
        print("\n".join(f"  {s}" for s in stale))
        return 1
    print(("已是最新" if not stale else "已生成：\n" + "\n".join(f"  {s}" for s in stale)) if not check else "一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
