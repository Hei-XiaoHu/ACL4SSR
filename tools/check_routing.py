#!/usr/bin/env python3
"""离线行为回归：用真实 mihomo 匹配 QQ、Claude、游戏下载、QUIC 与广告连接，并做 DNS 泄露断言。

用法：python3 tools/check_routing.py /path/to/mihomo

使用小型规则夹具，保留生成器产出的完整分流顺序和本仓库列表。
所有出站都改接本地 SS 接收端，DNS 也在本地，测试不访问业务站点。
四台假 DNS（境外 / 国内 / 内网 system / 直连 direct-nameserver）各自返回不同地址并记录收到的查询，
据此断言：
  L1 走代理的域名本地零查询（交给节点远端解析，任何本地 DNS 都看不到）
  L2 未知域名为匹配国内 IP 规则只查境外 DNS，绝不发给国内 DNS
  L3 DIRECT 出站：国内域名走国内 policy，其余走 direct-nameserver，内网走 system
  L4 主解析器（fake-ip-filter / IP 规则使用）：已知国内 → 国内，其余 → 境外，内网 → system
这验证 mihomo 的实际匹配行为，并静态核对 Stash 输出；不是 Stash 实机测试。
"""
from __future__ import annotations

import ipaddress
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

import build

DIRECT_AUDIT = "direct-audit"  # 含此标记的查询返回回环地址，DIRECT 拨号不会访问公网


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise RuntimeError("SOCKS 连接提前关闭")
        data += chunk
    return data


def address(host: str, port: int) -> bytes:
    try:
        ip = ipaddress.ip_address(host)
        return bytes([1 if ip.version == 4 else 4]) + ip.packed + struct.pack("!H", port)
    except ValueError:
        encoded = host.encode("idna")
        return b"\x03" + bytes([len(encoded)]) + encoded + struct.pack("!H", port)


def socks_reply(sock: socket.socket) -> tuple[str, int]:
    version, status, _, kind = recv_exact(sock, 4)
    if version != 5 or status != 0:
        raise RuntimeError(f"SOCKS 响应异常: version={version}, status={status}")
    if kind == 1:
        host = socket.inet_ntoa(recv_exact(sock, 4))
    elif kind == 3:
        host = recv_exact(sock, recv_exact(sock, 1)[0]).decode()
    else:
        host = socket.inet_ntop(socket.AF_INET6, recv_exact(sock, 16))
    return host, struct.unpack("!H", recv_exact(sock, 2))[0]


QUERY_LOG: list[tuple[str, str]] = []  # (DNS 标签, 查询域名)
QUERY_LOCK = threading.Lock()


def start_dns(sock: socket.socket, label: str, response_ip: str, audit_ip: str) -> threading.Thread:
    def serve():
        while True:
            try:
                packet, peer = sock.recvfrom(4096)
                end, labels = 12, []
                while packet[end]:
                    labels.append(packet[end + 1:end + 1 + packet[end]].decode(errors="replace"))
                    end += packet[end] + 1
                end += 5
                qname = ".".join(labels).lower()
                with QUERY_LOCK:
                    QUERY_LOG.append((label, qname))
                question = packet[12:end]
                answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"
                answer += socket.inet_aton(audit_ip if DIRECT_AUDIT in qname else response_ip)
                response = packet[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
                sock.sendto(response + question + answer, peer)
            except (OSError, IndexError):
                return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def queried(host: str) -> set[str]:
    with QUERY_LOCK:
        return {label for label, name in QUERY_LOG if name == host.lower()}


def config(dns_port: int, sink_port: int, socks_port: int) -> dict:
    providers = {}
    for name, spec in build.providers("meta").items():
        source = build.S["providers"][name]
        rows = []
        if "self" in source:
            rows = yaml.safe_load((build.ROOT / source["self"]).read_text())["payload"]
        elif spec["behavior"] == "domain":
            rows = ["unused.invalid"]
        elif spec["behavior"] == "ipcidr":
            rows = ["192.0.2.254/32"]
        providers[name] = {"type": "inline", "behavior": spec["behavior"], "payload": rows}

    # 恶意/跟踪夹具和已有白名单发生冲突，以验证顺序，不依赖每日变化的远程列表。
    providers["adrules"]["payload"] = [
        "+.tracking.miui.com", "+.adjust.com", "+.umeng.com", "+.umengcloud.com",
        "+.googletraveladservices.com", "tracking-protection.cdn.mozilla.net",
        # Claude 必需主机即使被广告源误收，仍应走明确的本地 Claude 规则。
        "api.anthropic.com", "challenges.cloudflare.com",
        # 真实广告源确实收录了 Sift 与 Intercom 分析上报（2026-10 核对 AdRules / anti-AD）
        "+.siftscience.com", "+.sift.com", "+.api-visitor-analytics.intercom.com",
        # 人工夹具，不声称这些主机存在；验证非必要子域名仍接受广告检查。
        "audit-telemetry.anthropic.com", "audit-telemetry.claude.ai",
        "audit-telemetry.together.ai",
    ]
    providers["private"]["payload"] = ["+.lan", "+.home.arpa"]
    providers["private-ip"]["payload"] = ["127.0.0.0/8", "192.168.0.0/16"]
    overlap = ["+.browserleaks.com", "+.acm.org", "+.cambridge.org"]
    providers["cn"]["payload"] = ["+.qq.com", "+.cn", "+.shanghaidisneyresort.com", *overlap]
    providers["geolocation-!cn"]["payload"] = overlap
    providers["cn-ip"]["payload"] = ["116.131.56.103/32", "223.5.5.5/32"]
    providers["youtube"]["payload"] = ["+.youtube.com", "+.googlevideo.com"]
    providers["google"]["payload"] = [
        "+.google.com", "+.googleapis.cn", "+.gstatic.com", "+.googleusercontent.com",
        "+.googlevideo.com", "+.openai.com", "+.googletraveladservices.com",
    ]
    providers["google-cn"]["payload"] = ["+.gstatic.cn"]
    providers["googlefcm"]["payload"] = ["mtalk.google.com"]
    providers["netflix"]["payload"] = ["+.netflix.com", "+.nflxvideo.net"]
    providers["ai"]["payload"] = ["+.openai.com"]
    # 与上游一致：games@cn 含 steamserver.net（Steam CM），steam 集合也含
    providers["games-cn"]["payload"] = [
        "+.nintendoswitch.cn", "gog.qtlglb.com", "+.steamserver.net", "+.steamusercontent.com",
    ]
    providers["games"]["payload"] = ["+.battle.net", "+.ubisoft.com", "+.gog.com", "+.nintendoswitch.cn"]
    providers["game-download-cn"]["payload"] = ["dl.delivery.mp.microsoft.com", "blzdist-wow.necdn.leihuo.netease.com"]
    providers["game-download"]["payload"] = ["+.dl.playstation.net", "steampipe.akamaized.net"]
    providers["steam"]["payload"] = ["+.steamcontent.com", "+.steampowered.com", "+.steamserver.net"]
    providers["ea"]["payload"] = ["+.ea.com", "+.origin.com"]
    providers["communication"]["payload"] = ["+.discord.media"]
    providers["apple"]["payload"] = ["+.apple.com"]
    providers["microsoft"]["payload"] = ["+.microsoft.com"]
    providers["quic-exempt"]["payload"] = ["+.examplegame.com"]
    providers["gfw"]["payload"] = ["+.wikipedia.org"]
    providers["geolocation-!cn"]["payload"] += [
        "+.battle.net", "+.dl.playstation.net", "steampipe.akamaized.net", "+.discord.media",
        "+.apple.com", "+.microsoft.com", "+.examplegame.com",
        "+.steamcontent.com", "+.steampowered.com", "+.ea.com", "+.gog.com",
        "+.intercom.io", "+.sift.com",
    ]
    providers["entertainment-cn"]["payload"] = ["+.iqiyi.com", "+.youku.com"]
    providers["entertainment-cn-attr"]["payload"] = ["+.shanghaidisneyresort.com"]
    providers["proxymedia"]["payload"] = ["+.disneyplus.com", "+.twitch.tv", "+.spotify.com", "+.shanghaidisneyresort.com"]

    # 保留原规则，仅把固定 DIRECT 出站也接到本地测试端。
    rules = [rule.replace(",DIRECT", ",_audit_direct") for rule in build.rules("meta")]
    targets = {"_audit_direct"}
    for rule in rules:
        parts = rule.split(",")
        target = parts[-2] if parts[-1] == "no-resolve" else parts[-1]
        if target != "REJECT":
            targets.add(target)
    return {
        "socks-port": socks_port,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "dns": {
            "enable": True,
            "listen": "127.0.0.1:0",
            "ipv6": False,
            "enhanced-mode": "redir-host",
            "nameserver": [f"udp://127.0.0.1:{dns_port}"],
            "default-nameserver": ["127.0.0.1"],
        },
        "proxies": [{
            "name": "_audit_sink", "type": "ss", "server": "127.0.0.1",
            "port": sink_port, "cipher": "aes-128-gcm", "password": "test", "udp": True,
        }],
        "proxy-groups": [
            {"name": name, "type": "select", "proxies": ["_audit_sink"]}
            for name in sorted(targets)
        ],
        "rule-providers": providers,
        "rules": rules,
    }


CHINA_SERVERS = {"223.5.5.5", "119.29.29.29", "doh.pub", "1.2.4.8"}


def _has_china(servers) -> bool:
    return any(any(c in str(s) for c in CHINA_SERVERS) for s in servers)


def assert_outputs():
    china, system = build.S["dns_china"], ["system"]
    meta = build.meta_dns()["dns"]
    stash = build.stash_dns()["dns"]
    # mihomo：主 DNS 全部境外且经 DNS 组；DIRECT 走国内；policy 只有内网与 cn 两类
    assert meta["direct-nameserver-follow-policy"]
    assert all("#🛰️ DNS-Proxy" in server for server in meta["nameserver"])
    assert not _has_china(meta["nameserver"])
    assert meta["direct-nameserver"] == china
    policy = meta["nameserver-policy"]
    assert policy["rule-set:private"] == system and policy["+.lan"] == system
    assert list(policy)[-1] == "rule-set:cn" and policy["rule-set:cn"] == china
    # 关键不变式：policy 不含任何境外条目，DIRECT 未命中时必回到国内 direct-nameserver
    assert all(v in (system, china) for v in policy.values()), policy
    assert sum(v == china for v in policy.values()) == 1
    # Stash：没有 direct-nameserver，默认直连的游戏下载集合单独走国内
    sp = stash["nameserver"], stash["nameserver-policy"]
    assert not _has_china(sp[0])
    assert all(v in (system, china) for v in sp[1].values()), sp[1]
    assert sp[1]["geosite:private"] == system and sp[1]["+.lan"] == system
    assert sp[1]["geosite:category-game-platforms-download"] == china
    assert sp[1]["+.steamcontent.com"] == china and sp[1]["+.cdn.ea.com"] == china
    assert list(sp[1])[-1] == "geosite:cn" and sp[1]["geosite:cn"] == china
    assert not any(key.startswith("geosite:") and "@" in key for key in sp[1])
    for host in ("+.claude.ai", "+.anthropic.com", "+.steamserver.net", "challenges.cloudflare.com"):
        assert host not in sp[1], host
    # 国外覆写：不含任何国内服务器；只替换 DNS，不改规则
    ov = yaml.safe_load(build.overseas())
    assert list(ov) == ["dns!"], list(ov)
    od = ov["dns!"]
    for key in ("default-nameserver", "nameserver", "proxy-server-nameserver", "direct-nameserver"):
        assert not _has_china(od[key]), (key, od[key])
    assert all(v == system for v in od["nameserver-policy"].values())
    assert any(s.startswith("tls://") for s in od["nameserver"]) and any(s.startswith("https://") for s in od["nameserver"])
    assert all("#🛰️ DNS-Proxy" in s for s in od["nameserver"])
    assert not any("#" in s for s in od["direct-nameserver"] + od["proxy-server-nameserver"])

    for target, dns in (("meta", meta), ("stash", stash)):
        assert "+.stun.*.*" in dns["fake-ip-filter"], target
        rules = build.rules(target)
        assert all("RULE-SET,unban," not in rule for rule in rules), target
        ad_index = next(i for i, rule in enumerate(rules) if
                        rule.startswith(("RULE-SET,adrules,", "RULE-SET,awavenue,")))
        assert rules.index("RULE-SET,claude-essential,💬 Ai平台") < ad_index, target
        assert rules.index("RULE-SET,claude,💬 Ai平台") > ad_index, target
        assert rules.index("RULE-SET,claude-telemetry,🛑 广告拦截") < ad_index, target
        assert rules.index("RULE-SET,game-proxy-extra,🎮 游戏平台") < rules.index("RULE-SET,games-cn,🎯 全球直连")
        assert rules.index("RULE-SET,game-download-extra,🎯 全球直连") < rules.index("RULE-SET,steam,🎮 游戏平台")
        quic = next(rule for rule in rules if rule.startswith("AND,"))
        assert "(RULE-SET,claude)" in quic and "(RULE-SET,gfw)" in quic, target
        assert "(RULE-SET,claude-ip,no-resolve)" in quic, target
        assert "RULE-SET,cn-ip,no-resolve" in quic if target == "meta" else "GEOIP,CN,no-resolve" in quic
        assert "(RULE-SET,quic-exempt)" in quic and "(RULE-SET,apple)" in quic, target
        if target == "stash":
            assert "(PROTOCOL,QUIC)" in quic and "DST-PORT" not in quic
            assert "cn" not in build.providers("stash")
            assert "GEOSITE,cn" in quic
            assert rules.index("GEOSITE,geolocation-!cn,🐟 漏网之鱼") < rules.index("GEOSITE,cn,🎯 全球直连")
    essential = build.local_provider_domains("claude-essential")
    assert "+.sift.com" in essential and "+.siftscience.com" in essential
    assert "claude.app" in "".join(build.local_provider_domains("claude"))
    assert "RULE-SET,shared-auth,🚀 节点选择" in build.rules("meta")
    assert "RULE-SET,shared-auth,🚀 节点选择" in build.rules("stash")
    for line in build.ini("meta").splitlines():
        if line.startswith("custom_proxy_group=") and any(
            line.startswith(f"custom_proxy_group={region}") for region in build.REGIONS
        ):
            assert "`[]REJECT`" in line
    print("✓ mihomo / Stash / 国外覆写 DNS、STUN、白名单、Claude 与游戏优先级、空地区组", flush=True)


def dns_query(port: int, host: str) -> str:
    question = b"".join(bytes([len(label)]) + label.encode() for label in host.split("."))
    packet = b"\xa1\xb2\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    packet += question + b"\x00\x00\x01\x00\x01"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(5)
        sock.sendto(packet, ("127.0.0.1", port))
        reply = sock.recv(4096)

    def skip_name(offset):
        while reply[offset]:
            length = reply[offset]
            if length & 0xc0 == 0xc0:
                return offset + 2
            offset += length + 1
        return offset + 1

    _, flags, questions, answers, _, _ = struct.unpack("!6H", reply[:12])
    if flags & 0xf:
        raise AssertionError(f"DNS {host} 错误码 {flags & 0xf}")
    offset = 12
    for _ in range(questions):
        offset = skip_name(offset) + 4
    for _ in range(answers):
        offset = skip_name(offset)
        kind, _, _, size = struct.unpack("!HHIH", reply[offset:offset + 10])
        offset += 10
        if kind == 1 and size == 4:
            return socket.inet_ntoa(reply[offset:offset + size])
        offset += size
    raise AssertionError(f"DNS {host} 未返回 A 记录")


def _udp_server(label: str, response_ip: str, audit_ip: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    start_dns(sock, label, response_ip, audit_ip)
    return sock


REMOTE_IP, CHINA_IP, LAN_IP, DIRECT_IP = "203.0.113.8", "116.131.56.103", "127.0.0.1", "127.0.0.2"


def native_regressions(exe: str):
    # UDP 与 TCP 接收端只在回环地址上接收；不转发任何数据。
    for _ in range(16):
        sink_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sink_udp.bind(("127.0.0.1", 0))
        sink_tcp = socket.socket()
        sink_tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sink_tcp.bind(sink_udp.getsockname())
            break
        except OSError:
            sink_udp.close()
            sink_tcp.close()
    else:
        raise RuntimeError("无法分配同时空闲的 TCP/UDP 测试端口")
    sink_tcp.listen()
    # 境外 / 国内 / 内网 / 直连：常规答案各不相同；direct-audit 测试名一律答回环地址
    dns = _udp_server("remote", REMOTE_IP, "127.0.0.4")
    china_dns = _udp_server("china", CHINA_IP, "127.0.0.3")
    lan_dns = _udp_server("system", LAN_IP, LAN_IP)
    direct_dns = _udp_server("direct", DIRECT_IP, DIRECT_IP)
    dns_reserve = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns_reserve.bind(("127.0.0.1", 0))
    dns_port = dns_reserve.getsockname()[1]
    dns_reserve.close()
    reserve = socket.socket()
    reserve.bind(("127.0.0.1", 0))
    socks_port = reserve.getsockname()[1]
    reserve.close()
    lines: queue.Queue[str] = queue.Queue()
    transcript = []
    proc = None
    # DIRECT 解析器选择：测试专用域名经字面 DIRECT 规则真实拨号（答案均为回环，不出公网）
    direct_cases = [
        (f"{DIRECT_AUDIT}.qq.com", "china", "国内域名 → 国内 policy"),
        (f"{DIRECT_AUDIT}.steamcontent.com", "direct", "游戏下载 → 国内 direct-nameserver"),
        (f"{DIRECT_AUDIT}.cdn.ea.com", "direct", "EA 下载 → 国内 direct-nameserver"),
        (f"{DIRECT_AUDIT}.unknown.example", "direct", "未知域名直连 → 国内 direct-nameserver"),
        (f"{DIRECT_AUDIT}.claude.ai", "direct", "若手动把 AI 切 DIRECT：连接本身已直连，解析同样国内"),
    ]

    try:
        with tempfile.TemporaryDirectory(prefix="acl4ssr-routing-") as tmp:
            path = Path(tmp) / "config.yaml"
            cfg = config(dns.getsockname()[1], sink_udp.getsockname()[1], socks_port)
            remote_server = [f"udp://127.0.0.1:{dns.getsockname()[1]}"]
            china_server = [f"udp://127.0.0.1:{china_dns.getsockname()[1]}"]
            lan_server = [f"udp://127.0.0.1:{lan_dns.getsockname()[1]}"]
            # 保留生成的 policy 顺序/匹配条件，只把上游替换为返回不同 A 记录的本地 DNS。
            policy = {}
            for key, servers in build.dns_policy("meta").items():
                if servers == ["system"]:
                    policy[key] = lan_server
                elif servers == build.S["dns_china"]:
                    policy[key] = china_server
                else:
                    raise AssertionError(f"policy 出现非国内/非 system 条目: {key}")
            cfg["dns"].update({
                "listen": f"127.0.0.1:{dns_port}",
                "proxy-server-nameserver": china_server,
                "direct-nameserver": [f"udp://127.0.0.1:{direct_dns.getsockname()[1]}"],
                "direct-nameserver-follow-policy": build.meta_dns()["dns"]["direct-nameserver-follow-policy"],
                "respect-rules": build.meta_dns()["dns"]["respect-rules"],
                "nameserver-policy": policy,
            })
            cfg["rules"][:0] = [
                "DOMAIN,router.audit.lan,DIRECT",
                *(f"DOMAIN,{host},DIRECT" for host, _, _ in direct_cases),
                "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",  # 测试 DNS 均为本地接收端
            ]
            path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
            proc = subprocess.Popen([exe, "-d", tmp, "-f", str(path)], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)

            def read_logs():
                for line in proc.stdout:
                    transcript.append(line.rstrip())
                    lines.put(line.rstrip())

            threading.Thread(target=read_logs, daemon=True).start()

            def await_line(predicate, timeout=10, retry=None):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    try:
                        line = lines.get(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
                    except queue.Empty:
                        if proc.poll() is not None:
                            break
                        if retry is not None:
                            retry()
                        continue
                    if predicate(line):
                        return line
                raise RuntimeError("等待分流日志超时\n" + "\n".join(transcript[-25:]))

            waiting = {"SOCKS proxy listening at", "DNS server(UDP) listening at"}

            def ready(line):
                waiting.difference_update(marker for marker in tuple(waiting) if marker in line)
                return not waiting

            await_line(ready)
            essentials = set(build.local_provider_domains("claude-essential"))
            cases = [
                ("tcp", "chromewebstore.google.com", 443, "google", "🌐 谷歌服务"),
                ("tcp", "dl.google.com", 443, "google", "🌐 谷歌服务"),
                ("tcp", "services.googleapis.cn", 443, "google", "🌐 谷歌服务"),
                ("tcp", "www.gstatic.com", 443, "google", "🌐 谷歌服务"),
                ("tcp", "lh3.googleusercontent.com", 443, "google", "🌐 谷歌服务"),
                ("tcp", "www.gstatic.cn", 443, "google-cn", "🌐 谷歌服务"),
                ("tcp", "mtalk.google.com", 443, "googlefcm", "📢 谷歌FCM"),
                ("tcp", "video.googlevideo.com", 443, "youtube", "📹 油管视频"),
                # 截图中的 QQ 纯 IP，以及国内域名/未知 IP，绝不能被 QUIC blanket rule 拒绝。
                ("udp", "116.131.56.103", 443, "cn-ip", "🎯 全球直连"),
                ("udp", "223.5.5.5", 443, "cn-ip", "🎯 全球直连"),
                ("udp", "gchat.qpic.qq.com", 443, "cn", "🎯 全球直连"),
                ("udp", "203.0.113.9", 443, "Match", "🐟 漏网之鱼"),
                ("udp", "router.lan", 443, "private", "_audit_direct"),
                ("udp", "160.79.104.10", 443, "AND", "REJECT"),
                ("udp", "claude.ai", 443, "AND", "REJECT"),
                ("udp", "video.googlevideo.com", 443, "AND", "REJECT"),
                ("udp", "www.netflix.com", 443, "AND", "REJECT"),
                ("udp", "claude.ai", 8443, "claude-essential", "💬 Ai平台"),
                ("udp", "www.wikipedia.org", 443, "AND", "REJECT"),
                ("udp", "www.acm.org", 443, "AND", "REJECT"),
                ("udp", "www.twitch.tv", 443, "AND", "REJECT"),
                ("udp", "challenges.cloudflare.com", 443, "AND", "REJECT"),
                ("udp", "api.battle.net", 443, "games", "🎮 游戏平台"),
                ("udp", "a.dl.playstation.net", 443, "game-download", "🎯 全球直连"),
                ("udp", "steampipe.akamaized.net", 443, "game-download", "🎯 全球直连"),
                ("udp", "cache10-hkg1.steamcontent.com", 443, "game-download-extra", "🎯 全球直连"),
                ("udp", "call.discord.media", 443, "geolocation-!cn", "🐟 漏网之鱼"),
                # 默认直连的境外服务与自定义豁免：QUIC 不拦
                ("udp", "www.apple.com", 443, "apple", "🍎 苹果服务"),
                ("udp", "update.microsoft.com", 443, "microsoft", "Ⓜ️ 微软服务"),
                ("udp", "play.examplegame.com", 443, "geolocation-!cn", "🐟 漏网之鱼"),
            ]
            for host in [
                "claude.ai", "www.claude.ai", "audit-subdomain.claude.ai", "downloads.claude.ai",
                "claude.com", "platform.claude.com", "code.claude.com",
                "claude.app", "api.anthropic.com", "console.anthropic.com",
                "a-api.anthropic.com", "s-cdn.anthropic.com", "assets-proxy.anthropic.com",
                "a.claude.ai", "a-cdn.claude.ai", "assets.claude.ai",
                "test.livepreview.claude.ai", "test.livepreview.claude.app",
                "mcp-proxy.anthropic.com",
                "bridge.claudeusercontent.com", "test.frame.claudeusercontent.com",
                "files.claudemcpcontent.com", "api.claudemcpclient.com",
                "claude.dev", "clau.de", "servd-anthropic-website.b-cdn.net",
                "anthropic.com.cdn.cloudflare.net",
                "anthropic.auth0.com", "anthropic-com.ghost.io",
                "widget.intercom.io", "js.intercomcdn.com",
                # 广告源收录了 Sift，必须由排在广告前的 essential 放行到 AI
                "cdn.sift.com", "api.siftscience.com",
            ]:
                essential = host in essentials or any(
                    host == domain[2:] or host.endswith(domain[1:])
                    for domain in essentials if domain.startswith("+.")
                )
                cases.append(("tcp", host, 443, "claude-essential" if essential else "claude", "💬 Ai平台"))
            cases += [
                ("tcp", "challenges.cloudflare.com", 443, "shared-auth", "🚀 节点选择"),
                ("tcp", "client-api.arkoselabs.com", 443, "shared-auth", "🚀 节点选择"),
                ("tcp", "160.79.104.10", 443, "claude-ip", "💬 Ai平台"),
                ("tcp", "2607:6bc0::10", 443, "claude-ip", "💬 Ai平台"),
                ("tcp", "http-intake.logs.us5.datadoghq.com", 443, "claude-telemetry", "🛑 广告拦截"),
                ("tcp", "http-intake.logs.ap1.datadoghq.com", 443, "claude-telemetry", "🛑 广告拦截"),
                ("tcp", "browser-intake-us5-datadoghq.com", 443, "claude-telemetry", "🛑 广告拦截"),
                ("tcp", "browser-intake-datadoghq.eu", 443, "claude-telemetry", "🛑 广告拦截"),
                ("tcp", "o1.ingest.sentry.io", 443, "claude-telemetry", "🛑 广告拦截"),
                ("tcp", "o1.ingest.us.sentry.io", 443, "claude-telemetry", "🛑 广告拦截"),
                ("tcp", "o1.ingest.de.sentry.io", 443, "claude-telemetry", "🛑 广告拦截"),
                ("tcp", "events.statsigapi.net", 443, "claude-telemetry", "🛑 广告拦截"),
                ("tcp", "cdn.usefathom.com", 443, "claude-telemetry", "🛑 广告拦截"),
                ("tcp", "api-visitor-analytics.intercom.com", 443, "adrules", "🛑 广告拦截"),
                ("tcp", "audit-telemetry.anthropic.com", 443, "adrules", "🛑 广告拦截"),
                ("tcp", "audit-telemetry.claude.ai", 443, "adrules", "🛑 广告拦截"),
                ("tcp", "audit-telemetry.together.ai", 443, "adrules", "🛑 广告拦截"),
                ("tcp", "tracking.miui.com", 443, "adrules", "🛑 广告拦截"),
                ("tcp", "app.adjust.com", 443, "adrules", "🛑 广告拦截"),
                ("tcp", "errlog.umeng.com", 443, "adrules", "🛑 广告拦截"),
                ("tcp", "msg.umengcloud.com", 443, "adrules", "🛑 广告拦截"),
                ("tcp", "googletraveladservices.com", 443, "adrules", "🛑 广告拦截"),
                ("tcp", "tracking-protection.cdn.mozilla.net", 443, "functional-direct", "🎯 全球直连"),
                ("tcp", "claude.ai.evil.example", 443, "Match", "🐟 漏网之鱼"),
                ("tcp", "notanthropic.com", 443, "Match", "🐟 漏网之鱼"),
                ("tcp", "other.b-cdn.net", 443, "Match", "🐟 漏网之鱼"),
                ("tcp", "epicgames-download1.akamaized.net", 443, "extra-direct", "🎯 全球直连"),
                ("tcp", "epicgames-download1-123.file.myqcloud.com", 443, "extra-direct", "🎯 全球直连"),
                ("tcp", "cdn2-epicgames-123.file.myqcloud.com", 443, "extra-direct", "🎯 全球直连"),
                ("tcp", "epicgames-download.evil.example", 443, "Match", "🐟 漏网之鱼"),
                ("tcp", "epicgames-download1.akamaized.net.evil.example", 443, "Match", "🐟 漏网之鱼"),
                ("tcp", "api.battle.net", 443, "games", "🎮 游戏平台"),
                ("tcp", "www.ubisoft.com", 443, "games", "🎮 游戏平台"),
                ("tcp", "www.gog.com", 443, "games", "🎮 游戏平台"),
                ("tcp", "www.nintendoswitch.cn", 443, "games-cn", "🎯 全球直连"),
                ("tcp", "gog.qtlglb.com", 443, "games-cn", "🎯 全球直连"),
                ("tcp", "www.disneyplus.com", 443, "proxymedia", "🌍 国外媒体"),
                ("tcp", "www.twitch.tv", 443, "proxymedia", "🌍 国外媒体"),
                ("tcp", "api.spotify.com", 443, "proxymedia", "🌍 国外媒体"),
                ("tcp", "my-claude-proxy.example", 443, "Match", "🐟 漏网之鱼"),
                ("tcp", "dl.delivery.mp.microsoft.com", 443, "game-download-cn", "🎯 全球直连"),
                ("tcp", "blzdist-wow.necdn.leihuo.netease.com", 443, "game-download-cn", "🎯 全球直连"),
                ("tcp", "www.iqiyi.com", 443, "entertainment-cn", "🎯 全球直连"),
                ("tcp", "www.youku.com", 443, "entertainment-cn", "🎯 全球直连"),
                ("tcp", "www.shanghaidisneyresort.com", 443, "entertainment-cn-attr", "🎯 全球直连"),
                ("tcp", "a.dl.playstation.net", 443, "game-download", "🎯 全球直连"),
                ("tcp", "steampipe.akamaized.net", 443, "game-download", "🎯 全球直连"),
                # 上游只逐个列 cacheN-xxx；新节点仍应直连
                ("tcp", "cache10-hkg1.steamcontent.com", 443, "game-download-extra", "🎯 全球直连"),
                # 创意工坊下载：上游 games@cn 已直连
                ("tcp", "images.steamusercontent.com", 443, "games-cn", "🎯 全球直连"),
                # EA / GOG 下载 CDN 直连；商店/登录走游戏平台
                ("tcp", "lvlt.cdn.ea.com", 443, "game-download-extra", "🎯 全球直连"),
                ("tcp", "ssl-lvlt.cdn.ea.com", 443, "game-download-extra", "🎯 全球直连"),
                ("tcp", "download.dm.origin.com", 443, "game-download-extra", "🎯 全球直连"),
                ("tcp", "cdn.gog.com", 443, "game-download-extra", "🎯 全球直连"),
                ("tcp", "www.ea.com", 443, "ea", "🎮 游戏平台"),
                # Steam CM 信令走游戏平台，即使上游 games@cn 收录了 steamserver.net
                ("tcp", "cm1-hkg1.cm.steampowered.com", 27017, "game-proxy-extra", "🎮 游戏平台"),
                ("tcp", "cmp1-hkg1.steamserver.net", 443, "game-proxy-extra", "🎮 游戏平台"),
                ("tcp", "store.steampowered.com", 443, "steam", "🎮 游戏平台"),
            ]
            for network, host, port, expected_rule, expected_policy in cases:
                tcp = socket.create_connection(("127.0.0.1", socks_port), timeout=3)
                tcp.settimeout(3)
                udp = None
                try:
                    tcp.sendall(b"\x05\x01\x00")
                    assert recv_exact(tcp, 2) == b"\x05\x00"
                    if network == "udp":
                        tcp.sendall(b"\x05\x03\x00\x01\x00\x00\x00\x00\x00\x00")
                        relay = socks_reply(tcp)
                        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        udp.bind(("127.0.0.1", 0))
                        source_port = udp.getsockname()[1]
                        udp.sendto(b"\x00\x00\x00" + address(host, port) + b"audit", relay)
                    else:
                        source_port = tcp.getsockname()[1]
                        tcp.sendall(b"\x05\x01\x00" + address(host, port))
                        tcp.sendall(b"GET / HTTP/1.0\r\n\r\n")
                    destination = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
                    retry = (lambda: udp.sendto(b"\x00\x00\x00" + address(host, port) + b"audit", relay)) if udp is not None else None
                    line = await_line(lambda line: f"[{network.upper()}]" in line
                                      and f":{source_port} -->" in line
                                      and destination in line
                                      and ("match " in line or "(match " in line), retry=retry)
                    if expected_rule in ("AND", "Match"):
                        matched = bool(re.search(rf"match {expected_rule}(?:[/ ()]|$)", line))
                    else:
                        matched = f"match RuleSet({expected_rule})" in line or f"match RuleSet/{expected_rule}" in line
                    if not matched or expected_policy not in line:
                        raise AssertionError(f"{network} {host}:{port}: 期望 {expected_rule} → {expected_policy}\n{line}")
                    print(f"✓ {network.upper()} {host}:{port} → {expected_rule} / {expected_policy}", flush=True)
                finally:
                    tcp.close()
                    if udp is not None:
                        udp.close()

            # ---------------- DNS 泄露断言（先于主动 DNS 查询，避免日志被污染）
            def is_ip(host):
                try:
                    ipaddress.ip_address(host)
                    return True
                except ValueError:
                    return False

            udp_hosts = {h for n, h, _, _, _ in cases if n == "udp" and not is_ip(h)}
            # mihomo 对 UDP 域名目标固定先在本地解析（NAT 映射），按主解析器 policy 选服务器：
            # 国内域名 → 国内，内网 → system，其余只能是境外。
            udp_allowed = {"gchat.qpic.qq.com": {"china"}, "router.lan": {"system"}}
            domains = {(h, r) for n, h, _, r, _ in cases if not is_ip(h)}
            for host, rule in sorted(domains):
                seen = queried(host)
                if host in udp_hosts:
                    allowed = udp_allowed.get(host, {"remote"})
                    assert seen <= allowed, (host, seen, f"UDP 本地解析只允许 {allowed}")
                elif rule == "Match":
                    # L2：未命中任何域名规则，为国内 IP 规则解析一次，只能发往境外 DNS
                    assert seen == {"remote"}, (host, seen, "未知域名只能发给境外 DNS")
                else:
                    # L1：TCP 域名规则直接命中，交给出站远端解析，本地任何 DNS 都不应看到
                    assert not seen, (host, seen, "走代理/已命中的域名不应在本地解析")
            with QUERY_LOCK:
                china_seen = {name for label, name in QUERY_LOG if label == "china"}
            assert china_seen == {"gchat.qpic.qq.com"}, china_seen
            print(f"✓ DNS 泄露 L1/L2：{len(domains)} 个域名；TCP 命中规则者本地零查询，"
                  f"未知域名与 UDP 只查境外；国内 DNS 只见过国内域名", flush=True)

            # L3：DIRECT 出站实际选用的解析器
            for host, expected, note in direct_cases:
                with socket.create_connection(("127.0.0.1", socks_port), timeout=3) as client:
                    client.settimeout(3)
                    client.sendall(b"\x05\x01\x00")
                    assert recv_exact(client, 2) == b"\x05\x00"
                    client.sendall(b"\x05\x01\x00" + address(host, 9))
                    deadline = time.monotonic() + 5
                    while not queried(host) and time.monotonic() < deadline:
                        time.sleep(0.05)
                    time.sleep(0.3)
                seen = queried(host)
                assert seen == {expected}, (host, seen, f"期望 {expected}")
                print(f"✓ DNS DIRECT {host} → {expected}（{note}）", flush=True)

            # L4：主解析器（fake-ip-filter、IP 规则、本地 DNS 监听使用）
            expectations = [
                (REMOTE_IP, "境外", [
                    "claude.ai", "platform.claude.com", "claude.app", "api.anthropic.com",
                    "cdn.sift.com", "challenges.cloudflare.com", "onedrive.live.com",
                    "chromewebstore.google.com", "api.battle.net", "www.disneyplus.com",
                    "cmp1-hkg1.steamserver.net", "cache10-hkg1.steamcontent.com", "never-seen.example",
                ]),
                # cn 含少量国外站（acm.org 等）与 .cn 谷歌域名：它们已被前置规则分到代理，
                # 上面的 L1 已证明代理连接不会在本地解析，因此这里的国内答案不会被使用。
                (CHINA_IP, "国内", [
                    "gchat.qpic.qq.com", "www.baidu.cn", "www.nintendoswitch.cn",
                    "services.googleapis.cn", "acm.org",
                ]),
                (LAN_IP, "内网 system", ["nas.lan", "router.home.arpa"]),
            ]
            for want, label, hosts in expectations:
                for host in hosts:
                    result = dns_query(dns_port, host)
                    assert result == want, (host, result, f"主解析器应使用{label} DNS")
                print(f"✓ DNS 主解析器 → {label}：{', '.join(hosts)}", flush=True)

            # 真正使用 DIRECT 解析器与本地 TCP 服务；若绕过 LAN policy 则无法连接。
            with socket.socket() as peer:
                peer.bind(("127.0.0.1", 0))
                peer.listen()
                peer.settimeout(5)
                with socket.create_connection(("127.0.0.1", socks_port), timeout=3) as client:
                    client.settimeout(3)
                    client.sendall(b"\x05\x01\x00")
                    assert recv_exact(client, 2) == b"\x05\x00"
                    client.sendall(b"\x05\x01\x00" + address("router.audit.lan", peer.getsockname()[1]))
                    socks_reply(client)
                    client.sendall(b"direct-dns-policy")
                    conn, _ = peer.accept()
                    with conn:
                        conn.settimeout(3)
                        assert recv_exact(conn, 17) == b"direct-dns-policy"
            assert queried("router.audit.lan") == {"system"}
            print("✓ DIRECT 内网域名实际连接 → system；没有被独立直连 DNS 绕过", flush=True)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            proc.stdout.close()
        dns.close()
        china_dns.close()
        lan_dns.close()
        direct_dns.close()
        sink_udp.close()
        sink_tcp.close()


def main():
    exe = (sys.argv[1] if len(sys.argv) > 1 else None) or os.environ.get("MIHOMO") or shutil.which("mihomo")
    if not exe:
        sys.exit("找不到 mihomo，请传入可执行文件路径")
    assert_outputs()
    native_regressions(exe)


if __name__ == "__main__":
    main()
