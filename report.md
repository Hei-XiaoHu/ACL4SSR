# 每周规则报告（2026-11-23 09:18 北京时间）

**本周需要关注：** 旧 ACL4SSR 未审阅差异 8 条；geosite:category-ai-!cn +1 -0；geosite:anthropic 待固定 2 条

## 关注的上游集合（相比上周）

- `geosite:category-game-platforms-download`：无变化（491 条）
- `geosite:category-ai-!cn`：新增 1、删除 0（现 218 条，预期去向 🤖 AI）
  - 新增：`+.elevenlabsusercontent.com`

新增条目已自动进入对应集合。⚠️ 表示实际去向与该集合不同：新增的被排在前面的集合截走（如遥测被 🛑 拦截属预期），删除的已不再命中原去向。
删除的主机若仍在使用，加进对应的 `rules/*.txt`（下载主机加进 `rules/direct.txt`）。

## 本地固定清单（spec `pin`）

- `geosite:anthropic` → `rules/ai.txt`：待固定 2 条：`http-intake.logs.us5.datadoghq.com`, `o1158394.ingest.us.sentry.io`

## 旧 ACL4SSR 与当前规则的默认去向差异

未审阅差异 **8** 条（已审阅忽略 2784 条）。只比较 DOMAIN/DOMAIN-SUFFIX；“按IP”表示新版域名规则都未命中，取决于 IP 是否在国内。

| 旧列表 | 变化 | 条数 | 示例 |
|---|---|---|---|
| ProxyGFWlist | 代理→直连 | 6 | `+.bbs.sina.com`, `+.dailynews.sina.com`, `+.home.sina.com`, `+.longbridge.cn`, `+.play-analytics.com` |
| ProxyGFWlist | 代理→拦截 | 2 | `+.appsflyersdk.com`, `+.tbskkinabalu.page.tl` |

<details><summary>全部条目</summary>

| 条目 | 旧列表 / 旧组 | 新集合 / 新组 |
|---|---|---|
| `+.appsflyersdk.com` | ProxyGFWlist / 🚀 节点选择 | ads / 🛑 广告 |
| `+.bbs.sina.com` | ProxyGFWlist / 🚀 节点选择 | cn / 🎯 直连 |
| `+.dailynews.sina.com` | ProxyGFWlist / 🚀 节点选择 | cn / 🎯 直连 |
| `+.home.sina.com` | ProxyGFWlist / 🚀 节点选择 | cn / 🎯 直连 |
| `+.longbridge.cn` | ProxyGFWlist / 🚀 节点选择 | cn / 🎯 直连 |
| `+.play-analytics.com` | ProxyGFWlist / 🚀 节点选择 | cn / 🎯 直连 |
| `+.tbskkinabalu.page.tl` | ProxyGFWlist / 🚀 节点选择 | ads / 🛑 广告 |
| `+.wiki.keso.cn` | ProxyGFWlist / 🚀 节点选择 | cn / 🎯 直连 |

</details>

旧列表共 10159 条域名规则；另有 597 条关键词/IP/其他规则未比较。

---
处理方式：确需调整的条目加进 `rules/` 下对应文件；有意不同的条目连同理由记入 `src/legacy-review.yaml`，下周不再出现。完整流程见 `docs/maintenance.md`；处理完由仓库所有者回复结论并关闭，下次有新条目时会自动重新打开。
