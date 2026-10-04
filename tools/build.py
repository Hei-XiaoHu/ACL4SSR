#!/usr/bin/env python3
"""从 src/spec.yaml 生成全部客户端配置。

用法：
  python3 tools/build.py          生成/覆盖输出文件
  python3 tools/build.py --check  只检查输出是否与源头一致（CI 用），不一致时退出码 1
"""
from __future__ import annotations

import copy
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
        behavior, fmt, ext = spec.get("behavior", "classical"), "yaml", "yaml"
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


def quic_rule(target: str, avail: dict) -> str:
    def leaf(name):
        if target == "stash" and name == "geolocation-!cn":
            return "(GEOSITE,geolocation-!cn)"
        if name not in avail or avail[name]["behavior"] not in ("domain", "classical"):
            sys.exit(f"[{target}] QUIC 集合不存在或不含域名: {name}")
        return f"(RULE-SET,{name})"

    def logical(kind, *children):
        return f"({kind},({','.join(children)}))"

    services = logical("OR", *(leaf(name) for name in S["quic_reject_sets"]))
    ip_services = []
    for name in S["quic_reject_ip_sets"]:
        if name not in avail or avail[name]["behavior"] != "ipcidr":
            sys.exit(f"[{target}] QUIC IP 集合不存在或不是 ipcidr: {name}")
        ip_services.append(f"(RULE-SET,{name},no-resolve)")
    if ip_services:
        services = logical("OR", services, *ip_services)
    # 正向域名白名单是关键：未知目标和纯 IP 不会因缺少 cn 域名而被拒绝。
    china_domain = "(RULE-SET,cn)" if target == "meta" else "(GEOSITE,cn)"
    china_ip = "(RULE-SET,cn-ip,no-resolve)" if target == "meta" else "(GEOIP,CN,no-resolve)"
    # cn 含“国内 DNS 更优”的国外站；与路由/DNS 一样，明确 !cn 分类优先。
    domestic = logical("AND", china_domain, logical("NOT", leaf("geolocation-!cn")))
    exemptions = logical("OR", *(leaf(name) for name in S["quic_exempt_sets"]))
    # Stash 能识别 QUIC 协议，只拦真正的 QUIC（任意端口），游戏自定义 UDP 不受影响；
    # mihomo 没有协议规则，用 UDP443 近似。
    transport = "(PROTOCOL,QUIC)" if target == "stash" else "(DST-PORT,443)"
    expression = logical(
        "AND", "(NETWORK,udp)", transport, services,
        logical("NOT", domestic), logical("NOT", china_ip), logical("NOT", exemptions),
    )
    return expression[1:-1] + ",REJECT"


def render_rules(rule_list: list, target: str, avail: dict) -> list[str]:
    out = []
    for r in rule_list:
        if r.get("only") and r["only"] != target:
            continue
        if r.get("quic"):
            out.append(quic_rule(target, avail))
            continue
        if "raw" in r:
            out.append(r["raw"])
            continue
        if r["set"] not in avail:
            if r["set"] not in S["providers"]:
                sys.exit(f"[{target}] 未定义的源规则集: {r['set']}")
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
        # Stash 用 follow-rule + DoH 端点 IP 规则指定出站（该 IP 的其他流量也受影响）
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
            parts = [f"(?i){REGION_RE[g['name']]}", "[]REJECT"]
        else:
            parts = [f"(?i){v}" if k == "regex" else f"[]{v}" for k, v in _members(g)]
        line = f"custom_proxy_group={g['name']}`{typ}`" + "`".join(parts)
        if typ == "url-test":
            line += f"`{S['test_url']}`{S['test_interval']},,{g.get('tolerance', 50)}"
        out.append(line)
    return out


# ---------------------------------------------------------------- 全局与 DNS
def fake_ip_filter() -> list:
    return list(dict.fromkeys([*S["dns_system_domains"], *S["fake_ip_filter"]]))


def local_provider_domains(name: str) -> list[str]:
    """把本地 domain / classical DOMAIN 条目复用为 Stash DNS policy。"""
    spec = S["providers"][name]
    rows = yaml.safe_load((ROOT / spec["self"]).read_text(encoding="utf-8"))["payload"]
    if spec.get("behavior") == "domain":
        return rows
    domains = []
    for row in rows:
        kind, value = row.split(",", 1)
        if kind == "DOMAIN":
            domains.append(value)
        elif kind == "DOMAIN-SUFFIX":
            domains.append(f"+.{value}")
        else:
            sys.exit(f"{name}: DNS policy 无法表达 {row}，请使用精确域名/后缀")
    return domains


def dns_policy(target: str, *, overseas: bool = False) -> dict:
    policy = {domain: ["system"] for domain in S["dns_system_domains"]}
    if target == "meta":
        policy = {"rule-set:private": ["system"], **policy}
    else:
        policy["geosite:private"] = ["system"]
    if overseas:
        return policy
    remote = [f"{u}#🛰️ DNS-Proxy" for u in S["dns_remote"]] if target == "meta" else S["dns_remote"]
    local_names = [name for name in S["dns_remote_sets"] if "self" in S["providers"][name]]
    geo_names = [name for name in S["dns_remote_sets"] if name not in local_names]
    tagged = [name for name in S["dns_china_sets"] if "@" in S["providers"][name].get("geosite", "")]
    tag_cache = None
    if target == "stash" and tagged:
        tag_cache = yaml.safe_load((ROOT / S["stash_dns_cn_cache"]).read_text(encoding="utf-8"))
        if tag_cache["providers"] != tagged:
            sys.exit("Stash 国内 DNS 标签缓存源已改变，请运行 tools/update_stash_dns.py")
        for domain in tag_cache["payload"]:
            if domain in policy and policy[domain] != S["dns_china"]:
                sys.exit(f"DNS policy 冲突: {domain}")
            policy[domain] = S["dns_china"]
    # 明确代理例外 > 国内游戏标签 > 境外公司/娱乐集合 > cn。
    for name in [*local_names, *S["dns_china_sets"], *geo_names]:
        if target == "stash" and name in tagged:
            continue
        spec = S["providers"][name]
        servers = S["dns_china"] if name in S["dns_china_sets"] else remote
        if target == "meta":
            policy[f"rule-set:{name}"] = servers
        elif "self" in spec:
            for domain in local_provider_domains(name):
                if domain in policy and policy[domain] != servers:
                    sys.exit(f"DNS policy 冲突: {domain}")
                policy[domain] = servers
        else:
            geo = spec.get("meta", spec)["geosite"]
            policy[f"geosite:{geo}"] = servers
    policy["rule-set:cn" if target == "meta" else "geosite:cn"] = S["dns_china"]
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
        "nameserver": [f"{u}#🛰️ DNS-Proxy" for u in S["dns_remote"]],
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
    "规则：MetaCubeX/meta-rules-dat（v2fly 社区，每日同步）mrs 二进制规则集，匹配快、内存小",
    "去广告：AdRules + anti-AD（mrs）；默认走代理的境外 UDP443 回落 TCP，默认直连/国内/游戏/下载/未知 IP 保留",
    "DNS：AI/代理补充/已知国外域名优先走境外 DoH；国内用国内 DoH，内网用系统 DNS",
    "安全：allow-lan 关闭，DNS 仅监听 127.0.0.1；find-process-mode always（仅用于连接列表显示应用名）",
    f"规则 CDN 为 {CDN}，失效时全局替换为 https://fastly.jsdelivr.net/gh",
]
HDR_STASH = [
    "规则：MetaCubeX/meta-rules-dat 的 domain/ipcidr yaml；国内外兜底复用 Stash 原生 GEOSITE + GEOIP,CN",
    "  （与 geosite DNS policy 顺序对齐，不额外下载全量 cn/geolocation-!cn 文本）",
    "去广告：AWAvenue 秋风规则（约 900 条，含广告+隐私跟踪+流氓推广）",
    "DNS：follow-rule + DoH 端点 IP 绑定 🛰️ DNS-Proxy；内网系统 DNS、国外优先境外 DoH；geosite policy 需 Stash iOS 3.4.0+",
    "GEOSITE 数据首次从 GitHub 按需加载，请确保 GitHub 可达；少量国内属性标签已展开为 DNS 字面域名",
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
    dns["nameserver-policy"] = dns_policy("meta", overseas=True)
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
