#!/usr/bin/env python3
"""用真实 mihomo 内核校验生成的配置。

模拟 Xboard / subconverter / Clash Party 覆写的渲染过程，把节点注入模板后执行 `mihomo -t`，
并断言节点筛选（排除信息/倍率节点）与空组保活。

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

# 节点名样本：真实格式 + 信息/倍率干扰项
NODES = [
    "🇭🇰 香港【华东】 S+ ⚡200M", "🇭🇰 香港 A+ ⚡500M", "🇩🇪 德国 S+ ⚡2.5G", "🇫🇷 法国 A ⚡1G",
    "🇺🇸 RN | 美东 | 水牛😐", "🇺🇸 DMIT | 美西 | 三网优化😀", "🇯🇵 Zouter | JP | 地😀", "🇸🇬 SG-01",
    "剩余流量：100 GB", "套餐到期：2027-01-01", "🇭🇰 香港 IPLC 倍率3",
]
JUNK = {"剩余流量：100 GB", "套餐到期：2027-01-01", "🇭🇰 香港 IPLC 倍率3"}
NODE_GROUPS = [g["name"] for g in build.S["groups"] if "$nodes" in g["proxies"]]
NO_NODE_GROUPS = [g["name"] for g in build.S["groups"] if "$nodes" not in g["proxies"]]


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
        # 上游先移除 regex，再在末尾追加匹配节点；不是在 regex 原位置插入。
        # 零节点时上游清理循环不执行，不能用“理想渲染”掩盖该限制。
        if NODES:
            regex = [p for p in g["proxies"] if _is_regex(p)]
            literals = [p for p in g["proxies"] if not _is_regex(p)]
            matched = [n for n in NODES if any(_pcre(p).search(n) for p in regex)] if regex else NODES
            g["proxies"] = list(dict.fromkeys([*literals, *matched]))
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


def assert_groups(cfg: dict, label: str):
    groups = {g["name"]: g["proxies"] for g in cfg["proxy-groups"]}
    if list(groups) != [g["name"] for g in build.S["groups"]]:
        sys.exit(f"[{label}] 策略组顺序/名称与 spec 不一致: {list(groups)}")
    want = [n for n in NODES if n not in JUNK]
    for name in NODE_GROUPS:
        got = [p for p in groups[name] if p in NODES]
        if set(got) != set(want):
            sys.exit(f"[{label}] {name} 节点筛选错误\n  期望 {want}\n  实际 {got}")
    for name in NO_NODE_GROUPS:
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
    assert_groups(xb, "xboard-meta")
    assert_groups(xboard_render(stash_tpl), "xboard-stash")
    sub = subconverter_render(base, ini)
    assert_groups(sub, "subconverter-meta")
    assert_groups(subconverter_render(yaml.safe_load(build.base("stash")), build.ini("stash")), "subconverter-stash")
    print("✓ 策略组顺序 / 节点筛选")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mihomo_test(exe, xb, "xboard-meta", tmp)
        mihomo_test(exe, sub, "subconverter-meta", tmp)
        mihomo_test(exe, party_override(sub, ov), "subconverter-meta+overseas", tmp)
        mihomo_test(exe, party_override(xb, ov), "xboard-meta+overseas", tmp)
        # 全部为信息/倍率节点：自动选择组只剩 REJECT 保活，不得补 DIRECT。
        global NODES
        original_nodes = NODES
        try:
            NODES = sorted(JUNK)
            for renderer, cfg in (
                ("xboard", xboard_render(meta_tpl)),
                ("subconverter", subconverter_render(base, ini)),
            ):
                groups = {g["name"]: g["proxies"] for g in cfg["proxy-groups"]}
                assert groups["♻️ 自动选择"] == ["REJECT"], (renderer, groups["♻️ 自动选择"])
                mihomo_test(exe, cfg, f"{renderer}-all-filtered", tmp)
            NODES = []
            zero_sub = subconverter_render(base, ini)
            mihomo_test(exe, zero_sub, "subconverter-zero-nodes", tmp)
            assert any(_is_regex(p) for g in xboard_render(meta_tpl)["proxy-groups"] for p in g["proxies"])
            print("! Xboard 零节点：上游可能残留 regex，需要订阅服务端处理；未声称可直接导入")
        finally:
            NODES = original_nodes


if __name__ == "__main__":
    main()
