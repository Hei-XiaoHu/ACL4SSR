# ACL4SSR（Hei-XiaoHu 自用版）· 代理须知

mihomo（Clash Party / CMFA）与 Stash 的分流配置和规则集。概览见 `README.md`。

## 处理 issue、新增或调整规则

一律按 `docs/maintenance.md` 的流程执行：看 issue → `tools/weekly_report.py --preview` 用最新数据核对 →
按判断表逐项处理 → 改 `rules/` + 补测试 + 写 `docs/config-updates.md` → `python3 tools/verify.py` 全部通过 →
提交推送 → `python3 tools/after_push.py` 确认发布 → 用 gh 在 issue 中回复结论并关闭。

## 必须遵守

- 源头只有 `src/spec.yaml`（组、DNS、集合顺序）与 `rules/*.txt`（本地条目，文件名 = 集合名）。
  `Clash/config/*.ini`、`Clash/customBaseConfigs/*.yml`、`Xboard/custom.*.yaml`、`Clash/override/overseas.yaml` 由
  `python3 tools/build.py` 生成，禁止手改。
- 推送前 `python3 tools/verify.py` 必须全部通过（与 CI 相同）。推送 master 会立即触发规则集重新发布到 rules 分支。
- 不要手动改 `rules` / `report` 分支，它们由 Actions 生成。
- 依据优先：官方文档 > v2fly / MetaCubeX 社区数据 > 第三方页面。不泛化整个 CDN 或供应商后缀，不用 DOMAIN-KEYWORD。
- 会改变现有放行/拦截行为、又缺少官方依据的判断，要在提交说明和 issue 回复里单独写明。
- 提交说明用一句中文概括处理内容；文档与注释用中文。

## 已定的设计（不要“顺手改掉”）

- 规则经 jsDelivr 分发，分支缓存最多约 12 小时延迟，已接受；不改为经节点从 GitHub 原地址下载。
- 不设地区策略组；🐟 漏网之鱼只接 MATCH 兜底。
- Claude：必需端点在 `ai-essential`（排在广告前）；家族域名在 `ai`（排在广告后，仍接受广告检查）；可选遥测在 `telemetry` 拦截。
  Statsig 只放行功能开关（i=）主机，拦截上报（e=）主机。详见 `docs/claude-routing.md`。
- 游戏下载 CDN 一律直连，商店/登录/社区/Steam CM 走 🎮 游戏。
