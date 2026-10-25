#!/usr/bin/env python3
"""推送后确认：等待当前提交触发的 GitHub Actions 全部结束，并确认规则集是否已发布到 rules 分支。

用法：python3 tools/after_push.py [--sha 提交] [--timeout 秒]
需要已登录的 gh CLI。任一工作流失败退出码 1（rules 失败时上一版规则保持不变，失败会记到 issue）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

RULES_WORKFLOW = "构建并发布规则集（rules 分支）"


def sh(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def runs_for(sha: str) -> list[dict]:
    out = sh("gh", "run", "list", "--limit", "30", "--json",
             "databaseId,headSha,workflowName,status,conclusion,event,url")
    return [r for r in json.loads(out) if r["headSha"] == sha and r["event"] == "push"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default="HEAD")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()
    sha = sh("git", "rev-parse", args.sha)
    remote = sh("git", "ls-remote", "origin", "refs/heads/master").split()[0]
    if remote != sha:
        print(f"! origin/master 是 {remote[:7]}，不是 {sha[:7]}：是否还没推送？")
        return 1

    deadline = time.monotonic() + args.timeout
    runs: list[dict] = []
    while time.monotonic() < deadline:
        runs = runs_for(sha)
        pending = [r for r in runs if r["status"] != "completed"]
        # 推送后 Actions 需要几秒才登记；至少看到一个运行且全部结束才算完成
        if runs and not pending:
            break
        names = ", ".join(r["workflowName"] for r in pending) or "等待 Actions 登记"
        print(f"… {sha[:7]} 进行中：{names}", flush=True)
        time.sleep(20)
    else:
        print(f"✗ 等待超时（{args.timeout}s）")
        return 1

    failed = False
    for r in runs:
        ok = r["conclusion"] == "success"
        failed |= not ok
        print(f"{'✓' if ok else '✗'} {r['workflowName']}：{r['conclusion']}  {r['url']}")

    if any(r["workflowName"] == RULES_WORKFLOW for r in runs):
        subprocess.run(["git", "fetch", "-q", "origin", "rules"], check=False)
        subject = sh("git", "log", "-1", "--format=%s", "origin/rules")
        manifest = json.loads(sh("git", "show", "origin/rules:manifest.json"))
        if sha[:7] in subject:
            print(f"✓ 规则集已发布：{subject}")
            print("  客户端经 jsDelivr 最多约 12 小时后拿到新版；浏览器打开下面地址看 generated 判断 CDN 是否已更新：")
            print("  https://fastly.jsdelivr.net/gh/Hei-XiaoHu/ACL4SSR@rules/manifest.json")
        elif not failed:
            print(f"i 规则内容与上一版相同，未重新发布（rules 分支仍为 {manifest['generated']}）")
    else:
        print("i 本次改动不涉及规则集，rules 工作流未触发")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
