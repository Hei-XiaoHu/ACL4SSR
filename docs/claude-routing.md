# Claude 域名、共享服务与遥测分流

核对日期：2026-10-04。依据 Claude 官方网络/桌面版文档、v2fly/MetaCubeX 数据、ARIN RDAP，以及用户提供的 [Net.Coffee 参考页](https://ip.net.coffee/claude/site.html)。参考页是补充线索，不直接作为“全部必须代理/放行”的依据。

## 最终分类

| 类别 | 范围 | 策略 |
|---|---|---|
| 明确的核心功能端点 | 官方 API、OAuth、安装更新、CDN、桌面预览、用户内容与 MCP 内容 | `claude-essential` → 💬 Ai平台；提供必要的精确主机/专用内容后缀例外 |
| Claude 域名家族 | anthropic.com、claude.ai/com/app/dev、clau.de、MCP/content 父域，以及两个专属第三方 CDN 主机 | `claude` → 💬 Ai平台；位于广告集合之后，不给整个 Claude 家族广告豁免 |
| 明确的可选遥测 | 官方 Datadog 两端点，以及参考页中的 Sentry 接收端、Statsig 事件上报、Fathom 统计 | `claude-telemetry` → 🛑 广告拦截，国外覆写直接 REJECT |
| 共享人机验证 | challenges.cloudflare.com、client-api.arkoselabs.com | `shared-auth` → 🚀 节点选择；国外覆写跟随通用业务 DIRECT |
| 已核实的自有 IP | 160.79.104.0/21、2607:6bc0::/32 | 域名规则之后使用 `claude-ip` → 💬 Ai平台，no-resolve |
| 其他共享服务 | GitHub、npm、Google Storage、通用 JS/font CDN、Auth0/WorkOS/Intercom 等 | 按原有通用/平台分流；不把整个供应商后缀塞入 AI |

Claude、共享验证码和广告规则的顺序为：明确遥测拦截 → 定向 QUIC → 必要功能例外 → 通用广告集合 → Claude 家族/其他 AI → 自有 IP 兜底。

`claude.app` 与动态 `*.livepreview.claude.app` 出现在官方 Desktop 清单，但本次上游 anthropic/category-ai-!cn 的普通 domain 列表没有它们，因此在本地补齐。`platform.claude.com` 的 OAuth 交换、刷新、撤销以及 API、Chrome bridge、Artifacts、MCP 内容都属于已核对的功能范围。

普通域名分流无法识别同一个验证码主机是被哪个网站调用。把 challenges.cloudflare.com 固定到 AI 会让其他网站验证码也使用 AI 出口；本配置改为通用节点。默认 AI 本来就跟随节点选择，二者初始出口一致。若手动为 AI 选了不同出口，且真实登录出现反复挑战，再根据连接日志判断是否需要临时统一出口；不预设“所有共享服务都必须同 AI 出口”。

## 遥测边界

本地规则明确拦截：

```text
http-intake.logs.us5.datadoghq.com
browser-intake-us5-datadoghq.com
```

二者是共享 Datadog 接收端，其他应用向相同端点发送的遥测也会受影响。使用精确域名，不添加 `DOMAIN-KEYWORD,datadog/sentry/sift` 等无归属边界的匹配。

非必要的 Claude 子域名仍会接受 AdRules/anti-AD 或 Stash AWAvenue 检查。必要例外只覆盖明确功能端点与专用内容域，不放行整个 `*.anthropic.com`、`*.claude.ai`。

`api.anthropic.com` 同时承载正常 API 和部分 event_logging。域名/IP 规则看不到同一 HTTPS 主机上的不同路径，无法仅凭此配置做到“允许核心 API、拒绝它的所有遥测路径”。不能为拦截遥测而封禁整个 API。Claude Code 用户可按官方文档使用 `DISABLE_TELEMETRY=1`、`DISABLE_ERROR_REPORTING=1`；更广的 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` 会影响其他非必要功能，应先阅读官方说明。本次未修改任何用户系统环境变量。

## 如何处理 Net.Coffee 页面中的建议

| 页面项目 | 核对结果与处理 |
|---|---|
| anthropic / claude / content / MCP 后缀 | 与官方/社区域名相符，保留明确归属的分流 |
| servd-anthropic-website.b-cdn.net | 精确 Anthropic 租户主机，已在社区源中；不扩大为整个 b-cdn.net |
| anthropic.com.cdn.cloudflare.net | 作为专属别名精确补充；不扩大为所有 cloudflare.net |
| anthropic.auth0.com | 不是整个 Auth0 供应商。当前官方核心 allowlist 未列入；本次 OIDC discovery 返回404，不能据此认定登录必需，也不能据此认定域名彻底停用。不为未经核实的旧认证流程增设核心豁免 |
| anthropic-com.ghost.io | 博客/CMS，不是推理/OAuth 必需端点；不提升为核心例外 |
| sentry.io / statsigapi.net / datadog / sift | 只精确拦截上报端点（`*.ingest[.us/.de].sentry.io`、`events.statsigapi.net`）。Statsig 初始化决定功能开关，Sift 为反欺诈，拦截可能影响登录/支付，留给广告源判断；不使用关键词 |
| intercom.io / intercomcdn.com | 通用客服服务；不赋予整个供应商 Claude 专属身份 |
| cdn.usefathom.com | 访问统计，显式拦截（Stash 的 AWAvenue 未收录） |
| 两个 IP 段 / AS399358 | ARIN RDAP 注册主体均为 Anthropic, PBC；添加两个自有前缀。ASN 规则未额外引入，避免依赖客户端 ASN 数据库与重复覆盖 |
| “所有 NTP 必须进入 AI，否则返回的时区不一致” | 不采纳。NTP 用于同步时间，不返回中国/美国等本地时区；本地时区由操作系统设置。不能靠 NTP 分流保证“没有时区泄漏” |
| “每个监控请求必须代理，才能避免风控” | 未发现官方依据支持这种无条件结论；明确的可选遥测可拦截，不能为了这个说法放行所有统计供应商 |

自有前缀覆盖不代表 Claude 所有服务都位于这两个网段，也不代表每个裸 IP 的应用请求用途都能确定。不会为云上托管的 Claude 分配整片 Cloudflare/CDN 公用网段。

## 验证与限制

`tools/check_routing.py` 使用真实 mihomo 和本地 DNS/SS 接收端验证匹配行为，不登录账号，不把测试流量发到业务站点。覆盖：

- 核心 API、OAuth、下载、两种动态预览、CDN、Chrome bridge、Artifacts、MCP 内容。
- Claude 域名家族的非核心主机、claude.app 新域名和精确第三方 CDN。
- 两个可选遥测端点拦截；用人工 telemetry 子域夹具证明 Claude/其他 AI 家族不会绕过广告检查。这些人工主机不代表真实遥测端点。
- 共享验证码进入通用节点；伪造 `claude.ai.evil.example`、`notanthropic.com` 与其他 b-cdn 租户不进入 Claude 专用规则。
- 自有 IPv4/IPv6 前缀的裸 IP 兜底，且不为规则额外解析域名。
- Claude DNS 进入境外 policy；QQ 国内域名进入国内 policy。

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
