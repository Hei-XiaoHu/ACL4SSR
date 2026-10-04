#!/usr/bin/env python3
"""同步小型国内标签的 Stash DNS 缓存；普通 build/check 不需要网络。"""
import concurrent.futures
import sys
import urllib.request
import yaml

import build


def main():
    names = [name for name in build.S["dns_china_sets"]
             if "@" in build.S["providers"][name].get("geosite", "")]
    providers = build.providers("stash")

    def fetch(name):
        req = urllib.request.Request(providers[name]["url"], headers={"User-Agent": "ACL4SSR-DNS-sync"})
        with urllib.request.urlopen(req, timeout=30) as response:
            rows = yaml.safe_load(response.read())["payload"]
        if not rows or any(not isinstance(row, str) or "," in row for row in rows):
            raise ValueError(f"{name}: 不是非空 domain payload")
        return rows

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            rows = sorted({row for payload in pool.map(fetch, names) for row in payload})
        expected = {"providers": names, "payload": rows}
        path = build.ROOT / build.S["stash_dns_cn_cache"]
        current = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
        if "--check" in sys.argv:
            if current != expected:
                old = set(current["payload"]) if current else set()
                print("Stash DNS 标签缓存与上游不同；请运行 tools/update_stash_dns.py 后重新 build。")
                print("新增:", sorted(set(rows) - old))
                print("移除:", sorted(old - set(rows)))
                return 1
            print(f"✓ Stash DNS 国内标签缓存：{len(rows)} 条，与上游一致")
        else:
            text = "# 由 tools/update_stash_dns.py 从维护中的国内属性标签生成；勿手改。\n"
            text += "# 路由 provider 仍每日下载上游；此缓存仅用于 Stash DNS 字面域名。\n"
            text += yaml.safe_dump(expected, allow_unicode=True, sort_keys=False)
            path.write_text(text, encoding="utf-8")
            print(f"已更新 {path.relative_to(build.ROOT)}：{len(rows)} 条；请运行 tools/build.py")
        return 0
    except Exception as error:
        print(f"Stash DNS 同步失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
