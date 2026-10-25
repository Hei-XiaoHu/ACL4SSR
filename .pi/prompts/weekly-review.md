---
description: 处理 GitHub Action 的规则 issue，完整走到推送，并起草 issue 回复
argument-hint: "[issue 编号]"
---
按 `docs/maintenance.md` 完整处理本仓库 GitHub Action 提的 issue，一直做到推送并确认发布。要处理的 issue：${1:-所有打开的「每周规则报告」「规则集构建失败」（用 `gh issue list --state open` 查找）}。

1. 读 issue 与评论；运行 `python3 tools/weekly_report.py --preview` 用最新数据核对（issue 可能已过时）。
2. 按 `docs/maintenance.md` 第 3 步的判断表逐项决定；需要查依据时优先官方文档。
   没有官方依据、又会改变现有放行/拦截行为的条目，先列出来问我，不要自行决定。
3. 修改 `rules/` 等源文件，给重要端点补 `tools/check_routing.py` / `tools/check_rules.py` 用例，在 `docs/config-updates.md` 顶部记录。
4. 运行 `python3 tools/verify.py`，必须全部通过；失败就修复后重跑。
5. 提交（一句中文概括）并推送 master，然后运行 `python3 tools/after_push.py` 确认 Actions 成功、规则集已发布。
6. 按 `docs/maintenance.md` 第 8 步的模板起草 issue 回复，放在汇报里交给我。不要用 gh 在 GitHub 上评论、关闭或编辑 issue（gh 登录的不是仓库所有者）。
7. 最后简要汇报：处理了哪些条目、哪些无需操作及原因、提交哈希、发布时间。

如果 issue 中没有需要处理的条目，仍然完成预览核对，起草“无需操作”的回复交给我，不产生提交。
