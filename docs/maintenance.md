# 维护流程：从 issue 到推送

本仓库的规则维护固定按下面的流程走，人工或 AI 代理（见根目录 `AGENTS.md`、pi 命令 `/weekly-review`、`/add-rule`）都一样。
目标：每次改动都有依据、有测试、有记录，推送后确认已发布。

## 什么时候需要处理

| 来源 | 说明 |
|---|---|
| issue「每周规则报告」被重新打开 | `weekly.yml` 每周一 05:00（北京时间）生成；只有出现待处理条目时才追加评论并重新打开 |
| issue「规则集构建失败」 | `rules.yml` 每日构建失败时记录，客户端继续用上一版；恢复后自动关闭 |
| 自己发现某个域名走错，或要新增规则 | 第 1 步后改做第 2 步的「单个域名」核对，再从第 3 步开始 |

**issue 状态约定**：打开 = 有待处理条目；处理完在 issue 中回复结论并关闭。下次有新条目时 Action 会自动重新打开。

## 步骤

### 1. 准备

```bash
git pull --ff-only
pip install pyyaml            # 唯一依赖；gh CLI 需已登录
gh issue list --state open
gh issue view <编号> --comments
```

### 2. 用最新数据预览

issue 内容是生成当时的数据，上游之后可能又有变化。以 report 分支的基准为“上周”重新算一遍（只打印，不写任何分支）：

```bash
python3 tools/weekly_report.py --preview
```

**单个域名**：按当日规则算出它现在实际命中哪个集合、走哪个组（mihomo 与 Stash 都看；都未命中则按 IP / 兜底）：

```bash
cd tools && python3 - <域名> [域名...] <<'EOF'
import sys, build, build_rules as br
cache = br.fetch_all()
tables = {t: br.route_table(br.collect(t, cache)) for t in build.TARGETS}
for host in sys.argv[1:]:
    print(host, {t: br.route(tables[t], host) for t in tables})
EOF
```

同时查清它的用途与归属（优先官方文档）。

### 3. 逐项判断

| 报告中的情况 | 处理 |
|---|---|
| 关注集合「新增」，无 ⚠️ | 已自动进入对应集合，无需操作 |
| 「新增」带 ⚠️，被 `telemetry` / `ads` 截走 | 确认是遥测/统计 → 预期，无需操作；确认是功能端点 → 放进排在广告前的 `ai-essential.txt`（AI）或 `local-direct.txt`（直连） |
| 「新增」带 ⚠️，被其他服务集合截走 | 判断归属；需要改去向时放进更靠前的本地文件（顺序见 `src/spec.yaml` 的 `sets`） |
| 「删除」带 ⚠️ | 主机仍在使用 → 加进对应 `rules/*.txt`（下载主机进 `direct.txt`）；已废弃 → 无需操作 |
| 本地固定清单「待固定」 | 把列出的条目加进对应文件（`geosite:anthropic` → `rules/ai.txt` 的 Claude 家族段，并更新该段的同步日期） |
| 旧 ACL4SSR 未审阅差异 | 采纳 → 加进 `rules/`；不采纳 → 连同理由记入 `src/legacy-review.yaml` |
| 构建失败：上游下载失败 | 多为临时网络问题，Actions 页面重跑；持续失败再考虑换源 |
| 构建失败：条目数骤减 | 打开对应上游确认。确属异常 → 等上游恢复；确属正常删减 → Actions 手动运行「构建并发布规则集」并勾选 `skip_shrink_check` |
| 构建失败：本地条目被前面的集合截走 | 按日志提示：必需端点挪进 `ai-essential.txt` / `local-direct.txt`，不再需要的删掉 |
| 构建失败：关键域名分流错误（check_rules） | 看日志中的“实际”命中集合，按上面同样的原则调整 |

判断依据优先级：官方文档 / 官方清单 > v2fly、MetaCubeX 社区数据 > 第三方参考页。

**先问再改**：去向不明确，或查不到官方依据、又会改变现有放行/拦截行为的条目，AI 代理先列出来询问维护者，不要自行决定；
确认后照做，并在提交说明与 issue 回复中单独列出，便于日后回退。

### 4. 修改

- 条目放哪：见 README「修改规则」表。原则：精确主机优先，不泛化整个 CDN / 供应商后缀；
  `example.com` 精确，`+.example.com` 含子域名；每组条目写注释说明用途与依据链接/日期。
- 重要端点同时补测试：离线回归 `tools/check_routing.py`（夹具与 cases）、发布把关 `tools/check_rules.py` 的 `CASES`。
- 改了 `src/spec.yaml` 要运行 `python3 tools/build.py` 重新生成配置；十份生成文件不要手改。
- 记录：`docs/config-updates.md` 顶部加一节「日期 + 标题」，写清处理了哪些条目、为什么；Claude 相关同步 `docs/claude-routing.md`。

### 5. 推送前校验

```bash
python3 tools/verify.py        # 与 CI 完全相同；必须全部通过
```

依次运行：spec 自检与生成一致性 → mihomo -t 渲染校验 → 分流/QUIC/广告/DNS 泄露回归 → 当日上游核对 →
试构建规则集（含骤减保护）→ 真实规则集关键域名。mihomo 自动下载到 `.cache/`。

### 6. 提交推送

```bash
git add -A
git commit -m "<一句话中文概括：处理了什么 + 关键改动>"
git push
```

推送 `rules/`、`src/spec.yaml`、规则相关工具时会立刻触发 `rules.yml` 重新发布；内容未变则不发布。

### 7. 推送后确认

```bash
python3 tools/after_push.py    # 等本次提交的 Actions 结束，确认 rules 分支已发布
```

客户端经 jsDelivr 下载，最多约 12 小时后才拿到新版（README「生效延迟」）。

### 8. 回复并关闭 issue

按下面的模板回复（`gh issue comment <编号> --body ...`），然后 `gh issue close <编号>`：

```text
已处理（提交 <短哈希>）：
- <条目/情况>：<处理方式与理由>
- 无需操作：<条目>（<原因>）
校验：tools/verify.py 全部通过；规则集已发布（rules 分支 <时间>），客户端最多约 12 小时后生效。
```

「规则集构建失败」issue 在下一次构建成功时由 Action 自动关闭。

没有需要处理的条目时，仍完成第 2 步的预览核对，回复“无需操作”的结论并关闭 issue，不产生提交。

### 9. 汇报（AI 代理）

最后向维护者简要汇报：

- 处理了哪些条目：放在哪个文件、改前 → 改后的去向（第 2 步的核对结果）；
- 哪些无需操作及原因；
- 提交哈希、规则集发布时间，并提醒客户端最多约 12 小时后生效。
