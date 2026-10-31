#!/usr/bin/env python3
"""推送前一键校验：按 CI 与每日发布的顺序跑全部检查，任一失败即退出码 1。

用法：
  python3 tools/verify.py                  全部检查（需联网）
  python3 tools/verify.py --offline        只跑离线检查（spec 自检/生成一致性、内核校验、分流与 DNS 回归）
  python3 tools/verify.py --mihomo PATH    指定 mihomo；默认依次用环境变量 MIHOMO、PATH 中的 mihomo、
                                           .cache/ 下自动下载的最新正式版（linux/darwin amd64/arm64）

步骤（与 .github/workflows/check.yml、rules.yml 一致）：
  1 build.py --check       spec 自检 + 十份生成文件与 src/spec.yaml 一致
  2 check.py               Xboard / subconverter / 国外覆写渲染后 mihomo -t
  3 check_routing.py       本地夹具：分流顺序、QUIC、广告、DNS 泄露
  4 check_upstream.py      当日上游：Claude 不在 cn、本地条目未被前面的集合截走          （联网）
  5 build_rules.py         用当日上游试构建规则集，含骤减保护（对比 rules 分支上一版）   （联网）
  6 check_rules.py         真实规则集关键域名分流                                       （联网）
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
CACHE = ROOT / ".cache"


def _api(url: str) -> dict:
    headers = {"User-Agent": "ACL4SSR-verify", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
        return json.load(resp)


def mihomo_path(given: str | None) -> str:
    found = given or os.environ.get("MIHOMO") or shutil.which("mihomo")
    if found:
        # 各步骤在 tools/ 下运行，相对路径（如 CI 的 ./mihomo）按调用时的目录解析为绝对路径
        path = Path(found).resolve() if os.sep in found else Path(shutil.which(found) or found).resolve()
        if not path.is_file():
            sys.exit(f"找不到 mihomo：{found}")
        return str(path)
    system = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    if not system or not arch:
        sys.exit(f"无法自动下载 mihomo（{platform.system()} {platform.machine()}），请用 --mihomo 指定")
    cached = sorted(CACHE.glob(f"mihomo-{system}-{arch}-v*"))
    try:
        release = _api("https://api.github.com/repos/MetaCubeX/mihomo/releases/latest")
    except Exception as exc:  # noqa: BLE001 - 离线时退回已缓存版本
        if cached:
            print(f"! 查询 mihomo 最新版失败（{exc}），使用缓存 {cached[-1].name}")
            return str(cached[-1])
        sys.exit(f"下载 mihomo 失败：{exc}")
    name = f"mihomo-{system}-{arch}-{release['tag_name']}"
    target = CACHE / name
    if not target.exists():
        asset = next((a for a in release["assets"] if a["name"] == f"{name}.gz"), None)
        if not asset:
            sys.exit(f"最新发布中没有 {name}.gz，请用 --mihomo 指定")
        CACHE.mkdir(exist_ok=True)
        print(f"下载 {asset['browser_download_url']}")
        with urllib.request.urlopen(asset["browser_download_url"], timeout=120) as resp:
            target.write_bytes(gzip.decompress(resp.read()))
        target.chmod(0o755)
        for old in cached:
            old.unlink()
    return str(target)


def previous_manifest(dest: Path) -> Path | None:
    """rules 分支上一版 manifest（骤减保护的对比基准）；取不到时跳过骤减检查。"""
    url = f"https://raw.githubusercontent.com/Hei-XiaoHu/ACL4SSR/rules/manifest.json?t={int(time.time())}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            dest.write_bytes(resp.read())
        return dest
    except Exception as exc:  # noqa: BLE001
        print(f"! 取不到 rules 分支上一版 manifest（{exc}），跳过骤减检查")
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mihomo")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    results: list[tuple[str, bool, float]] = []

    def step(label: str, cmd: list[str]) -> bool:
        print(f"\n━━ {label}\n$ {' '.join(cmd)}", flush=True)
        start = time.monotonic()
        ok = subprocess.run(cmd, cwd=TOOLS).returncode == 0
        results.append((label, ok, time.monotonic() - start))
        return ok

    py = sys.executable
    if step("spec 自检 + 生成文件一致", [py, "build.py", "--check"]):
        exe = mihomo_path(args.mihomo)
        step("mihomo -t 渲染校验", [py, "check.py", exe])
        step("分流 / QUIC / 广告 / DNS 泄露回归", [py, "check_routing.py", exe])
        if not args.offline:
            step("当日上游核对", [py, "check_upstream.py"])
            with tempfile.TemporaryDirectory(prefix="acl4ssr-verify-") as tmp:
                dist = Path(tmp) / "dist"
                cmd = [py, "build_rules.py", "--out", str(dist), "--mihomo", exe]
                prev = previous_manifest(Path(tmp) / "prev.json")
                if prev:
                    cmd += ["--previous", str(prev)]
                if step("试构建规则集（含骤减保护）", cmd):
                    step("真实规则集关键域名", [py, "check_rules.py", "--dist", str(dist), "--mihomo", exe])

    print("\n━━ 汇总")
    for label, ok, sec in results:
        print(f"{'✓' if ok else '✗'} {label}（{sec:.0f}s）")
    failed = [label for label, ok, _ in results if not ok]
    if failed:
        print(f"\n✗ {len(failed)} 项失败，不要推送")
        return 1
    print("\n✓ 全部通过" + ("（仅离线检查，推送前请再跑一次完整校验）" if args.offline else "，可以推送"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
