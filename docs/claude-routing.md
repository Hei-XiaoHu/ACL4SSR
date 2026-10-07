# Claude 域名、共享服务与遥测分流

核对日期：2026-10-04，2026-10-07 按用户决策更新（Sift / Intercom / auth0 / 博客改走 AI，Datadog 补全各区域）。依据 Claude 官方网络/桌面版文档、v2fly/MetaCubeX 数据、ARIN RDAP，以及用户提供的 [Net.Coffee 参考页](https://ip.net.coffee/claude/site.html)。参考页是补充线索，不直接作为“全部必须代理/放行”的依据。

## 最终分类

| 类别 | 范围 | 策略 |
|---|---|---|
| 明确的核心功能端点 | 官方 API、OAuth、安装更新、CDN、桌面预览、用户内容与 MCP 内容；Sift 反欺诈 | `ai-essential`（rules/ai-essential.txt） → 🤖 AI；排在广告集合之前。Sift 被 AdRules / anti-AD 收录，只有放在这里才不会被拦 |
| Claude 域名家族 | anthropic.com、claude.ai/com/app/dev、clau.de、MCP/content 父域、两个专属第三方 CDN 主机、anthropic.auth0.com、anthropic-com.ghost.io、Intercom | `ai`（rules/ai.txt） → 🤖 AI；位于广告集合之后，不给整个 Claude 家族广告豁免（Intercom 分析上报仍被广告源拦截） |
| 明确的可选遥测 | Datadog 各区域 RUM / 日志摄取端点，Sentry 摄取端（含 us/de），Statsig 事件上报，Fathom 统计 | `telemetry` → 🛑 广告 |
| 共享人机验证 | challenges.cloudflare.com、client-api.arkoselabs.com | `auth` → 🚀 节点选择（低延迟节点，验证更快） |
| 已核实的自有 IP | 160.79.104.0/21、2607:6bc0::/32 | 域名规则之后使用 `ai-ip` → 🤖 AI，no-resolve |
| 其他共享服务 | GitHub、npm、Google Storage、通用 JS/font CDN、Auth0 其他租户、WorkOS 等 | 按原有通用/平台分流；不把整个供应商后缀塞入 AI |

Claude、共享验证码和广告规则的顺序为：明确遥测拦截 → 定向 QUIC → 必要功能例外 → 通用广告集合 → Claude 家族/其他 AI → 自有 IP 兜底。

`claude.app` 与动态 `*.livepreview.claude.app` 出现在官方 Desktop 清单，但本次上游 anthropic/category-ai-!cn 的普通 domain 列表没有它们，因此在本地补齐。`platform.claude.com` 的 OAuth 交换、刷新、撤销以及 API、Chrome bridge、Artifacts、MCP 内容都属于已核对的功能范围。

普通域名分流无法识别同一个验证码主机是被哪个网站调用。把 challenges.cloudflare.com 固定到 AI 会让其他网站验证码也使用 AI 出口；本配置改为通用节点。默认 AI 本来就跟随节点选择，二者初始出口一致。若手动为 AI 选了不同出口，且真实登录出现反复挑战，再根据连接日志判断是否需要临时统一出口；不预设“所有共享服务都必须同 AI 出口”。

## 遥测边界

本地规则明确拦截（完整列表见 `rules/telemetry.txt`）：

```text
browser-intake-{,us3-,us5-,ap1-,ap2-}datadoghq.com / browser-intake-datadoghq.eu / browser-intake-ddog-gov.com
http-intake.logs.{,us3.,us5.,ap1.,ap2.}datadoghq.com / http-intake.logs.datadoghq.eu / http-intake.logs.ddog-gov.com
+.ingest.sentry.io / +.ingest.us.sentry.io / +.ingest.de.sentry.io
events.statsigapi.net / cdn.usefathom.com
```

Datadog 浏览器端点是连字符域名（不是 datadoghq.com 的子域），按 Datadog 官方站点列表逐个列出，覆盖 Anthropic 将来切换区域的情况。这些都是共享接收端，其他应用向相同端点发送的遥测也会被拦（隐私上可接受）。不添加 `DOMAIN-KEYWORD,datadog/sentry/sift`：关键词无归属边界，也无法放进 domain/mrs 集合。

非必要的 Claude 子域名仍会接受 AdRules/anti-AD 或 Stash AWAvenue 检查。必要例外只覆盖明确功能端点与专用内容域，不放行整个 `*.anthropic.com`、`*.claude.ai`。

`api.anthropic.com` 同时承载正常 API 和部分 event_logging。域名/IP 规则看不到同一 HTTPS 主机上的不同路径，无法仅凭此配置做到“允许核心 API、拒绝它的所有遥测路径”。不能为拦截遥测而封禁整个 API。Claude Code 用户可按官方文档使用 `DISABLE_TELEMETRY=1`、`DISABLE_ERROR_REPORTING=1`；更广的 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` 会影响其他非必要功能，应先阅读官方说明。本次未修改任何用户系统环境变量。

## 如何处理 Net.Coffee 页面中的建议

| 页面项目 | 核对结果与处理 |
|---|---|
| anthropic / claude / content / MCP 后缀 | 与官方/社区域名相符，保留明确归属的分流 |
| servd-anthropic-website.b-cdn.net | 精确 Anthropic 租户主机，已在社区源中；不扩大为整个 b-cdn.net |
| anthropic.com.cdn.cloudflare.net | 作为专属别名精确补充；不扩大为所有 cloudflare.net |
| anthropic.auth0.com | Anthropic 专属 Auth0 租户（不是整个 Auth0）。登录会记录 IP，走 AI 保持出口一致；不在广告源中，放在 `ai`（rules/ai.txt） 即可 |
| anthropic-com.ghost.io | 博客/CMS，按用户决定同走 AI；不是核心端点，不放进 essential |
| sentry.io / statsigapi.net / datadog | 只精确拦截上报端点；Statsig 初始化决定功能开关，不拦；不使用关键词 |
| sift | 反欺诈，把设备指纹与 IP 交给 Anthropic 风控。广告源（AdRules / anti-AD）收录了 sift.com / siftscience.com，之前实际被拦。现放入 `ai-essential`（rules/ai-essential.txt）（排在广告前）走 AI，保证与 Claude 同出口；不使用 `sift` 关键词 |
| intercom.io / intercomcdn.com | 客服会话绑定账户与 IP，走 AI。全局生效：其他网站的 Intercom 也会走 AI；Intercom 分析上报仍被广告源拦截 |
| cdn.usefathom.com | 访问统计，显式拦截（Stash 的 AWAvenue 未收录） |
| 两个 IP 段 / AS399358 | ARIN RDAP 注册主体均为 Anthropic, PBC；添加两个自有前缀。ASN 规则未额外引入，避免依赖客户端 ASN 数据库与重复覆盖 |
| “所有 NTP 必须进入 AI，否则返回的时区不一致” | 不采纳。NTP 用于同步时间，不返回中国/美国等本地时区；本地时区由操作系统设置。不能靠 NTP 分流保证“没有时区泄漏” |
| “每个监控请求必须代理，才能避免风控” | 未发现官方依据支持这种无条件结论；明确的可选遥测可拦截，不能为了这个说法放行所有统计供应商 |

自有前缀覆盖不代表 Claude 所有服务都位于这两个网段，也不代表每个裸 IP 的应用请求用途都能确定。不会为云上托管的 Claude 分配整片 Cloudflare/CDN 公用网段。

## 验证与限制

`tools/check_routing.py` 使用真实 mihomo 和本地 DNS/SS 接收端验证匹配行为，不登录账号，不把测试流量发到业务站点。覆盖：

- 核心 API、OAuth、下载、两种动态预览、CDN、Chrome bridge、Artifacts、MCP 内容。
- Claude 域名家族的非核心主机、claude.app 新域名和精确第三方 CDN。
- Datadog 各区域、Sentry 各区域、Statsig 事件、Fathom 遥测拦截；Sift 即使在广告源中仍进入 AI；Intercom 分析上报仍被拦截；用人工 telemetry 子域夹具证明 Claude/其他 AI 家族不会绕过广告检查。这些人工主机不代表真实遥测端点。
- 共享验证码进入通用节点；伪造 `claude.ai.evil.example`、`notanthropic.com` 与其他 b-cdn 租户不进入 Claude 专用规则。
- 自有 IPv4/IPv6 前缀的裸 IP 兜底，且不为规则额外解析域名。
- DNS 泄露：走代理的 Claude 连接（TCP）本地零查询，由节点远端解析；主解析器对 Claude 域名只用境外 DNS；国内 DNS 全程只收到国内域名。
- `tools/check_upstream.py` 每次用当日上游核对：Claude/AI 域名不在 geosite:cn，广告之后的 AI 域名未被广告源整域拦截。

这证明规则匹配与优先级，不等于所有网站功能已完成端到端测试。未声称做了 Claude mobile 抓包；企业 SSO 的第三方 IdP、本地 MCP 任意服务器、用户自定义 API 网关仍需按真实目的地址判断。Bedrock/Vertex/Azure 上的 Claude 不因模型名相同就自动归属 Anthropic 的自有域名或网段。

## 依据

- [Claude Code network configuration](https://code.claude.com/docs/en/network-config)
- [Claude Desktop network requirements](https://code.claude.com/docs/en/desktop)
- [Claude Code data usage](https://code.claude.com/docs/en/data-usage)
- [Claude in Chrome admin controls](https://support.claude.com/en/articles/13065128-claude-in-chrome-admin-controls)
- [v2fly anthropic](https://github.com/v2fly/domain-list-community/blob/master/data/anthropic)
- [ARIN IPv4](https://rdap.arin.net/registry/ip/160.79.104.0)、[IPv6](https://rdap.arin.net/registry/ip/2607:6bc0::)、[ASN](https://rdap.arin.net/registry/autnum/399358)
- [Cloudflare Turnstile CSP](https://developers.cloudflare.com/turnstile/reference/content-security-policy/)
- [NTPv4 / RFC5905](https://www.rfc-editor.org/rfc/rfc5905)
