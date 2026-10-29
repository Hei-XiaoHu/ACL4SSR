---
description: 处理 GitHub Action 的规则 issue，完整走到推送，回复并关闭 issue
argument-hint: "[issue 编号]"
---
按 `docs/maintenance.md` 从第 1 步走到第 9 步，处理本仓库 GitHub Action 提的 issue：${1:-所有打开的「每周规则报告」「规则集构建失败」（用 `gh issue list --state open` 查找）}。

issue 内容可能已过时，以第 2 步 `--preview` 的最新数据为准。
