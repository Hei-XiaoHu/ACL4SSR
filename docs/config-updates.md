# 配置修复与最终复核

对应 [初始审计](mihomo-stash-audit.md) 的修改前快照。配置已按 Claude → 其他分类 → DNS/非规则配置 → 整体校验的顺序复核。

## 2026-10-31 新增 Clash Party / FlClash 本地覆写模板（Clash/override/*.js）

- 把维护者本机的三个 JavaScript 覆写去掉节点名、IP、域名与凭据后整理为模板：`game-ports.js`（ProxiFyre 按端口分配游戏节点）、`pinned-node.js`（指定域名/IP 固定节点 + tunnels）、`local-node.js`（追加自有节点）。手写文件，不经 build.py。
- `pinned-node.js` 的主要改动：IP 规则分两组——插在最前面的自动补 `no-resolve`；要按"解析后的 IP"匹配的放 `LATE_IP_RULES`，插到 `RULE-SET,cn-ip` 之前。原因：规则自上而下匹配，不带 `no-resolve` 的 IP 规则放第一条会让每个域名连接都先用主 nameserver 解析一次（结果对走代理的连接无用，对直连连接也不被 `direct-nameserver` 复用），而 cn-ip 是本套规则里唯一需要解析的一条，放它前面不增加解析。核对 `geosite:geolocation-!cn` 的顶级域条目只有 `.google`、`.xbox` 等 66 个品牌 TLD，个人域名不会被 foreign 截走，能走到 cn-ip。其他改动：规则不写去向默认走 NODE、`FALLBACK` 可指定节点缺失时的替代去向、隧道改数组并按 address 去重、幂等清理。
- `game-ports.js`：`match` 支持正则或精确名，可匹配策略组名；兜底改为常量。`local-node.js`：支持多个节点、`ANCHOR` 可为 null。三份模板用 Node 模拟 `main(config)` 跑过正常/幂等/节点缺失三种情况。
- README 新增"本地覆写模板"一节，含 FlClash 单脚本限制下的合并写法，以及 Stash 覆写只能前插或 `#!replace`、应改用域名规则的说明。

## 2026-10-31 Stash 配置改为与 mihomo 同一套规则集；删除完整版并列文件

- 维护者在 iOS 最新版 Stash 上导入完整版（约 36 万条域名）实测：规则集全部加载，番茄/红果广告消失，未出现崩溃。据此把标准版 Stash 配置（`_Stash.ini` / `dns_enhanced_stash.yml` / `custom.stash.yaml`）直接改成完整版内容，删除昨日新增的三份 `_Full` 文件与 `stash-full` 生成目标。用户与 Xboard 同步脚本无需改动，刷新订阅即得新版。
- `src/spec.yaml` 删除 `awavenue` 上游与 `stash_native`；`ads` 不再按客户端分来源（`from: {meta, stash}` 写法随之取消）。两客户端现在共用同一份规则集定义，唯一差别仍是 `clients: [meta]` 的 bt 进程规则。
- `rules` 分支不再发布 `stash/` 目录：Stash 直接下载 `mihomo/` 目录的文件（mrs 两边同格式，字节级一致），`manifest.json` 的 `counts` / `sources` 改为单层（不再按客户端分组；骤减保护兼容读取旧版 `counts.meta`）。仍用旧 Stash 配置的客户端刷新规则集会 404 并沿用本地缓存，刷新订阅后即切换。
- 规则集缓存路径改为与 URL 同构的 `./ruleset/acl4ssr/mihomo/<集合>`（mihomo 与 Stash 相同）：保证旧 Stash 配置缓存的 950 条 `ads.mrs` 不会被新配置先读到；mihomo 侧因此重新下载一次（约 2.8 MB）。
- Stash DNS policy 的 `geosite:private` / `geosite:cn` 改为 `rule-set:private` / `rule-set:cn`，整份配置不再依赖原生 GEOSITE 数据（不需要 GitHub 可达）。
- 校验：`check_routing.assert_outputs` 断言 Stash 规则去掉 DoH 端点 IP 绑定后与 mihomo 逐条相同（仅 `DST-PORT,443` → `PROTOCOL,QUIC`、无 bt），provider 定义（URL、缓存路径）与 mihomo 完全相同，规则与 DNS 均无 GEOSITE/GEOIP；`check_upstream` 只需按一份规则集检查。`python3 tools/verify.py` 全部通过。
- 内存结论的边界：只在维护者一台设备、最新 Stash 上确认过可加载和日常使用；长期常驻占用与规则集每日更新时的峰值未测量。隧道无故断开时查 iOS 分析数据里的 `JetsamEvent`（`reason: per-process-limit`）。

## 2026-10-31 新增 Stash 完整版配置（规则与 mihomo 一致）

- 起因：番茄小说 / 红果短剧的广告在 mihomo 上能拦、Stash 上拦不住。对比当日三份广告源：字节系穿山甲（`pglstatp-toutiao.com`、`pangolin-sdk-toutiao.com`、`*.fqnovel.com` 等）在 AdRules 是整个后缀、anti-AD 也大量收录，AWAvenue（约 970 条，仅 12 条后缀规则）只列了个别主机名。不是 MITM 的问题——mihomo 按域名就能拦掉，Stash 缺的只是规则。
- 新增生成目标 `stash-full`（`build.FULL`），输出 `Clash/config/ACL4SSR_Online_Full_AdblockPlus_Stash_Full.ini`、`Clash/customBaseConfigs/dns_enhanced_stash_full.yml`、`xboard/custom.stash-full.yaml`。与标准版 Stash 的差别只有：规则集全部指向 `rules` 分支 `mihomo/` 目录（mrs 两边同格式，不另发一套），因此 `ads` 变成 AdRules + anti-AD，`cn` / `foreign` / `cn-ip` 变成规则集而非 `GEOSITE,cn` / `GEOSITE,geolocation-!cn` / `GEOIP,CN`；DNS policy 的 `geosite:private` / `geosite:cn` 相应改为 `rule-set:private` / `rule-set:cn`，整份配置不再依赖原生 GEOSITE 数据。规则集缓存目录用 `./ruleset/acl4ssr-full/`，避免 Stash 启动时先读到标准版缓存的小文件。`bt` 仍只在 mihomo（进程规则）。
- 标准版 Stash 配置与 Xboard `stash` 槽位不动：约 36 万条域名规则对 iOS 网络扩展 50 MB 上限是否够用无法静态判断（Stash 官方 FAQ 只给了上限；公开崩溃案例是 yaml 格式 30 万条，mrs 常驻占用没有数据），需维护者实机导入完整版观察内存，稳定后再决定是否替换。
- 校验：`check_routing.assert_outputs` 断言完整版规则列表去掉 DoH 端点 IP 绑定后，与 mihomo 的规则逐条相同（仅 `DST-PORT,443` → `PROTOCOL,QUIC`、无 bt）；provider URL 与 mihomo 相同、缓存路径独立；DNS policy 无 `geosite:`。`check.py` 对完整版的 Xboard 与 subconverter 渲染同样检查策略组。`python3 tools/verify.py` 全部通过。
- 依据：stash.wiki 规则集文档（mrs 支持 domain/ipcidr；domain/ipcidr 针对大量数据压缩优化）、FAQ“编写高效配置”（iOS 15+ 内存上限 50 MB）、3.6 发布说明（DNS policy `rule-set:`）。

## 2026-10-30 Stash 改用 mrs 规则集与 3.6 新 DNS 字段；目录改名 xboard/

- Stash 的 domain/ipcidr 规则集从 yaml 改为 mrs（Stash iOS 3.1.1+ 支持，与 mihomo 同一二进制格式）：`rules` 分支 `stash/` 下 21 个集合改发 `.mrs`，只有 classical 的 `local-direct` 仍是 yaml。旧 `stash/*.yaml` 不再发布，仍用旧配置的 Stash 刷新规则集会 404 并沿用本地缓存，刷新订阅后即换到 mrs。
- Stash DNS 对齐 mihomo：新增 `proxy-server-nameserver`（国内 DoH）给节点域名单独解析，不跟随 follow-rule；`nameserver-policy` 里原先逐条展开的 `rules/direct.txt` 28 条与 `geosite:category-game-platforms-download` 合并为一条 `rule-set:direct`（Stash 3.6+ 支持 `rule-set:` 引用，与分流共用同一份规则集，`direct` 集合本就包含游戏下载上游）。`spec.stash_dns_china` 现在只写集合名。
- 因此 Stash 最低要求提高到 iOS 3.6 / macOS 4.3（2026-10-09 发布）；README、底包与模板头注释同步说明。依据：stash.wiki 规则集与 DNS 文档、3.1.1 / 3.4.0 / 3.6.0 发布说明。未做 Stash 实机验证。
- mihomo 配置复核：未发现冗余或已废弃字段（`global-client-fingerprint` 已在 1.19.27 移除，本仓库从未使用；`use-hosts`/`use-system-hosts`/`fake-ip-filter-mode` 为默认值但显式保留便于阅读）。sniffer `override-destination: false` 与官方示例一致，未改。
- `Xboard/` 目录改名 `xboard/`（顶层目录统一小写；`Clash/` 为远程配置路径不动）。OVH 上 Xboard 模板同步脚本的拉取路径同步改为 `xboard/`。`xboard/README.md` 改为描述实际部署方式（后台数据库模板 + 每小时同步脚本），并说明 clash 槽位放 mihomo 模板的原因与 Xboard Clash 渲染器只下发 ss/vmess/trojan 的限制；sing-box/Surge/Surfboard 不做模板。
- 工具：`build.provider_file` 不再按客户端区分后缀；`check_routing.assert_outputs` 改为断言 `rule-set:direct` 与 `proxy-server-nameserver`。`python3 tools/verify.py` 全部通过（mihomo v1.19.33）。

## 2026-10-26 被墙的 Azure 网站改走代理

- 按当日上游核对“被墙域名落入默认直连组”的情况：`geosite:gfw` 中只有 6 条走了直连组。
- `+.azurewebsites.net`（Azure App Service 上的第三方网站）同时在 geosite:gfw 与 geosite:microsoft，原先被 Ⓜ️ 微软（默认直连）截走，国内直连常打不开；
  加入 `rules/proxy.txt`，先于微软组走 🚀 节点选择。微软自有站点（azure.microsoft.com 等）仍走 Ⓜ️ 微软；中国区 `azurewebsites.cn` 不受影响。
- 其余不处理：`www.bing.com`、`global.bing.com`（直连会跳转国内版，属预期）、`www.msn.com`、`www.skype.com`（Skype 已停止服务）、`appsto.re`（苹果短链）、`bx.in.th`。
- 依据：MetaCubeX geosite:gfw（社区数据）；改变了 *.azurewebsites.net 的默认去向（直连 → 代理），无官方文档依据，如需回退删除该行即可。

## 2026-10-26 BT 客户端按进程直连

- 新增集合 `bt`（`rules/bt.txt`，classical，仅 mihomo），排在内网直连之后、遥测/QUIC/广告之前，固定 `DIRECT`（不随 🎯 直连组切换）。
  原因：TUN 模式下 BT 客户端连接的 peer 多为境外裸 IP，不在 cn-ip 内，会落到 🐟 漏网之鱼走代理，消耗节点流量且违反多数机场条款。
  系统代理模式不接管 BT 流量，不受影响；Stash iOS 不支持进程规则，不生成。
- 收录 qBittorrent、Transmission、μTorrent、BitTorrent、BitComet、Deluge（Windows）、Tixati、PicoTorrent、BiglyBT、rtorrent、KTorrent 与几款安卓客户端包名。
  有意不收录 aria2c/Motrix、迅雷、IDM、FDM：它们同时做普通 HTTP 下载，强制直连会影响需要代理的下载。
- 不采用 `geosite:category-public-tracker`：其中含大量 PT/BT 站点网页域名，直连会改变浏览这些网站的去向；进程规则已覆盖客户端自身的 tracker 与 peer 连接。
- 依据：mihomo 规则文档（PROCESS-NAME 按完整进程名匹配，Windows 带 .exe，安卓为包名）。进程名清单属常见安装默认值，未逐一实机核对；不匹配时只是不生效，不会误伤其他流量。
- `find-process-mode: always` 保持不变，注释改为“BT 进程直连需要”；客户端把它设为 off 时 BT 直连失效。
- 工具：`rules/*.txt` 支持 `process:` 条目（仅 classical）；spec 集合支持 `clients: [meta]`；进程规则存在后 mihomo 日志在端口后附加“(进程名, uid)”，
  `check_routing.py` / `check_rules.py` 的日志匹配随之调整。离线回归在 Linux 上把 Python 解释器复制改名为 `qbittorrent` 实测命中 `bt → DIRECT`。

## 2026-10-25 维护流程固定

- 新增 `docs/maintenance.md`：从 Action 的 issue 到推送、确认发布、回复关闭 issue 的固定流程与判断表；根目录 `AGENTS.md` 供 AI 代理自动加载；
  pi 项目命令 `.pi/prompts/weekly-review.md`（`/weekly-review [编号]`）与 `add-rule.md`（`/add-rule <域名>`）。
- `tools/verify.py`：推送前一键校验，自动下载/缓存 mihomo 到 `.cache/`；CI（check.yml）改为直接运行它，本地与 CI 检查项完全一致（CI 因此也会试构建规则集并跑关键域名把关）。
- `tools/after_push.py`：等待本次提交的 Actions 结束，确认 rules 分支是否已发布本提交。
- `tools/weekly_report.py --preview`：以 report 分支基准、用最新数据本地预览报告，不写任何分支。
- spec 新增 `pin`：`geosite:anthropic` 的条目应全部固定在 `rules/ai.txt`；每周报告列出待固定条目（原先需要人工对比 v2fly）。
- issue 状态约定：「每周规则报告」只在有待处理条目时重新打开（原先每周无条件重新打开），处理完回复并关闭。
- `rules.yml` 手动运行新增 `skip_shrink_check`：确认上游属正常大幅删减时跳过骤减保护，避免一直卡住不发布。

## 2026-10-25 每周报告跟进、Statsig 修正与发布把关加强

- 每周报告（issue #5）：上游 `category-ai-!cn` 两周共新增 16 条，均已自动走 🤖 AI（`o33249.ingest.us.sentry.io` 为 OpenAI 的 Sentry，由 telemetry 先行拦截，属预期）。
  其中 v2fly `data/anthropic` 新增的 Claude 家族父域同步到 `rules/ai.txt` 本地固定（ant.dev、anthropic.team、antspace.dev、chatbotclaude.com、claude.new、claude.site、claudeacademy.com、claudepages.dev、claudestudio.com）。
- 官方网络清单：`sso.claude.com`（SSO 登录）与 `anthropic.com` 裸域加入 `ai-essential`。
- Statsig：原则是只拦上报、不拦功能开关，但 featureassets.org / assetsconfigcdn.org / statsigapi.net（mihomo）与 api.statsig.com（Stash）被广告源拦截。
  按 featureassets.org 的 DNS TXT 把初始化主机放进 `ai-essential`，上报主机 prodregistryv2.org / beyondwickedmapping.org 加入 `telemetry`；
  旧版 Claude Code 遥测端点 `statsig.anthropic.com` 显式拦截（mihomo 本已被广告源拦截，Stash 之前走 AI）。
- `tools/build.py` 增加 spec 自检（`--check` 与每日构建都会执行）：`rules/` 下没有同名集合的文件（文件名拼错会被静默忽略）、去向/成员引用不存在的组、QUIC/DNS/watch 引用不存在的集合或来源、同一条目出现在去向不同的两个本地文件。
- `tools/check_upstream.py` 从“广告之后的几个本地文件是否被广告源拦截”扩展为“任一本地条目是否被前面去向不同的集合整体截走”，mihomo 与 Stash 分别按各自来源检查；`build_rules.py` 用同一份下载数据调用它，不通过则不发布。
- 骤减保护同时检查单个上游（AdRules 与 anti-AD 合并为一个集合，其中一个腰斩时集合整体可能仍在阈值内）；上一版不足 50 条的小集合/小上游不做比例判断。
- 每周报告只下载一次；`watch` 集合的每条增删按当日规则算出实际去向，与预期不同的标 ⚠️（替代原先“删除了仍在使用的下载主机需人工核对”）。
- 公共代码收拢：域名匹配器、按顺序路由与批量下载统一在 `build_rules.py`（`DomainMatcher` / `route_table` / `fetch_all`），`legacy_diff.py`、`check_upstream.py`、`weekly_report.py` 共用，不再各自维护上游 URL 与匹配语义。
- CI：mihomo 下载抽成 `.github/actions/setup-mihomo`（找不到发布文件时明确报错）；`actions/checkout`、`actions/setup-python` 升到 v7（Node 24，消除 Node 20 弃用告警）；`rules.yml` 的触发路径补上 `check_rules.py` 依赖的 `check_routing.py` 与 `check_upstream.py`。

## 2026-10-07 旧规则对比与每周报告（重构第 4 步）

一次性对比旧 ACL4SSR 31 个列表（约 9800 条域名规则）与当前规则的默认去向，2834 条有变化：

- 约 2600 条“→ 按 IP”（主要是旧 GFWList 与 `.hk/.jp/.tw` 等整域）：新规则未直接命中，经境外 DNS 后落到 🐟，仍走代理。整类标记已审阅。
- 采纳：运营商一键登录（移动/联通/电信）与网易易盾被广告源拦截 → `rules/local-direct.txt` 放行（`log.cmpassport.com` 仍拦）；
  群晖 DDNS / QuickConnect / TeamViewer → `rules/direct.txt`；B站国际版与港澳台 Akamai CDN → 新增 `rules/bilibili.txt`；
  Statsig 功能开关 `featuregates.org` 被广告源拦截 → `rules/ai-essential.txt`。
- 其余逐条记入 `src/legacy-review.yaml` 并附理由（谷歌 CN 统一走 🔍、UnBan 精简、统计上报被拦、bootcss/staticfile 供应链投毒等）。

`tools/legacy_diff.py` 复现对比；`.github/workflows/weekly.yml` 每周一生成报告（旧规则新差异 + 游戏下载 / AI 上游集合增删），写入 issue 与 `report` 分支。Issues 已开启，规则构建失败也会记到 issue。发布把关的关键域名增至 55 个。

## 2026-10-07 规则集合并与每日发布（重构第 3 步）

- 本地规则从 `Clash/rule/` 的 12 个历史文件改为 `rules/` 下 10 个文件，与合并集合一一同名；格式统一为每行一条。
- 约 50 个 provider 合并为 24 个集合（`src/spec.yaml` 的 `sets`，顺序即分流顺序）。AdRules 与 anti-AD 合并去重为一个 mrs（21 万条，约 2 MB）。
- `tools/build_rules.py` 合并去重（同集合内被 `+.父域` 覆盖的条目删除）并转换 mrs；`.github/workflows/rules.yml` 每日 04:00 及本地规则改动时构建，发布到 `rules` 分支并刷新 fastly jsDelivr 缓存；内容指纹不变则不发布。
- 失败保护：上游下载失败、集合条目骤减 30% 以上、mrs 转换失败或 `tools/check_rules.py`（真实规则集 46 个关键域名）不通过时不发布，记录到“规则集构建失败” issue，成功后自动关闭。
- 顺序核对（`build_rules.py --conflicts`）：`category-entertainment` 收录约 870 个游戏平台域名，游戏集合必须先于流媒体；`category-entertainment@cn` 收录 Apple Music / iTunes，苹果先于 direct。与重构前相比，唯一的去向变化是 `ggpht.cn`（本已被广告源拦截）。
- 规则 CDN 由 testingcf 改为 fastly。实测 jsDelivr 对分支地址的缓存刷新不可靠：fastly 按 Accept-Encoding 分别缓存，purge 后带 gzip 的请求（mihomo）仍拿到旧版；cdn/testingcf 的源站层也继续返回旧内容。规则改动最多约 12 小时后到客户端（用户选择接受，不改为经节点从 GitHub 原地址下载）。
- 规则集本地缓存路径改到 `./ruleset/acl4ssr/`：旧配置同名文件（如 `./ruleset/bilibili.mrs`）在 24 小时间隔内会被新配置直接复用，换配置时出现旧条数。

## 2026-10-07 策略组精简（重构第 2 步）

31 个组（含 8 个地区组）精简为 13 个，统一“表情 + 短名”，按使用频率排序；组名变化后客户端里保存的选择会重置一次。

| 新组 | 合并自 |
|---|---|
| 🚀 节点选择 | 🚀 节点选择、🔯 自选、📲 电报消息 |
| 🤖 AI | 💬 Ai平台 |
| 🎬 流媒体 | 📹 油管视频、🎥 奈飞视频、📺 巴哈姆特、🌍 国外媒体 |
| 📺 B站 | 📺 哔哩哔哩 |
| 🎮 游戏 | 🎮 游戏平台 |
| 🔍 谷歌 | 🌐 谷歌服务、📢 谷歌FCM |
| Ⓜ️ 微软 | Ⓜ️ 微软Bing、Ⓜ️ 微软云盘、Ⓜ️ 微软服务 |
| 🍎 苹果 | 🍎 苹果服务 |
| 🎯 直连 | 🎯 全球直连、🎶 网易音乐 |
| 🛑 广告 | 🛑 广告拦截 |
| 🛰️ DNS | 🛰️ DNS-Proxy |

删除：🎓 说明组、8 个地区组。已知国外（geolocation-!cn）改走 🚀 节点选择，🐟 漏网之鱼只接 MATCH 兜底。下文更早的记录保留当时的组名。

## 2026-10-07 DNS 简化与 Claude / 游戏补充（重构第 1 步）

| 项目 | 最终行为 |
|---|---|
| DNS 模型 | 回到“已知国内 → 国内 DoH，其余 → 经 🛰️ DNS-Proxy 查境外 DoH，内网 → system”。删除 `dns_remote_sets` / `dns_china_sets`：fake-ip 与系统代理下，走代理的连接由节点远端解析，本地 policy 中的境外条目从不被用到 |
| mihomo DIRECT | `direct-nameserver` 国内 + follow-policy（保留内网 system）。policy 中不含任何境外条目，DIRECT 未命中 policy 时一律回到国内 direct-nameserver，直连下载自然拿到国内 CDN |
| Stash | 无 direct-nameserver，DIRECT 也用主 DNS：额外只给游戏下载集合（`category-game-platforms-download` + `game-download-extra`）指定国内 DNS。删除 `src/stash-dns-cn.yaml` 与 `update_stash_dns.py` |
| 国外覆写 | 只替换 DNS：所有国内服务器换成 Cloudflare / Google 的 DoH + DoT，主 DNS 仍经 🛰️ DNS-Proxy；分流规则与策略组不变。只给海外电脑使用 |
| Claude | Sift 进 `claude-essential`（广告源收录了它，之前实际被拦）；auth0 租户、博客、Intercom 进 `claude`；Datadog 补全各区域摄取端点。详见 [claude-routing](claude-routing.md) |
| Steam CM | 新增 `game-proxy-extra`：`steamserver.net`、`cm.steampowered.com` 走 🎮 游戏平台（上游 games@cn 含 steamserver.net，必须提前截走） |
| 游戏下载补漏 | `game-download-extra` 增加 EA（`+.cdn.ea.com`、`download.dm.origin.com`）、GOG（`cdn.gog.com`、`cdn-hw.gog.com`）、创意工坊与蒸汽平台；删除 CM 条目 |
| 测试 | `check_routing.py` 四台假 DNS 记录查询并断言泄露（见文件头 L1–L4）；新增联网的 `check_upstream.py` 核对当日上游 |

已知限制：mihomo 对 UDP 的域名目标固定先在本地解析一次（按主解析器 policy，Claude 等只会发往境外 DNS）；靠 IP 规则判为直连后由 direct-nameserver 重新解析，上游 issue #3244 报告过个别情况下未使用重解析结果，需实机留意。

## 早先已实施的修复（2026-10-04，DNS / 国外覆写 / 遥测 / Steam 行已被上一节取代）

| 项目 | 最终行为 |
|---|---|
| QUIC / QQ 误拦 | 改为指定服务域名正向集合，仅处理 UDP443，并排除国内域名和已有国内 IP。截图 IP `116.131.56.103`、`223.5.5.5`、QQ 域名及未知裸 IP 不会因 NOT cn 被一概拒绝 |
| 内网解析 | private/private-ip 固定 DIRECT；内网后缀/路由器/本地登录名走 system，并补齐 fake-IP 例外。mihomo DIRECT 打开 follow-policy，避免独立直连解析器绕过内网 policy |
| 国内/国外 DNS 顺序 | 本地代理例外和明确境外集合先于 cn；国内游戏、下载、娱乐标签先于境外泛分类。googleapis.cn、OneDrive、browserleaks/acm/cambridge 等交集已覆盖 |
| Stash 兼容性 | 恢复官方支持的中间星号 STUN 模式，补 Nintendo/Xbox/PlayStation 例外。继续以3.4+为门槛，不加入3.6+才支持的独立节点 DNS 字段 |
| Stash 国内标签 DNS | 3个属性标签集合合并为121条字面域名；避免未确认的 `geosite:name@cn` DNS 语法。提供同步/只读差异检查工具，路由 provider 仍每日更新 |
| Claude | 专用域名家族、必要功能例外、可选遥测、自有 IP 分开处理；补 claude.app 和官方 Desktop 端点。详见 [依据与边界](claude-routing.md) |
| 共享验证服务 | Cloudflare/Arkose 精确主机走节点选择，不把通用供应商整体归为 AI；国外覆写中随通用业务直连 |
| UnBan | 去掉广泛 UnBan；仅保留6条功能域名。小米/Adjust/友盟等已知追踪请求继续接受广告检查 |
| 游戏 | steam@cn 扩展为 category-games@cn（37条，包含原19条）；增加国内下载集合（YAML25条/去重24条）；增加境外游戏平台859条，补齐 Battle.net/Ubisoft/GOG 等 |
| Epic 下载 | 删除宽泛关键词，改为限定的完整域名正则，避免同名恶意域名被放行。保留原 Akamai 下载直连取舍，不将其误称为纯国内端点 |
| PlayStation | 当前4条均包含在 Sony115条中，且同策略；删除重复 provider/规则 |
| 媒体 | 删除旧 ProxyMedia 的 AI关键词、共享服务、混杂 IP/URL 规则；改为社区娱乐集合。先保留国内娱乐796条与国内属性100条，避免上海迪士尼等误进境外媒体 |
| Stash ChinaDomain | 删除混有历史私网/TeamViewer IP 的 ACL ChinaDomain；路由兜底和 DNS 同用 Stash 原生 GEOSITE，国外优先，再 cn，再 GEOIP |
| 空组 | 地区组和自动选择明确保留 REJECT；无地区/全过滤不自动补 DIRECT |
| 国外覆写 | 明确遥测拦截、必要功能例外、普通广告检查、AI、其余 DIRECT；国外公共 DNS 同时保留内网 system policy |
| 维护 | 全局、DNS、嗅探参数移入 spec；未定义源规则集报错；生成、行为检查纳入 CI。更新本地 domain 文件后也需 build，因为 Stash DNS 使用展开内容 |
| 遥测补充 | 对照参考页：Datadog 两端点外，补 Sentry 接收端（ingest.sentry.io / us / de）、Statsig 事件上报 events.statsigapi.net、Fathom 统计 cdn.usefathom.com，两端都显式拦截。不拦 Statsig 配置初始化（影响功能开关）、Intercom 客服、Sift 风控（可能影响登录/支付）；不使用 datadog/sentry/sift 关键词 |
| QUIC 扩大 | 从 AI/YouTube/Netflix 扩至全部已识别境外域名集合，加 Anthropic 自有 IP；豁免国内、游戏、下载、通信。cn 与 !cn 交集站点按境外处理，与路由/DNS 一致 |
| 游戏下载 | 新增完整下载集合（mihomo 491 / Stash 492 条）并默认直连、国内 DNS；此前只有国内子集 |
| Steam 下载补漏 | 上游只逐个列 `cacheN-xxx.steamcontent.com`（如缺 cache10-hkg1），漏网主机落入 geosite:steam → 🎮 游戏平台走代理。新增 `game-download-extra.txt`：`+.steamcontent.com`、`+.cm.steampowered.com` 及旧 SteamCN 的 dl.steam.ksyna.com、steampipe.steamcontent.tnkjmec.com，恢复旧 SteamCN 直连并走国内 DNS；商店/社区仍走游戏平台 |

## 非规则配置复核

DNS-Proxy 默认跟随节点选择；mihomo 境外 DNS 显式指定组，节点域名通过独立直连 DNS 解析，避免解析节点本身依赖该节点。Stash 主 DoH 使用 IP，并通过前置 IP 规则选组，符合官方递归规避条件；其绑定影响这些 IP 的其他端口/业务，不等价于 mihomo 的每条 DNS URI `#组`。

解析链分别核对了主解析、代理节点解析与 DIRECT 解析。新增真实 DIRECT 内网连接测试：用不同本地 DNS 模拟 LAN policy 和错误直连回退，只有遵循 policy 才能连接本地服务。测试未修改操作系统 DNS。

保留本机监听、warning 日志、现有 TCP 竞争/延迟统计与 profile 设置。嗅探保持 `override-destination:false`，恢复域名用于匹配，不强行改变目的地址；ECH、无 SNI、非标准流量不保证可恢复域名。DNS 禁用 AAAA 不代表系统所有 IPv6 都被禁用。

Stash GEOSITE 数据并非随应用一起分发；官方说明首次从 GitHub 按需加载。模板没有再添加全量 cn/geolocation-!cn YAML provider，但这不代表没有 geosite 数据下载或内存开销。未做 iOS 峰值内存、耗电或真实游戏联机测量。

测速间隔600秒；Xboard 显式 lazy，INI 的 mihomo 依赖已核对的内核默认 lazy=true。Stash/其他转换器的最终输出应按客户端验证，不能声称所有入口都显式设置 lazy。健康检查仍会在启动时运行。

## 保留的取舍与限制

- AI 默认选择方式保留。HTTP204测速不证明 Claude/ChatGPT/Gemini 支持地区或节点信誉；用户需选支持地区，固定出口可直接选择单节点。没有凭节点名称自动断言真实出口。
- 保留 AdRules 与 anti-AD：初始快照重叠84,237条，但分别有独有规则；没有仅凭重叠删掉其中之一，也没有引入自动合并发布流程。
- Xboard 零节点时所对照的上游会把 regex 清理放在节点循环内，可能留下不可导入的占位项；这是服务端渲染限制。本仓库修正模拟并明确报告，不宣称模板能保证零订阅节点导入成功。
- 必要 API 上的路径级遥测无法仅靠域名规则区分。共享接收端的精确拦截也可能影响其他应用向同端点的遥测。
- Stash 普通 geosite 取官方 community 数据，mihomo cn 含额外上游融合；两个客户端不保证每个边缘域名完全一致。规则/DNS动态数据也不是物理地理位置的绝对判定。
- 内网 system 解析仍依赖操作系统实际 DNS；`.local` 的 mDNS发现、企业 SSO、本地 MCP 和任意自定义网关需实机验证。
- 全球游戏下载 CDN 直连在国内通常可用，但个别节点直连可能较慢；可临时把 🎯 全球直连 切到代理测试，或在 extra-proxy 中覆盖个别域名。

## 验证

真实 mihomo v1.19.32 的配置校验覆盖两个订阅入口、两种国外覆写组合、只有香港节点、全部节点被过滤及 subconverter 零节点，共9种配置。

离线行为测试保留生成的规则顺序和本地列表，以本地 SS/DNS/TCP 接收端验证 QQ/国内/未知 UDP、指定服务 QUIC、Claude 核心/家族/遥测/共享验证码、广告冲突、伪造域名、Epic 正则和其他分类。DNS测试覆盖境外例外、国内游戏/媒体和真实 DIRECT 内网解析链，不访问业务网站，不登录账号。

两客户端84个 provider 定义已逐个核对：本地源读取实际 payload，上游源实际下载；domain/ipcidr 的 MRS 或 YAML 通过真实内核转换解析，classical YAML 检查非空 payload 并在行为测试中加载。Stash DNS121条缓存另与当前上游核对一致。

```bash
python3 tools/build.py --check
python3 tools/check.py /path/to/mihomo
python3 tools/check_routing.py /path/to/mihomo
python3 tools/check_upstream.py   # 联网
git diff --check
```

以上不是 Stash 实机内核校验，不证明所有网站功能、系统 DNS接管、iOS内存或代理地区解锁。Xboard/subconverter 的完整服务器渲染仍由实际部署版本决定，测试对照并模拟了上游关键行为。

改动位于本地工作区，未推送。新的本仓库规则文件需一并发布，远程订阅/规则刷新后才会生效；现有连接和旧 DNS 缓存可在重启内核后重新验证。
