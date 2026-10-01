#!/usr/bin/env python3
"""用真实 mihomo 内核校验生成的配置。

模拟 Xboard / subconverter / Clash Party 覆写的渲染过程，把节点注入模板后执行 `mihomo -t`，
并断言地区组正则的匹配结果。

用法：python3 tools/check.py [mihomo 可执行文件路径]
      （默认读环境变量 MIHOMO，再默认 PATH 中的 mihomo）
"""
from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

# 节点名样本：真实格式 + 用来验证正则边界的干扰项
NODES = [
    "🇭🇰 香港【华东】 S+ ⚡200M", "🇭🇰 香港 A+ ⚡500M", "🇩🇪 德国 S+ ⚡2.5G", "🇫🇷 法国 A ⚡1G",
    "🇺🇸 RN | 美东 | 水牛😐", "🇺🇸 DMIT | 美西 | 三网优化😀", "🇩🇪 NSC | 德国 | 三网优化😀",
    "🇯🇵 Zouter | JP | 地😀", "🇰🇷 阿里 | 韩国😀", "🇸🇬 SG-01", "🇹🇼 TW 01",
    "🇦🇺 Australia 01", "🇷🇺 Russia", "🇸🇪 Sweden", "🇺🇸 US-02",
    "剩余流量：100 GB", "套餐到期：2027-01-01", "🇭🇰 香港 IPLC 倍率3",
]
EXPECT = {
    "🇭🇰 香港节点": {"🇭🇰 香港【华东】 S+ ⚡200M", "🇭🇰 香港 A+ ⚡500M"},
    "🇩🇪 德国节点": {"🇩🇪 德国 S+ ⚡2.5G", "🇩🇪 NSC | 德国 | 三网优化😀"},
    "🇫🇷 法国节点": {"🇫🇷 法国 A ⚡1G"},
    "🇺🇸 美国节点": {"🇺🇸 RN | 美东 | 水牛😐", "🇺🇸 DMIT | 美西 | 三网优化😀", "🇺🇸 US-02"},
    "🇯🇵 日本节点": {"🇯🇵 Zouter | JP | 地😀"},
    "🇰🇷 韩国节点": {"🇰🇷 阿里 | 韩国😀"},
    "🇸🇬 狮城节点": {"🇸🇬 SG-01"},
    "🇹🇼 台湾节点": {"🇹🇼 TW 01"},
}
JUNK = {"剩余流量：100 GB", "套餐到期：2027-01-01", "🇭🇰 香港 IPLC 倍率3"}


def proxies():
    return [{"name": n, "type": "ss", "server": "127.0.0.1", "port": 10000 + i,
             "cipher": "aes-128-gcm", "password": "x"} for i, n in enumerate(NODES)]


# ---------------------------------------------------------------- Xboard 渲染
def _is_regex(s: str) -> bool:
    return len(s) > 2 and s[0] == "/" and re.fullmatch(r"/.*/[a-z]*", s, re.S) is not None


def _pcre(s: str) -> re.Pattern:
    body, flags = s[1:s.rindex("/")], s[s.rindex("/") + 1:]
    return re.compile(body, re.I if "i" in flags else 0)


def xboard_render(tpl: dict) -> dict:
    cfg = copy.deepcopy(tpl)
    cfg["proxies"] = proxies()
    for g in cfg["proxy-groups"]:
        out, filtered = [], False
        for p in g["proxies"]:
            if _is_regex(p):
                filtered = True
                out += [n for n in NODES if _pcre(p).search(n)]
            else:
                out.append(p)
        g["proxies"] = out if filtered else out + NODES
    cfg["proxy-groups"] = [g for g in cfg["proxy-groups"] if g["proxies"]]
    return cfg


# ---------------------------------------------------------------- subconverter 渲染
def subconverter_render(base: dict, ini: str) -> dict:
    cfg = copy.deepcopy(base)
    cfg["proxies"] = proxies()
    groups = []
    for line in ini.splitlines():
        if not line.startswith("custom_proxy_group="):
            continue
        parts = line.split("=", 1)[1].split("`")
        name, typ, rest = parts[0], parts[1], parts[2:]
        g = {"name": name, "type": typ, "proxies": []}
        if typ == "url-test":
            url, opts = rest[-2], rest[-1].split(",")
            rest = rest[:-2]
            g |= {"url": url, "interval": int(opts[0]), "tolerance": int(opts[2])}
        for item in rest:
            if item.startswith("[]"):
                g["proxies"].append(item[2:])
            else:
                g["proxies"] += [n for n in NODES if re.search(item, n)]
        groups.append(g)
    cfg["proxy-groups"] = groups
    for line in ini.splitlines():
        if line.startswith("ruleset=") and line.endswith(",[]FINAL"):
            cfg["rules"].append(f"MATCH,{line[8:].split(',')[0]}")
    return cfg


# ---------------------------------------------------------------- Clash Party 覆写
def party_override(cfg: dict, ov: dict) -> dict:
    cfg = copy.deepcopy(cfg)
    for k, v in ov.items():
        if k.startswith("+"):
            cfg[k[1:]] = v + cfg.get(k[1:], [])
        elif k.endswith("!"):
            cfg[k[:-1]] = v
        else:
            cfg[k] = v
    return cfg


def assert_regions(cfg: dict, label: str):
    groups = {g["name"]: g["proxies"] for g in cfg["proxy-groups"]}
    for name, want in EXPECT.items():
        got = {p for p in groups[name] if p in NODES}
        if got != want:
            sys.exit(f"[{label}] {name} 匹配错误\n  期望 {sorted(want)}\n  实际 {sorted(got)}")
    for name, members in groups.items():
        bad = JUNK & set(members)
        if bad:
            sys.exit(f"[{label}] {name} 混入了信息/倍率节点 {bad}")
    for name in ("🛑 广告拦截", "🎓 上网走 🚀 节点选择 · AI走 💬 Ai平台"):
        if set(groups[name]) & set(NODES):
            sys.exit(f"[{label}] {name} 不应包含节点")


def mihomo_test(exe: str, cfg: dict, label: str, workdir: Path):
    d = workdir / label
    d.mkdir()
    f = d / "config.yaml"
    f.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    r = subprocess.run([exe, "-t", "-d", str(d), "-f", str(f)], capture_output=True, text=True, timeout=300)
    out = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0 and "test is successful" in out
    print(f"{'✓' if ok else '✗'} {label}")
    if not ok:
        print(out)
        sys.exit(1)


def main():
    exe = (sys.argv[1] if len(sys.argv) > 1 else None) or os.environ.get("MIHOMO") or shutil.which("mihomo")
    if not exe:
        sys.exit("找不到 mihomo，可执行：python3 tools/check.py /path/to/mihomo")
    meta_tpl = yaml.safe_load(build.xboard("meta"))
    stash_tpl = yaml.safe_load(build.xboard("stash"))
    base = yaml.safe_load(build.base("meta"))
    ini = build.ini("meta")
    ov = yaml.safe_load(build.overseas())

    xb = xboard_render(meta_tpl)
    assert_regions(xb, "xboard-meta")
    assert_regions(xboard_render(stash_tpl), "xboard-stash")
    sub = subconverter_render(base, ini)
    assert_regions(sub, "subconverter-meta")
    assert_regions(subconverter_render(yaml.safe_load(build.base("stash")), build.ini("stash")), "subconverter-stash")
    print("✓ 地区组 / 节点筛选正则")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mihomo_test(exe, xb, "xboard-meta", tmp)
        mihomo_test(exe, sub, "subconverter-meta", tmp)
        mihomo_test(exe, party_override(sub, ov), "subconverter-meta+overseas", tmp)
        mihomo_test(exe, party_override(xb, ov), "xboard-meta+overseas", tmp)


if __name__ == "__main__":
    main()
