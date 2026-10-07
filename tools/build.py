#!/usr/bin/env python3
"""从 src/spec.yaml 生成全部客户端配置。

用法：
  python3 tools/build.py          生成/覆盖输出文件
  python3 tools/build.py --check  只检查输出是否与源头一致（CI 用），不一致时退出码 1
"""
from __future__ import annotations

import copy
import ipaddress
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "src" / "spec.yaml"
TARGETS = ("meta", "stash")
RULES_DIR = ROOT / "rules"

S = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
CDN = S["cdn"]
REPO = S["repo"]
RAW_SELF = f"https://raw.githubusercontent.com/{REPO}/master"
RULES_BASE = f"{CDN}/{REPO}@{S['rules_branch']}"
OUT_DIR = {"meta": "mihomo", "stash": "stash"}  # rules 分支内的子目录
GENERATED = "本文件由 tools/build.py 从 src/spec.yaml 生成，请勿手改；改规则请改 src/spec.yaml"


DNS_GROUP = S["dns_group"]

# ---------------------------------------------------------------- 节点筛选正则
NODES_RE = f"^(?!.*({S['node_exclude']})).*"


# ---------------------------------------------------------------- 规则集
SETS = {item["name"]: item for item in S["sets"] if isinstance(item, dict) and "name" in item}


def set_type(name: str) -> str:
    return SETS[name].get("type", "domain")


def local_rows(name: str) -> list[str]:
    """rules/<name>.txt：每行一条，# 注释；domain 用 x / +.x，classical 另可 regex:，ip 为 CIDR。"""
    path = RULES_DIR / f"{name}.txt"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("regex:") and set_type(name) != "classical":
            sys.exit(f"rules/{name}.txt: 只有 classical 集合允许 regex: 条目：{line}")
        if set_type(name) == "ip":
            ipaddress.ip_network(line, strict=False)
        elif not line.startswith("regex:") and not re.fullmatch(r"(\+\.)?[a-z0-9*_-]+(\.[a-z0-9*_-]+)*", line):
            sys.exit(f"rules/{name}.txt: 无法识别的条目：{line}")
        rows.append(line)
    return rows


def classical_line(row: str) -> str:
    if row.startswith("regex:"):
        return f"DOMAIN-REGEX,{row[6:]}"
    if row.startswith("+."):
        return f"DOMAIN-SUFFIX,{row[2:]}"
    return f"DOMAIN,{row}"


def sources(name: str, target: str) -> list[str]:
    src = SETS[name].get("from", [])
    return list(src.get(target, [])) if isinstance(src, dict) else list(src)


def native_rules(name: str, target: str) -> list[str]:
    """Stash 用原生 GEOSITE/GEOIP 代替的来源。"""
    if target != "stash":
        return []
    return [S["stash_native"][src] for src in sources(name, target) if src in S["stash_native"]]


def fetched_sources(name: str, target: str) -> list[str]:
    native = S["stash_native"] if target == "stash" else {}
    return [src for src in sources(name, target) if src not in native]


def has_provider(name: str, target: str) -> bool:
    return bool(local_rows(name) or fetched_sources(name, target))


def provider_file(name: str, target: str) -> str:
    ext = "yaml" if target == "stash" or set_type(name) == "classical" else "mrs"
    return f"{OUT_DIR[target]}/{name}.{ext}"


def providers(target: str) -> dict:
    out = {}
    for name in SETS:
        if not has_provider(name, target):
            continue
        rel = provider_file(name, target)
        behavior = {"domain": "domain", "ip": "ipcidr", "classical": "classical"}[set_type(name)]
        out[name] = {
            "type": "http",
            "behavior": behavior,
            "format": rel.rsplit(".", 1)[1],
            "interval": S["provider_interval"],
            "path": f"./ruleset/{rel.split('/', 1)[1]}",
            "url": f"{RULES_BASE}/{rel}",
        }
    return out


def _logical(kind: str, *children: str) -> str:
    return f"({kind},({','.join(children)}))"


def _any(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else _logical("OR", *parts)


def _leaf(name: str, target: str) -> str:
    """集合在逻辑规则中的条件：RULE-SET 与 Stash 原生规则取并集；IP 集合不额外解析。"""
    suffix = ",no-resolve" if set_type(name) == "ip" else ""
    parts = [f"(RULE-SET,{name}{suffix})"] if has_provider(name, target) else []
    parts += [f"({rule}{suffix})" for rule in native_rules(name, target)]
    if not parts:
        sys.exit(f"[{target}] 逻辑规则引用的集合没有任何来源: {name}")
    return _any(parts)


def quic_rule(target: str) -> str:
    services = [_leaf(n, target) for n in S["quic_reject"]]
    services += [_leaf(n, target) for n in S["quic_reject_ip"]]
    # 正向域名白名单是关键：未知目标和纯 IP 不会因缺少 cn 域名而被拒绝。
    # cn 含“国内 DNS 更优”的国外站；与路由一样，明确的境外归属优先。
    domestic = _logical("AND", _leaf("cn", target), _logical("NOT", _leaf("foreign", target)))
    exemptions = _any([_leaf(n, target) for n in S["quic_exempt"]])
    # Stash 能识别 QUIC 协议，只拦真正的 QUIC（任意端口），游戏自定义 UDP 不受影响；
    # mihomo 没有协议规则，用 UDP443 近似。
    transport = "(PROTOCOL,QUIC)" if target == "stash" else "(DST-PORT,443)"
    expression = _logical(
        "AND", "(NETWORK,udp)", transport, _any(services),
        _logical("NOT", domestic), _logical("NOT", _leaf("cn-ip", target)), _logical("NOT", exemptions),
    )
    return expression[1:-1] + ",REJECT"


def rules(target: str) -> list[str]:
    out = []
    if target == "stash":
        # Stash 用 follow-rule + DoH 端点 IP 规则指定出站（该 IP 的其他流量也受影响）
        for u in S["dns_remote"]:
            ip = re.match(r"https://([\d.]+)/", u).group(1)
            out.append(f"IP-CIDR,{ip}/32,{DNS_GROUP},no-resolve")
    for item in S["sets"]:
        if item == "quic":
            out.append(quic_rule(target))
        elif "match" in item:
            out.append(f"MATCH,{item['match']}")
        elif item.get("to"):
            name, to = item["name"], item["to"]
            ip_suffix = ",no-resolve" if item.get("no_resolve") and set_type(name) == "ip" else ""
            if has_provider(name, target):
                out.append(f"RULE-SET,{name},{to}{ip_suffix}")
            out += [f"{rule},{to}{ip_suffix}" for rule in native_rules(name, target)]
    return out


# ---------------------------------------------------------------- 策略组
def _members(g: dict) -> list:
    return [("regex", NODES_RE) if p == "$nodes" else ("name", p) for p in g["proxies"]]


def xboard_groups() -> list[dict]:
    """Xboard：/正则/i 为节点筛选；不含正则的组 Xboard 会自动追加全部节点，用 /^$/ 阻止。"""
    out = []
    for g in S["groups"]:
        typ = g.get("type", "select")
        # REJECT 保活：无匹配节点时自动选择组不被删除
        proxies = [f"/{v}/i" if kind == "regex" else v for kind, v in _members(g)]
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
    for g in S["groups"]:
        typ = g.get("type", "select")
        parts = [f"(?i){v}" if k == "regex" else f"[]{v}" for k, v in _members(g)]
        line = f"custom_proxy_group={g['name']}`{typ}`" + "`".join(parts)
        if typ == "url-test":
            line += f"`{S['test_url']}`{S['test_interval']},,{g.get('tolerance', 50)}"
        out.append(line)
    return out


# ---------------------------------------------------------------- 全局与 DNS
def fake_ip_filter() -> list:
    return list(dict.fromkeys([*S["dns_system_domains"], *S["fake_ip_filter"]]))


def dns_policy(target: str, *, overseas: bool = False) -> dict:
    """只含“内网 → system”与“已知国内 → 国内 DoH”；未命中的域名走主 nameserver（境外）。

    不放任何境外条目：mihomo 的 DIRECT 出站共享本 policy（follow-policy），
    未命中时回到国内 direct-nameserver，直连下载不会被送去境外 DNS。
    """
    policy = {domain: ["system"] for domain in S["dns_system_domains"]}
    if target == "meta":
        policy = {"rule-set:private": ["system"], **policy}
    else:
        policy["geosite:private"] = ["system"]
    if overseas:
        return policy
    china = S["dns_china"]
    if target == "stash":
        # Stash 没有 direct-nameserver：默认直连但不在 cn 里的下载集合单独指定国内 DNS
        for item in S["stash_dns_china"]:
            if item.startswith("geosite:"):
                if "@" in item:
                    sys.exit(f"Stash DNS 未确认支持 geosite 属性标签: {item}")
                policy[item] = china
                continue
            for domain in local_rows(item):
                if domain in policy and policy[domain] != china:
                    sys.exit(f"DNS policy 冲突: {domain}")
                policy[domain] = china
    policy["rule-set:cn" if target == "meta" else "geosite:cn"] = china
    return policy


def meta_general() -> dict:
    return copy.deepcopy(S["clients"]["meta"]["general"])


def meta_sniffer() -> dict:
    return {"sniffer": copy.deepcopy(S["clients"]["meta"]["sniffer"])}


def meta_dns() -> dict:
    china = S["dns_china"]
    dns = copy.deepcopy(S["clients"]["meta"]["dns"])
    dns.update({
        "fake-ip-filter": fake_ip_filter(),
        "default-nameserver": S["dns_bootstrap"],
        "nameserver": [f"{u}#{DNS_GROUP}" for u in S["dns_remote"]],
        "proxy-server-nameserver": china,
        "direct-nameserver": china,
        "nameserver-policy": dns_policy("meta"),
    })
    return {"dns": dns}


def stash_general() -> dict:
    return copy.deepcopy(S["clients"]["stash"]["general"])


def stash_dns() -> dict:
    dns = copy.deepcopy(S["clients"]["stash"]["dns"])
    dns.update({
        "fake-ip-filter": fake_ip_filter(),
        "default-nameserver": S["dns_bootstrap"],
        "nameserver": S["dns_remote"],
        "nameserver-policy": dns_policy("stash"),  # 需 Stash iOS 3.4.0+
    })
    return {"dns": dns}


# ---------------------------------------------------------------- YAML 输出
class _NoAliasDumper(yaml.SafeDumper):
    """不输出 &id/*id 锚点别名：Stash 等客户端无法正确展开。"""

    def ignore_aliases(self, data):
        return True


def _dump(obj, flow=False) -> str:
    return yaml.dump(
        obj, Dumper=_NoAliasDumper, allow_unicode=True, sort_keys=False, width=100000,
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
    f"规则：本仓库 rules 分支（每日合并本地 rules/*.txt 与 MetaCubeX 等上游）mrs 二进制规则集，匹配快、内存小",
    "去广告：AdRules + anti-AD 合并去重；默认走代理的境外 UDP443 回落 TCP，默认直连/国内/游戏/下载/未知 IP 保留",
    "DNS：已知国内走国内 DoH，其余经 🛰️ DNS 查境外 DoH，内网用系统 DNS；DIRECT 出站用国内 direct-nameserver",
    "安全：allow-lan 关闭，DNS 仅监听 127.0.0.1；find-process-mode always（仅用于连接列表显示应用名）",
    f"规则 CDN 为 {CDN}，失效时全局替换为 https://cdn.jsdelivr.net/gh",
]
HDR_STASH = [
    "规则：本仓库 rules 分支的 domain/ipcidr yaml；国内外兜底复用 Stash 原生 GEOSITE + GEOIP,CN",
    "  （不额外下载全量 cn/geolocation-!cn 文本）",
    "去广告：AWAvenue 秋风规则（约 900 条，含广告+隐私跟踪+流氓推广）",
    "DNS：follow-rule + DoH 端点 IP 绑定 🛰️ DNS；内网系统 DNS，已知国内与游戏下载走国内 DoH，其余境外 DoH",
    "geosite DNS policy 需 Stash iOS 3.4.0+；GEOSITE 数据首次从 GitHub 按需加载，请确保 GitHub 可达",
    f"规则 CDN 为 {CDN}，失效时全局替换为 https://cdn.jsdelivr.net/gh",
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


def overseas_dns() -> dict:
    """国外模式：与主配置同一份 DNS，只把国内服务器全部换成境外 DoH/DoT。"""
    o = S["overseas"]
    dns = meta_dns()["dns"]
    dns.update({
        "default-nameserver": o["dns_bootstrap"],
        "nameserver": [f"{u}#{DNS_GROUP}" for u in o["dns"]],
        "proxy-server-nameserver": o["dns"],
        "direct-nameserver": o["dns"],
        "nameserver-policy": dns_policy("meta", overseas=True),
    })
    return dns


def overseas() -> str:
    hdr = [
        "Clash Party 远程覆写 · 国外模式（仅海外电脑）", GENERATED,
        "效果：分流规则与策略组完全不变；DNS 中所有国内服务器换成 Cloudflare / Google 的 DoH + DoT",
        "  主 DNS 仍经 🛰️ DNS 组发出（想更快可在面板把该组切到 DIRECT）；内网仍走 system",
        "用法：Clash Party → 覆写 → 导入远程链接：",
        f"  {CDN}/{REPO}@master/Clash/override/overseas.yaml",
        "  然后在订阅的「编辑信息」里勾选此覆写",
        "前提：设置里关闭「控制 DNS 设置」，否则软件自身 DNS 设置优先级更高，本文件的 dns! 不生效",
        "dns! 强制整段替换",
    ]
    return yaml_doc(hdr, ("", _dump({"dns!": overseas_dns()})))


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
        if not rel.endswith(".ini"):
            yaml.safe_load(text)  # 自检：输出必须是合法 YAML
            if re.search(r"[&*]id\d+", text):
                sys.exit(f"{rel}: 输出含 YAML 锚点/别名，Stash 不支持")
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
