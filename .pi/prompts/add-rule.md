---
description: 新增或调整一条分流规则，完整走到推送
argument-hint: "<域名> [期望去向或说明]"
---
在本仓库为 `$1` 新增或调整分流规则。${@:2}

按 `docs/maintenance.md` 执行：
1. 先确认它现在实际走哪：用 `tools/build_rules.py` 的 `fetch_all` / `collect` / `route_table` / `route` 按当日规则计算（mihomo 与 Stash 都看），
   并查它的用途与归属（优先官方文档）。
2. 按 README「修改规则」表与 `src/spec.yaml` 的集合顺序选定文件；精确主机优先，不泛化整个 CDN / 供应商后缀，写注释说明用途与依据。
   若去向不明确或会改变现有放行/拦截行为又缺少依据，先问我。
3. 在 `tools/check_routing.py`（必要时 `tools/check_rules.py`）补用例，在 `docs/config-updates.md` 顶部记录。
4. `python3 tools/verify.py` 全部通过后提交推送，再运行 `python3 tools/after_push.py` 确认发布。
5. 汇报：放在哪个文件、前后去向、提交哈希；提醒客户端最多约 12 小时后生效。
