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
# 客户端：meta = mihomo（Clash Party / CMFA），stash = Stash iOS/macOS。两者用同一份规则集，
# sets 里 clients: [meta] 表示 Stash 不生成（仅进程规则）。
TARGETS = ("meta", "stash")
RULES_DIR = ROOT / "rules"

S = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
CDN = S["cdn"]
REPO = S["repo"]
RAW_SELF = f"https://raw.githubusercontent.com/{REPO}/master"
RULES_BASE = f"{CDN}/{REPO}@{S['rules_branch']}"
RULES_SUBDIR = "mihomo"  # rules 分支内的目录（历史名称；Stash 也下载这里的文件，mrs 两边同格式）
GENERATED = "本文件由 tools/build.py 从 src/spec.yaml 生成，请勿手改；改规则请改 src/spec.yaml"


DNS_GROUP = S["dns_group"]

# ---------------------------------------------------------------- 节点筛选正则
NODES_RE = f"^(?!.*({S['node_exclude']})).*"


# ---------------------------------------------------------------- 规则集
SETS = {item["name"]: item for item in S["sets"] if isinstance(item, dict) and "name" in item}


def set_type(name: str) -> str:
    return SETS[name].get("type", "domain")


def enabled(name: str, target: str) -> bool:
    """集合是否在该客户端生成（clients 省略 = 全部客户端）。"""
    return target in SETS[name].get("clients", TARGETS)


def local_rows(name: str) -> list[str]:
    """rules/<name>.txt：每行一条，# 注释；domain 用 x / +.x，classical 另可 regex: / process:，ip 为 CIDR。"""
    path = RULES_DIR / f"{name}.txt"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("regex:", "process:")) and set_type(name) != "classical":
            sys.exit(f"rules/{name}.txt: 只有 classical 集合允许 regex: / process: 条目：{line}")
        if line.startswith("process:"):
            # 进程名（Windows 含 .exe）或安卓包名；mihomo 按不区分大小写的完整名称匹配
            if not re.fullmatch(r"process:[a-z0-9][a-z0-9._+-]*", line):
                sys.exit(f"rules/{name}.txt: 进程名只能用小写字母、数字与 ._+-：{line}")
        elif set_type(name) == "ip":
            ipaddress.ip_network(line, strict=False)
        elif not line.startswith("regex:") and not re.fullmatch(r"(\+\.)?[a-z0-9*_-]+(\.[a-z0-9*_-]+)*", line):
            sys.exit(f"rules/{name}.txt: 无法识别的条目：{line}")
        rows.append(line)
    return rows


def classical_line(row: str) -> str:
    if row.startswith("regex:"):
        return f"DOMAIN-REGEX,{row[6:]}"
    if row.startswith("process:"):
        return f"PROCESS-NAME,{row[8:]}"
    if row.startswith("+."):
        return f"DOMAIN-SUFFIX,{row[2:]}"
    return f"DOMAIN,{row}"


def sources(name: str, target: str) -> list[str]:
    return list(SETS[name].get("from", [])) if enabled(name, target) else []


def has_provider(name: str, target: str) -> bool:
    return enabled(name, target) and bool(local_rows(name) or sources(name, target))


def provider_file(name: str) -> str:
    # domain / ipcidr 用 mrs 二进制（mihomo；Stash iOS 3.1.1+ 同样支持），classical 只能 yaml
    ext = "yaml" if set_type(name) == "classical" else "mrs"
    return f"{RULES_SUBDIR}/{name}.{ext}"


def providers(target: str) -> dict:
    out = {}
    for name in SETS:
        if not has_provider(name, target):
            continue
        rel = provider_file(name)
        behavior = {"domain": "domain", "ip": "ipcidr", "classical": "classical"}[set_type(name)]
        out[name] = {
            "type": "http",
            "behavior": behavior,
            "format": rel.rsplit(".", 1)[1],
            "interval": S["provider_interval"],
            # 独立子目录（与 URL 同构）：与旧配置的缓存隔离，换配置时必定重新下载，
            # 不会读到旧版 Stash 配置缓存的小广告列表
            "path": f"./ruleset/acl4ssr/{rel}",
            "url": f"{RULES_BASE}/{rel}",
        }
    return out


def _logical(kind: str, *children: str) -> str:
    return f"({kind},({','.join(children)}))"


def _any(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else _logical("OR", *parts)


def _leaf(name: str, target: str) -> str:
    """集合在逻辑规则中的条件；IP 集合不额外解析。"""
    if not has_provider(name, target):
        sys.exit(f"[{target}] 逻辑规则引用的集合没有任何来源: {name}")
    return f"(RULE-SET,{name}{',no-resolve' if set_type(name) == 'ip' else ''})"


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
    policy = {"rule-set:private": ["system"], **{domain: ["system"] for domain in S["dns_system_domains"]}}
    if overseas:
        return policy
    china = S["dns_china"]
    if target == "stash":
        # Stash 没有 direct-nameserver：默认直连但不在 cn 里的集合整体指定国内 DNS。
        # rule-set: 引用需 Stash iOS 3.6+ / macOS 4.3+，与分流共用同一份规则集。
        for item in S["stash_dns_china"]:
            if not has_provider(item, target) or set_type(item) != "domain":
                sys.exit(f"stash_dns_china 只能引用 Stash 上有规则集的 domain 集合: {item}")
            policy[f"rule-set:{item}"] = china
    policy["rule-set:cn"] = china
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
        # 节点域名用国内 DNS 直连解析，不跟随 follow-rule（需 Stash iOS 3.6+）
        "proxy-server-nameserver": S["dns_china"],
        "nameserver-policy": dns_policy("stash"),  # rule-set: 需 3.6+
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
    "安全：allow-lan 关闭，DNS 仅监听 127.0.0.1；find-process-mode always（BT 客户端按进程直连，并在连接列表显示应用名）",
    f"规则 CDN 为 {CDN}，失效时全局替换为 https://cdn.jsdelivr.net/gh",
]
HDR_STASH = [
    "规则：与 mihomo 完全一致，下载 rules 分支同一批 mrs 规则集（含 AdRules + anti-AD 广告、cn、foreign、cn-ip）；",
    "  不使用 Stash 原生 GEOSITE/GEOIP；仅 BT 进程直连规则无法在 Stash 上实现",
    "内存：约 36 万条域名规则，iOS 网络扩展上限 50 MB，实机已确认可加载；隧道无故断开时查 iOS 分析数据里的 JetsamEvent",
    "DNS：follow-rule + DoH 端点 IP 绑定 🛰️ DNS；内网系统 DNS，cn 与直连集合走国内 DoH，其余境外 DoH；节点域名用 proxy-server-nameserver（国内）",
    "需 Stash iOS 3.6+ / macOS 4.3+（mrs 规则集、DNS policy 的 rule-set:、proxy-server-nameserver）",
    f"规则 CDN 为 {CDN}，失效时全局替换为 https://cdn.jsdelivr.net/gh",
]
HDR = {"meta": HDR_META, "stash": HDR_STASH}
LABEL = {"meta": "mihomo", "stash": "Stash"}


def xboard(target: str) -> str:
    name = {"meta": "custom.clashmeta.yaml", "stash": "custom.stash.yaml"}[target]
    who = {"meta": "Clash Meta / mihomo（Clash Party、CMFA 等）", "stash": "Stash（iOS / macOS）"}[target]
    hdr = [f"Xboard 订阅模板 - {who}（{name}）", GENERATED,
           "策略组内 /正则/i 为 Xboard 侧节点筛选；/^$/ 表示不追加任何节点", *HDR[target]]
    return yaml_doc(hdr, *full_config(target, with_groups=True, final=True))


INI_NAME = {"meta": "ACL4SSR_Online_Full_AdblockPlus.ini", "stash": "ACL4SSR_Online_Full_AdblockPlus_Stash.ini"}
BASE_NAME = {"meta": "dns_enhanced.yml", "stash": "dns_enhanced_stash.yml"}


def base(target: str) -> str:
    hdr = [f"subconverter 底包（{LABEL[target]}），需配合 {INI_NAME[target]} 使用（依赖其中的策略组）",
           GENERATED, "MATCH 兜底由 ini 生成，排在本文件 rules 之后", *HDR[target]]
    return yaml_doc(hdr, *full_config(target, with_groups=False, final=False))


def ini(target: str) -> str:
    base_name = BASE_NAME[target]
    lines = [
        "[custom]",
        f";{GENERATED}",
        f";acl4SSR规则 - Full_AdblockPlus（{LABEL[target] if target == 'meta' else LABEL[target] + ' / iOS'}）",
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
    "xboard/custom.clashmeta.yaml": lambda: xboard("meta"),
    "xboard/custom.stash.yaml": lambda: xboard("stash"),
    "Clash/override/overseas.yaml": overseas,
}


def validate_spec() -> list[str]:
    """spec 与 rules/ 的一致性自检（离线）。返回问题列表，空表示通过。

    重点防止“静默失效”：rules/ 下文件名拼错不会被任何集合读取；
    quic/DNS/watch 列表引用了不存在的集合或来源；去向写错组名。
    """
    problems = []
    names = [item["name"] for item in S["sets"] if isinstance(item, dict) and "name" in item]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        problems.append(f"sets 中集合重名: {dupes}")
    for path in sorted(RULES_DIR.glob("*")):
        if path.suffix != ".txt" or path.stem not in SETS:
            problems.append(f"rules/{path.name} 没有同名集合，不会被使用（检查文件名或 src/spec.yaml 的 sets）")
    groups = [g["name"] for g in S["groups"]]
    targets = set(groups) | {"DIRECT", "REJECT"}
    for g in S["groups"]:
        for p in g["proxies"]:
            if p != "$nodes" and p not in targets:
                problems.append(f"策略组 {g['name']} 引用了不存在的成员: {p}")
    if S["dns_group"] not in groups:
        problems.append(f"dns_group 不是已定义的策略组: {S['dns_group']}")
    markers = [item for item in S["sets"] if not isinstance(item, dict)]
    if markers != ["quic"]:
        problems.append(f"sets 中必须恰好有一个 quic 标记: {markers}")
    if not (isinstance(S["sets"][-1], dict) and "match" in S["sets"][-1]):
        problems.append("sets 最后一项必须是 {match: 组名} 兜底")
    for item in S["sets"]:
        if not isinstance(item, dict):
            continue
        to = item.get("match") or item.get("to")
        if to and to not in targets:
            problems.append(f"{item.get('name', 'match')}: 去向 {to} 不是已定义的策略组")
        if "name" in item:
            if item.get("type", "domain") not in ("domain", "ip", "classical"):
                problems.append(f"{item['name']}: 未知 type {item['type']}")
            if not set(item.get("clients", TARGETS)) <= set(TARGETS):
                problems.append(f"{item['name']}: clients 只能取 {TARGETS}")
            if any(r.startswith("process:") for r in local_rows(item["name"])) and "stash" in item.get("clients", TARGETS):
                problems.append(f"{item['name']}: 进程规则只用于 mihomo，需写 clients: [meta]（Stash iOS 不支持）")
            for target in TARGETS:
                for src in sources(item["name"], target):
                    kind = src.partition(":")[0]
                    if kind not in ("geosite", "geoip") and src not in S["upstream"]:
                        problems.append(f"{item['name']}: 未定义的上游 {src}")
            if not any(has_provider(item["name"], t) for t in TARGETS):
                problems.append(f"{item['name']}: 既没有 rules/{item['name']}.txt 也没有上游来源")
    for key in ("quic_reject", "quic_reject_ip", "quic_exempt"):
        for name in S[key]:
            if name not in SETS:
                problems.append(f"{key} 引用了不存在的集合: {name}")
    for name in ("cn", "foreign", "cn-ip"):
        if name not in SETS:
            problems.append(f"QUIC 规则依赖的集合缺失: {name}")
    all_sources = {src for n in SETS for t in TARGETS for src in sources(n, t)}
    for src in S["watch"]:
        if src not in all_sources:
            problems.append(f"watch 中的 {src} 不是任何集合的来源")
    for src, name in (S.get("pin") or {}).items():
        if not src.startswith("geosite:") and src not in S["upstream"]:
            problems.append(f"pin 中的 {src} 不是 geosite 或已定义的上游")
        if name not in SETS or set_type(name) != "domain":
            problems.append(f"pin 的目标 {name} 不是域名集合")
    for item in S["stash_dns_china"]:
        if item not in SETS:
            problems.append(f"stash_dns_china 引用了不存在的集合: {item}")
    # 同一条目出现在两个去向不同的本地文件里：后面那条永远不会生效
    seen: dict[str, tuple[str, str]] = {}
    for item in S["sets"]:
        if not isinstance(item, dict) or "name" not in item or not item.get("to"):
            continue
        for row in local_rows(item["name"]):
            first = seen.setdefault(row, (item["name"], item["to"]))
            if first[1] != item["to"]:
                problems.append(f"rules/{item['name']}.txt: {row} 已在 rules/{first[0]}.txt（{first[1]}）中，不会生效")
    return problems


def main() -> int:
    check = "--check" in sys.argv
    problems = validate_spec()
    if problems:
        print("src/spec.yaml / rules/ 自检失败：\n" + "\n".join(f"  {x}" for x in problems))
        return 1
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
