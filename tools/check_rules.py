#!/usr/bin/env python3
"""发布前把关：用刚生成的真实规则集 + 生成器产出的完整规则顺序，让 mihomo 实际匹配关键域名。

用法：python3 tools/check_rules.py --dist dist --mihomo /path/to/mihomo

所有策略组接到一个不监听的本地端口（拨号立即失败并记录命中规则），DNS 为本地假服务器；不访问业务站点。
任一关键域名走错集合/策略组即失败，Action 不发布。
"""
from __future__ import annotations

import argparse
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

import build
from check_routing import address, recv_exact, start_dns

# (域名, 端口, 期望集合, 期望策略组)；只放长期稳定、用户明确要求的分流
CASES = [
    # Claude / AI
    ("claude.ai", 443, "ai-essential", "🤖 AI"),
    ("api.anthropic.com", 443, "ai-essential", "🤖 AI"),
    ("cdn.sift.com", 443, "ai-essential", "🤖 AI"),
    ("www.anthropic.com", 443, "ai", "🤖 AI"),
    ("widget.intercom.io", 443, "ai", "🤖 AI"),
    ("chatgpt.com", 443, "ai", "🤖 AI"),
    ("gemini.google.com", 443, "ai", "🤖 AI"),
    ("browser-intake-us5-datadoghq.com", 443, "telemetry", "🛑 广告"),
    ("o1.ingest.us.sentry.io", 443, "telemetry", "🛑 广告"),
    ("challenges.cloudflare.com", 443, "auth", "🚀 节点选择"),
    # 游戏：下载直连，其余走游戏
    ("cache1-hkg1.steamcontent.com", 443, "direct", "🎯 直连"),
    ("cache10-hkg1.steamcontent.com", 443, "direct", "🎯 直连"),
    ("steampipe.akamaized.net", 443, "direct", "🎯 直连"),
    ("download.epicgames.com", 443, "direct", "🎯 直连"),
    ("epicgames-download1.akamaized.net", 443, "local-direct", "🎯 直连"),
    ("lvlt.cdn.ea.com", 443, "direct", "🎯 直连"),
    ("origin-a.akamaihd.net", 443, "direct", "🎯 直连"),
    ("cdn.gog.com", 443, "direct", "🎯 直连"),
    ("level3.blizzard.com", 443, "direct", "🎯 直连"),
    ("gs2.ww.prod.dl.playstation.net", 443, "direct", "🎯 直连"),
    ("cmp1-hkg1.steamserver.net", 443, "game-proxy", "🎮 游戏"),
    ("cm1-hkg1.cm.steampowered.com", 27017, "game-proxy", "🎮 游戏"),
    ("store.steampowered.com", 443, "games", "🎮 游戏"),
    ("steamcommunity.com", 443, "games", "🎮 游戏"),
    ("store.epicgames.com", 443, "games", "🎮 游戏"),
    ("www.ea.com", 443, "games", "🎮 游戏"),
    # 各服务组
    ("www.bilibili.com", 443, "bilibili", "📺 B站"),
    ("music.163.com", 443, "direct", "🎯 直连"),
    ("github.com", 443, "proxy", "🚀 节点选择"),
    ("onedrive.live.com", 443, "proxy", "🚀 节点选择"),
    ("api.telegram.org", 443, "proxy", "🚀 节点选择"),
    ("www.bing.com", 443, "microsoft", "Ⓜ️ 微软"),
    ("dl.delivery.mp.microsoft.com", 443, "direct", "🎯 直连"),
    ("www.apple.com", 443, "apple", "🍎 苹果"),
    ("music.apple.com", 443, "apple", "🍎 苹果"),
    ("www.youtube.com", 443, "media", "🎬 流媒体"),
    ("www.netflix.com", 443, "media", "🎬 流媒体"),
    ("www.google.com", 443, "google", "🔍 谷歌"),
    ("mtalk.google.com", 443, "google", "🔍 谷歌"),
    ("www.wikipedia.org", 443, "foreign", "🚀 节点选择"),
    ("browserleaks.com", 443, "foreign", "🚀 节点选择"),
    ("www.baidu.com", 443, "cn", "🎯 直连"),
    ("www.qq.com", 443, "cn", "🎯 直连"),
    ("tracking-protection.cdn.mozilla.net", 443, "local-direct", "🎯 直连"),
    ("160.79.104.10", 443, "ai-ip", "🤖 AI"),
    ("router.lan", 80, "private", "DIRECT"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", type=Path, required=True)
    ap.add_argument("--mihomo", required=True)
    args = ap.parse_args()

    # 接收端端口不监听：拨号立即失败，mihomo 随即输出含“命中规则与策略组”的日志，不产生任何外部流量
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    sink_port = closed.getsockname()[1]
    closed.close()
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(("127.0.0.1", 0))
    start_dns(dns, "remote", "203.0.113.8", "203.0.113.8")
    reserve = socket.socket()
    reserve.bind(("127.0.0.1", 0))
    socks_port = reserve.getsockname()[1]
    reserve.close()

    providers = {}
    for name, spec in build.providers("meta").items():
        rel = build.provider_file(name, "meta")
        if not (args.dist / rel).exists():
            sys.exit(f"缺少规则集文件: {args.dist / rel}")
        # mihomo 只允许读取工作目录内的文件，启动前整体复制进去
        providers[name] = {"type": "file", "behavior": spec["behavior"], "format": spec["format"], "path": f"./{rel}"}
    # 固定 DIRECT 出站也接到接收端；保留生成的完整规则顺序
    rules = [r.replace(",DIRECT", ",_direct") for r in build.rules("meta")]
    groups = {"_direct"} | {g["name"] for g in build.S["groups"]}
    cfg = {
        "socks-port": socks_port, "allow-lan": False, "mode": "rule", "log-level": "info",
        "dns": {"enable": True, "ipv6": False, "enhanced-mode": "redir-host",
                "nameserver": [f"udp://127.0.0.1:{dns.getsockname()[1]}"], "default-nameserver": ["127.0.0.1"]},
        "proxies": [{"name": "_sink", "type": "ss", "server": "127.0.0.1", "port": sink_port,
                     "cipher": "aes-128-gcm", "password": "test"}],
        "proxy-groups": [{"name": g, "type": "select", "proxies": ["_sink"]} for g in sorted(groups)],
        "rule-providers": providers,
        "rules": ["IP-CIDR,127.0.0.0/8,DIRECT,no-resolve", *rules],
    }
    lines: queue.Queue[str] = queue.Queue()
    failures = []
    with tempfile.TemporaryDirectory(prefix="acl4ssr-rules-") as tmp:
        shutil.copytree(args.dist / build.OUT_DIR["meta"], Path(tmp) / build.OUT_DIR["meta"])
        cfg_path = Path(tmp) / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        proc = subprocess.Popen([args.mihomo, "-d", tmp, "-f", str(cfg_path)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        transcript = []

        def reader():
            for line in proc.stdout:
                transcript.append(line.rstrip())
                lines.put(line.rstrip())

        threading.Thread(target=reader, daemon=True).start()

        def wait(pred, timeout=20):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    if proc.poll() is not None:
                        break
                    continue
                if pred(line):
                    return line
            raise RuntimeError("等待 mihomo 超时\n" + "\n".join([t for t in transcript if "Start initial provider" not in t][-25:]))

        try:
            wait(lambda l: "SOCKS proxy listening at" in l)
            time.sleep(2)  # 监听建立后规则/策略组仍在初始化，过早的连接会被静默丢弃
            def probe(host, port, timeout):
                with socket.create_connection(("127.0.0.1", socks_port), timeout=3) as c:
                    c.settimeout(3)
                    c.sendall(b"\x05\x01\x00")
                    assert recv_exact(c, 2) == b"\x05\x00"
                    c.sendall(b"\x05\x01\x00" + address(host, port))
                    src = c.getsockname()[1]
                    try:
                        c.recv(64)
                    except OSError:
                        pass
                return wait(lambda l: f":{src} -->" in l and f"{host}:{port}" in l and "match " in l, timeout)

            for host, port, want_set, want_group in CASES:
                try:
                    line = probe(host, port, 5)
                except RuntimeError:
                    line = probe(host, port, 10)  # 偶发丢弃时重试一次
                want_group = "_direct" if want_group == "DIRECT" else want_group
                ok = (f"RuleSet({want_set})" in line or f"RuleSet/{want_set}" in line) and want_group in line
                print(f"{'✓' if ok else '✗'} {host}:{port} → {want_set} / {want_group}"
                      + ("" if ok else f"\n    实际: {line.split('match ', 1)[-1]}"), flush=True)
                if not ok:
                    failures.append(host)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    if failures:
        print(f"{len(failures)} 个关键域名分流错误，不发布")
        return 1
    print(f"✓ 真实规则集：{len(CASES)} 个关键域名全部命中预期集合与策略组")
    return 0


if __name__ == "__main__":
    sys.exit(main())
