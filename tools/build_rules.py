#!/usr/bin/env python3
"""合并本地 rules/*.txt 与上游列表，生成发布到 rules 分支的规则集。

用法：
  python3 tools/build_rules.py --out dist --mihomo /path/to/mihomo [--previous old/manifest.json]
  python3 tools/build_rules.py --conflicts      只下载并报告集合间的覆盖关系，不生成文件

输出（dist/）：
  mihomo/<集合>.mrs     domain / ipcidr（mihomo convert-ruleset 转换）
  mihomo/<集合>.yaml    classical（含正则的 local-direct）
  stash/<集合>.yaml     domain / ipcidr / classical
  manifest.json         每个集合的条目数、来源与内容指纹，供下次比较
失败（退出码 1，不应发布）：任一上游下载/解析失败；某集合条目数比上一版少 30% 以上；转换失败。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import ipaddress
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

import build

GEO_RAW = "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo"
SHRINK_LIMIT = 0.7  # 新条目数低于上一版的 70% 视为上游异常


# ---------------------------------------------------------------- 下载与解析
def source_url(src: str) -> tuple[str, str | None]:
    kind, _, name = src.partition(":")
    if kind in ("geosite", "geoip") and name:
        return f"{GEO_RAW}/{kind}/{name}.yaml", None
    spec = build.S["upstream"][src]
    return spec["url"], spec.get("plain")


def _download(url: str) -> str:
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ACL4SSR-rules-builder"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - 统一重试
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"下载失败 {url}: {last}")


def fetch(src: str) -> list[str]:
    url, plain = source_url(src)
    body = _download(url)
    if url.endswith((".yaml", ".yml")):
        rows = yaml.safe_load(body).get("payload") or []
    else:
        rows = [line.strip() for line in body.splitlines()
                if line.strip() and not line.lstrip().startswith(("#", "!"))]
    out = []
    for row in rows:
        row = str(row).strip().strip("'\"").lower()
        if not row:
            continue
        if plain == "suffix" and not row.startswith(("+.", ".", "*")):
            row = "+." + row
        out.append(row)
    if not out:
        raise RuntimeError(f"上游为空 {src}: {url}")
    return out


# ---------------------------------------------------------------- 合并
def _host(entry: str) -> str:
    return entry[2:] if entry.startswith("+.") else entry[1:] if entry.startswith(".") else entry


def merge_domains(rows: list[str]) -> list[str]:
    """去重；删除已被同集合内 +.父域 覆盖的条目（同一去向，结果不变）。"""
    unique = sorted(set(rows))
    suffixes = {e[2:] for e in unique if e.startswith("+.")}
    out = []
    for entry in unique:
        if "*" in entry:
            out.append(entry)
            continue
        host = _host(entry)
        labels = host.split(".")
        parents = [".".join(labels[i:]) for i in range(1, len(labels))]
        if any(p in suffixes for p in parents):
            continue
        if not entry.startswith("+.") and host in suffixes:
            continue
        out.append(entry)
    return out


def merge_ips(rows: list[str]) -> list[str]:
    nets = [ipaddress.ip_network(r, strict=False) for r in rows]
    v4 = ipaddress.collapse_addresses(n for n in nets if n.version == 4)
    v6 = ipaddress.collapse_addresses(n for n in nets if n.version == 6)
    return [str(n) for n in (*v4, *v6)]


def collect(target: str, cache: dict) -> dict[str, list[str]]:
    result = {}
    for name in build.SETS:
        if not build.has_provider(name, target):
            continue
        rows = list(build.local_rows(name))
        for src in build.fetched_sources(name, target):
            rows += cache[src]
        kind = build.set_type(name)
        if kind == "classical":
            result[name] = [build.classical_line(r) for r in dict.fromkeys(rows)]
        elif kind == "ip":
            result[name] = merge_ips(rows)
        else:
            result[name] = merge_domains(rows)
        if not result[name]:
            raise RuntimeError(f"[{target}] 集合为空: {name}")
    return result


# ---------------------------------------------------------------- 输出
def write_outputs(out: Path, sets: dict[str, dict[str, list[str]]], mihomo: str):
    for target, by_name in sets.items():
        folder = out / build.OUT_DIR[target]
        folder.mkdir(parents=True, exist_ok=True)
        for name, rows in by_name.items():
            rel = build.provider_file(name, target)
            path = out / rel
            if rel.endswith(".yaml"):
                path.write_text(yaml.safe_dump({"payload": rows}, allow_unicode=True, sort_keys=False, width=100000),
                                encoding="utf-8")
                continue
            behavior = "ipcidr" if build.set_type(name) == "ip" else "domain"
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
                tmp.write("\n".join(rows) + "\n")
            r = subprocess.run([mihomo, "convert-ruleset", behavior, "text", tmp.name, str(path)],
                               capture_output=True, text=True)
            Path(tmp.name).unlink()
            if r.returncode != 0 or not path.exists() or path.stat().st_size == 0:
                raise RuntimeError(f"mrs 转换失败 {rel}: {r.stdout}{r.stderr}")


def check_shrink(manifest: dict, previous: dict) -> list[str]:
    problems = []
    for target, by_name in manifest["counts"].items():
        for name, count in by_name.items():
            old = previous.get("counts", {}).get(target, {}).get(name)
            if old and count < old * SHRINK_LIMIT:
                problems.append(f"[{target}] {name}: {old} → {count}（减少超过 {int((1 - SHRINK_LIMIT) * 100)}%）")
    return problems


# ---------------------------------------------------------------- 覆盖关系报告
def _covered(host: str, exact: set[str], suffixes: set[str]) -> bool:
    labels = host.split(".")
    return host in exact or any(".".join(labels[i:]) in suffixes for i in range(len(labels)))


def conflicts(cache: dict, target: str = "meta"):
    """列出排序后可能改变去向的条目：后面集合的条目被前面不同去向的集合覆盖。"""
    order = [item["name"] for item in build.S["sets"]
             if isinstance(item, dict) and item.get("to") and build.set_type(item["name"]) == "domain"
             and build.has_provider(item["name"], target)]
    per_source = {}
    for name in order:
        for src in ["local", *build.fetched_sources(name, target)]:
            rows = build.local_rows(name) if src == "local" else cache[src]
            per_source[(name, src)] = rows
    for i, later in enumerate(order):
        for earlier in order[:i]:
            if build.SETS[earlier]["to"] == build.SETS[later]["to"]:
                continue
            e_rows = [r for (n, _), rows in per_source.items() if n == earlier for r in rows]
            exact = {r for r in e_rows if not r.startswith(("+.", "."))}
            suffixes = {_host(r) for r in e_rows if r.startswith("+.")}
            for (n, src), rows in per_source.items():
                if n != later:
                    continue
                hits = [r for r in rows if "*" not in r and _covered(_host(r), exact, suffixes)]
                if hits:
                    sample = ", ".join(hits[:6]) + (" ..." if len(hits) > 6 else "")
                    print(f"{later}[{src}] 被 {earlier}（{build.SETS[earlier]['to']}）截走 {len(hits)} 条: {sample}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--mihomo")
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--conflicts", action="store_true")
    args = ap.parse_args()

    needed = sorted({src for t in build.TARGETS for n in build.SETS if build.has_provider(n, t)
                     for src in build.fetched_sources(n, t)})
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        cache = dict(zip(needed, pool.map(fetch, needed)))
    if args.conflicts:
        conflicts(cache)
        return 0
    if not args.out or not args.mihomo:
        ap.error("需要 --out 与 --mihomo")

    sets = {t: collect(t, cache) for t in build.TARGETS}
    manifest = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {t: {n: len(rows) for n, rows in by.items()} for t, by in sets.items()},
        "sources": {n: {t: build.fetched_sources(n, t) for t in build.TARGETS} for n in build.SETS},
        "upstream_counts": {src: len(rows) for src, rows in cache.items()},
    }
    if args.previous and args.previous.exists() and args.previous.stat().st_size:
        problems = check_shrink(manifest, json.loads(args.previous.read_text(encoding="utf-8")))
        if problems:
            print("条目数异常减少，本次不发布：\n" + "\n".join(problems))
            return 1
    args.out.mkdir(parents=True, exist_ok=True)
    write_outputs(args.out, sets, args.mihomo)
    # 内容指纹：只覆盖规则内容（不含生成时间），内容未变时 Action 不重复发布
    digest = hashlib.sha256()
    for path in sorted(args.out.rglob("*")):
        if path.is_file() and path.parent != args.out:
            digest.update(path.relative_to(args.out).as_posix().encode() + b"\0" + path.read_bytes())
    manifest["content_sha256"] = digest.hexdigest()
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "README.md").write_text(
        "# rules 分支（自动生成，请勿手改）\n\n"
        "由 master 上的 `tools/build_rules.py` 合并 `rules/*.txt` 与上游列表生成，每日更新。\n"
        "`mihomo/` 供 Clash Party / CMFA，`stash/` 供 Stash；条目数见 `manifest.json`。\n",
        encoding="utf-8")
    for target, by in manifest["counts"].items():
        print(f"[{target}] " + "  ".join(f"{n}:{c}" for n, c in by.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
