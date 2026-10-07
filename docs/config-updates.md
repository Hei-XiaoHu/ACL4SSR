# 配置修复与最终复核

对应 [初始审计](mihomo-stash-audit.md) 的修改前快照。配置已按 Claude → 其他分类 → DNS/非规则配置 → 整体校验的顺序复核。

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
