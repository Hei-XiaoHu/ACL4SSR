# mihomo / Stash 配置逐项审查

本报告审查 `src/spec.yaml`、七份生成输出、三个补充规则文件、生成器、校验器和 CI。配置输出已完整读取；重复生成的策略组成员逐一核对后，以源文件行号汇总，避免把相同结论重复七次。远程规则列表进行了实际下载、格式检查和关键域名匹配检查；并未人工逐条审阅远程列表的几十万条规则。

这是**修改前的审计快照**，以下行号、问题和条数对应初始版本；上游列表会更新。已实施的修复及当前验证结果见 [修复结果](config-updates.md)，Claude 分类依据见 [Claude 分流](claude-routing.md)。

**验证结果**

- `python3 tools/build.py --check`：通过，七份输出与源文件一致。
- mihomo v1.19.32：`xboard-meta`、`subconverter-meta` 及二者的国外覆写组合，四项 `mihomo -t` 均通过。
- mihomo 的 37 个 provider、Stash 的 33 个 provider 的 URL 均可下载。
- mihomo 的 31 份 MRS 均通过真实内核的 `convert-ruleset <behavior> mrs` 解析；MRS 外层是 Zstandard 压缩，不能直接在下载字节头检查 `MRS` 魔数。
- YAML provider 检查了 `payload`；text provider 检查了实际文本内容。
- 内核校验只证明配置能够解析，不能证明真实网站可用、DNS 无污染、分流符合意图或 iOS 内存够用。
- 未在真实 Stash、Clash Party、CMFA 上导入和抓包；Stash 结论以官方文档和配置静态分析为依据。
- Xboard/subconverter 校验脚本使用 Python 模拟。额外对照了上游 PHP/C++ 实现，发现模拟没有覆盖的行为差异。

**优先处理的问题**

| 编号 | 优先级 | 位置 | 结论与建议 |
|---|---|---|---|
| F1 | 高 | `src/spec.yaml:129` | QUIC 条件是 UDP + 443 + 不命中 cn，并不检查最终是否代理。纯 IP 的国内连接在 mihomo 的 domain provider 中不命中 cn，会先被拒绝，来不及进入末尾 cn-ip；未入 cn 的直连服务也一样。命中 cn、但被 extra-proxy 指向代理的域名又会被放过。必须重新定义拦截范围。 |
| F2 | 高 | `tools/build.py:230` | `direct-nameserver` 使用国内公共 DNS，且 `direct-nameserver-follow-policy: false`。即使主 DNS 为 private 选择 system，DIRECT 出站仍使用独立解析器重新解析域名，跳过 private policy。局域网/企业内网名可能失效。建议打开 follow-policy 并保留 private 的 system policy，验证主机名实际解析。 |
| F3 | 高 | `tools/build.py:254` | Stash 生成器删除全部含 `*` 的 fake-IP 例外，理由与当前官方示例矛盾。官方明确列出 `+.stun.*.*` 和 `+.stun.*.*.*`。建议恢复已被官方示例支持的 STUN 例外；time/ntp 模式按目标版本另行验证，不能一概删除。 |
| F4 | 中至高 | `tools/build.py:258` | Stash 缺少 LAN/private 的 system DNS policy。fake-IP-filter 只改变返回真/假 IP，不选择内网 DNS；把 `.lan` 等排除后仍可能发给外部 DoH。建议为明确的内网后缀配置 system，检查企业 DNS、NAS、路由器和 Tailscale 场景。 |
| F5 | 中 | `tools/build.py:232`、`src/spec.yaml:163` | mihomo 路由先 geolocation-!cn 后 cn，但 DNS 只有 private/cn policy。上游两个域名集有 148 条完全相同的规则；browserleaks.com、acm.org、cambridge.org 确认同时命中。业务走代理，解析却可能发给国内 DNS。建议至少为 extra-proxy、extra-ai/ai 和明确的国外集合定义 DNS 优先级。注意 fake-IP 模式不一定在每次客户端查询时立即向上游解析，问题发生在实际需要解析时。 |
| F6 | 中 | `tools/build.py:164`、两份 ini 第 30–37 行 | 空地区组在 subconverter 上游实现中自动补 DIRECT；Xboard 生成器则显式留 REJECT。选中没有节点的地区组，两个入口行为不一致，并可能意外直连。建议统一明确的空组行为，增加缺地区节点场景校验。 |
| F7 | 中 | `src/spec.yaml:124` | UnBan 排在广告拦截前，31 条白名单中包含 tracking.miui.com、app.adjust.com、errlog.umeng.com、msg.umeng.com、msg.umengcloud.com、googletraveladservices.com；这些确实被 mihomo 两份广告集收录，却被提前放行。建议改为本地小白名单，按“功能必需”逐条保留。 |
| F8 | 中 | `src/spec.yaml:47` | AI 默认跟随全局低延迟自动选择，未约束服务支持地区，也可能在地区/出口间切换。测速成功不代表 ChatGPT/Gemini/Claude 可用。建议明确 AI 可用地区与是否需要固定出口；这是使用偏好，不能仅凭静态配置判定节点可用。 |
| F9 | 中 | `tools/check.py:158` | 现有测试所有地区都有样本，没覆盖缺地区、全部节点被过滤、零可用节点。Xboard 在零节点时，其正则移除逻辑本身也与 Python 模拟不同。增加真实渲染/边界验证，避免通过模拟得出过强结论。 |
| F10 | 低 | `src/spec.yaml:98`、`:150` | 上游 playstation 4 条规则全部包含在 sony 115 条中，二者同一策略。后者目前无额外作用。可删除 playstation provider 和对应规则，减少下载与维护。每日更新的上游可能改变，应在升级时复核。 |
| F11 | 低 | `src/spec.yaml:78`、`:80` | AdRules 197,054 条、anti-AD 100,064 条，完全相同的规则有 84,237 条。重复存在，但两者并不完全互相包含。可比较单列表效果或预合并去重；不能未经误杀/覆盖评估直接删掉其中一个。 |
| F12 | 低 | `tools/build.py:169`、`README.md:36` | Xboard 明确输出 lazy:true，INI 输出没有显式 lazy 参数。subconverter 支持独立 Lazy 配置，但本仓库的 INI 文本没有表达它。应核实目标转换器/内核默认值；“所有入口均显式保证 lazy”超出了当前证据。 |
| F13 | 中 | `src/spec.yaml:173`、`:193` | 国外覆写把局域网规则设为 DIRECT，却没有保留 private -> system DNS policy；原来的直连解析器和 policy 被整段替换。海外局域网/企业 DNS 名仍可能失效。建议国外 DNS 段也保留 LAN/system 例外。 |

**需要保留的正确设计**

AI 在微软/Bing 之前、GitHub 在微软之前、extra-proxy 在 OneDrive 之前，顺序都正确。mihomo 采用 MRS、Stash 采用更小的广告集合，方向合理。IP 规则集使用 no-resolve、cn-ip/GEOIP 放在尾部、MATCH 最后，也有明确性能价值。修改时应保留这些性质。

**全局参数与嗅探逐项检查**

这些参数的源头在 `tools/build.py`，并非 `src/spec.yaml`。README 的“只改 spec”对 DNS、嗅探和全局参数并不成立；建议把它们也迁入 spec，或准确说明需要修改生成器。

| 源位置 | 字段/值 | 检查结论 |
|---|---|---|
| build.py:181 | port:7890 | 常见 HTTP 代理端口，可保留；被占用时由客户端管理。 |
| build.py:182 | socks-port:7891 | 常见 SOCKS 端口，可保留；是否需要 mixed-port 取决于应用，不能认定必须改。 |
| build.py:183 | allow-lan:false | 合理；不向局域网开放代理。 |
| build.py:184 | mode:rule | 合理；规则模式是整套分流的前提。 |
| build.py:185 | log-level:warning | 日常合理；排查时临时 info/debug，不应长期输出大量日志。 |
| build.py:186 | find-process-mode:off | 当前无进程规则，合理；将来增加进程规则需同时调整。 |
| build.py:187 | tcp-concurrent:true | 可保留；连接竞争有收益，也会增加瞬时拨号，不能无测量宣称必定省电。 |
| build.py:188 | unified-delay:true | 可保留；主要影响延迟统计，不能代替业务可用性检测。 |
| build.py:189 | external-controller:127.0.0.1:9090 | 监听本机合理；端口和认证由客户端实际接管情况决定。 |
| build.py:190 | profile.store-selected:true | 合理；保存手动选择。 |
| build.py:190 | profile.store-fake-ip:true | 合理；持久化假 IP 映射。更新策略后必要时清理旧缓存。 |
| build.py:197 | sniffer.enable:true | 合理；有助于 IP 连接按域名分流。 |
| build.py:198 | force-dns-mapping:true | 可保留；增加域名恢复能力。 |
| build.py:199 | parse-pure-ip:true | 可保留；增加嗅探成本，需按手机真实耗电评估。 |
| build.py:200 | override-destination:false | 合理；利用 SniffHost 匹配规则，不强行替换目标地址。 |
| build.py:202 | HTTP 80 / 8080–8880 | 可保留；范围较宽，需要性能时可按实际使用收窄。 |
| build.py:203 | TLS 443 / 8443 | 合理；嗅探无法保证处理 ECH、无 SNI 或非 TLS 流量。 |
| build.py:204 | QUIC 443 / 8443 | 能帮助恢复域名，但拒绝规则只处理 UDP443；UDP8443 仍可能代理。若目标是“全部代理 QUIC 禁止”，声明与实现不一致。 |
| build.py:206 | skip +.push.apple.com | 合理，避免影响推送；嗅探排除不等于分流或 fake-IP 例外。 |
| build.py:206 | skip Mijia Cloud | 兼容性条目可保留；不是普通 DNS 域名，不应扩展成泛化白名单。 |
| build.py:239 | Stash mode:rule | 合理。 |
| build.py:240 | Stash log-level:warning | 合理。 |
| build.py:241 | Stash 顶层 ipv6:false | 意图明确；具体处理还受 iOS Network Extension 和客户端开关影响。 |
| build.py:242 | Stash profile 两项 | 属 Clash 风格兼容字段；未用真实 Stash 验证其持久化效果，不应只凭 YAML 能解析就认定生效。 |

**DNS 每个字段检查**

| 源位置 | 字段 | 检查结论 |
|---|---|---|
| build.py:215 / :249 | enable:true | 保留；Stash 是否接受所有兼容字段需实机确认。 |
| build.py:216 | listen:127.0.0.1:1053 | 安全且合理；设置监听不代表系统 DNS 自动接入，需要客户端/TUN DNS 接管。 |
| build.py:217 / :250 | ipv6:false | 减少 AAAA 解析；不能据此宣称系统所有 IPv6 流量已禁用。mihomo 顶层未显式关闭 IPv6。 |
| build.py:218 | prefer-h3:false | 合理，避免 DNS 本身依赖 QUIC。 |
| build.py:219 | respect-rules:true | 合理；国外 DNS 使用显式 #组，其优先级高于自动跟规则。国内 DoH 可按路由处理。 |
| build.py:220 | use-hosts:true | 合理。 |
| build.py:221 | use-system-hosts:true | 合理；取决于运行平台是否可访问系统 hosts。 |
| build.py:222 | cache-algorithm:arc | 当前内核支持，可保留；没有测量证据要求更换。 |
| build.py:223 / :251 | enhanced-mode:fake-ip | mihomo 有效；Stash 具体兼容字段以客户端导入结果为准。 |
| build.py:224 / :252 | fake-ip-range:198.18.0.1/16 | mihomo 常规配置；留意局域网是否实际使用此地址段。 |
| build.py:225 | blacklist | 与当前 fake-ip-filter 列表一致。 |
| build.py:226 / :254 | fake-ip-filter | 见下一表；Stash 过滤星号存在明确错误。 |
| build.py:227 / :256 | default-nameserver | 223.5.5.5 / 119.29.29.29 是明文引导解析，不能声称所有 DNS 都加密。用途主要是解析 DNS 服务域名。 |
| build.py:228 | nameserver#DNS-Proxy | 1.1.1.1 / 8.8.8.8 的 DoH 用指定组，设计正确；选 DIRECT/REJECT 的行为也需在组说明中明确。 |
| build.py:229 | proxy-server-nameserver | 为节点域名提供独立直连 DNS，避免代理解析循环；合理。 |
| build.py:230 | direct-nameserver | 独立直连解析是有意设计；必须结合 private/system policy 修复 F2。 |
| build.py:231 | direct-nameserver-follow-policy:false | 应优先考虑改 true，验证企业内网和本地域名。 |
| build.py:232 | rule-set:private -> system | 正确，但当前被独立 DIRECT 解析器绕过。 |
| build.py:232 | rule-set:cn -> china | 国内解析方向合理；与国外优先路由存在 F5。 |
| build.py:255 | Stash follow-rule:true | 官方支持；会让 DNS 网络请求跟规则走。这里主 DoH 服务器使用 IP，符合官方列出的递归规避条件之一，不能直接断言当前必然发生循环。 |
| build.py:257 | Stash nameserver | 主 DNS 使用 IP 地址的 DoH，合理；两条 IP 路由也会影响这些 IP 的其他流量，不只 DNS。 |
| build.py:258 | Stash geosite:cn policy | iOS3.4.0+ 支持；路由 cn 用 ACL4SSR ChinaDomain，DNS cn 用内置 geosite，两者集合不同，应明确差异。 |
| spec.yaml:214 | dns_remote | 可保留两个；冗余查询也有功耗成本，不建议无依据继续增加。 |
| spec.yaml:215 | dns_china | 可保留；doh.pub 引导域名需要 default-nameserver。 |
| spec.yaml:216 | dns_bootstrap | 可保留；如升级 Stash 到3.6+可评估加密 bootstrap，旧版本不能直接套用。 |

Stash 当前官方文档把 `proxy-server-nameserver` 标为 iOS/tvOS3.6+、macOS4.3+；不能为了“与 mihomo 相同”直接向面向3.4.0的模板增加这个字段。若决定提升最低版本，可以增加独立节点解析链路。官方文档同时已出现 inline provider，可用于很小的自定义列表，但也有版本门槛。

**fake-IP 例外逐条检查**

| spec 行 | 条目 | 结论 |
|---|---|---|
| 197 | +.lan | 保留；还必须使用内网/system DNS。 |
| 198 | +.local | 保留；mDNS 服务发现不等于普通 DNS，实机验证。 |
| 199 | +.localhost | 保留。 |
| 200 | +.home.arpa | 保留；补内网 DNS policy。 |
| 201 | +.internal | 保留；补企业 DNS policy。 |
| 202 | +.msftconnecttest.com | 保留；连通性检查例外。 |
| 203 | +.msftncsi.com | 保留；连通性检查例外。 |
| 204 | time.*.com | mihomo 保留；Stash 被生成器删除，按版本验证恢复。 |
| 205 | ntp.*.com | 同上。 |
| 206 | +.ntp.org | 保留。 |
| 207 | +.stun.*.* | mihomo 保留；Stash 官方样例支持，建议恢复。 |
| 208 | +.stun.*.*.* | 同上；更深层 STUN 例外可按实际需求补充。 |
| 209 | localhost.ptlogin2.qq.com | 保留；本地登录接口例外。 |
| 210 | localhost.sec.qq.com | 保留。 |
| 211 | localhost.work.weixin.qq.com | 保留。 |

private provider 覆盖 `.localdomain`、routerlogin.com、tplogin.cn、miwifi.com、`.ts.net` 等更多局域网名称，目前 fake-IP 例外只是子集。mihomo 可评估 rule-set 类型的 fake-IP-filter，Stash 则按明确后缀/域名补齐；不能假设两个客户端支持同样的过滤语法。

**策略组逐行检查**

| spec 行 | 组 | 结论 |
|---|---|---|
| 37 | proxy_first 成员列表 | 无循环引用；DIRECT/REJECT 是人工备用选项，符合可手动切换的设计。 |
| 38 | direct_first 成员列表 | 无循环引用；命名“全球直连”不是强制 DIRECT，因为用户可选择代理。 |
| 41 | 提示组 | 不被规则引用，仅作说明；可保留。Xboard /^$/ 正确阻止追加节点，零节点时真实实现另有边界。 |
| 42 | 节点选择 | 初始指向自动选择，合理；空自动组和不支持的节点协议需验证。 |
| 43 | DNS-Proxy | 初始跟随节点选择，合理；人工切 DIRECT 会导致国内网络访问境外 DoH 失败，REJECT 会阻断解析。 |
| 44 | 自选 | 初始仍是自动选择，是手工入口；与节点选择功能近似，但不能无视使用习惯删掉。 |
| 45 | 自动选择 | 600秒和50ms容差合理；只有连通性/延迟，不验证地区和服务解锁。零可用节点未覆盖。 |
| 46 | 电报消息 | 默认代理，合理。 |
| 47 | AI | 需要 F8 的地区/固定出口决策。 |
| 48 | 油管视频 | 默认代理，合理。 |
| 49 | 奈飞视频 | 默认代理合理；测速不检查 Netflix 解锁。 |
| 50 | 巴哈姆特 | 默认代理；用户一般需手选台湾节点，不能由全局最低延迟保证解锁。 |
| 51 | 哔哩哔哩 | 默认直连合理；港澳台内容需要手选对应节点。 |
| 52 | 国外媒体 | 默认代理合理；ProxyMedia 内含 AI 与宽泛关键词，见规则表。 |
| 53 | 谷歌FCM | 默认代理合理；是否维持省电长连接需手机验证。 |
| 54 | Bing | 默认直连合理；Copilot 先由 AI 组截走。 |
| 55 | OneDrive | 默认直连是有意取舍；网页版由 extra-proxy 提前截走。 |
| 56 | 微软服务 | 默认直连合理；GitHub 提前截走正确。 |
| 57 | 苹果服务 | 默认直连合理；QUIC 在它之前可能抢先拒绝，不应误认为必定直连可用。 |
| 58 | 游戏平台 | 默认代理适合登录/商店，未必适合大文件下载；当前 Steam国内分流和Epic下载例外已部分优化。 |
| 59 | 网易音乐 | 默认直连合理。 |
| 60 | 全球直连 | 默认 DIRECT 合理；private 也指向这个可切换组，误选代理会让内网流量代理。可考虑 private 固定 DIRECT。 |
| 61 | 广告拦截 | REJECT/DIRECT 方便临时排查误杀；能切 DIRECT 意味拦截可人为关闭。 |
| 62 | 漏网之鱼 | 默认代理合理；和节点选择作用可独立切换。 |
| 63 | 地区组展开 | Xboard/INI 空组行为不同，见 F6。 |
| 26 | 香港 regex | 当前样本通过；“港”较宽，也会匹配中转名称，不保证真实出口。 |
| 27 | 台湾 regex | 当前样本通过；可按实际节点名加入“臺”；不能仅凭节点名判定出口。 |
| 28 | 新加坡 regex | 当前样本通过；“坡”是宽匹配。 |
| 29 | 日本 regex | 当前样本通过；可按实际节点名补“日”或城市别称，先避免误匹配。 |
| 30 | 美国 regex | 当前样本通过；“美”很宽，可能匹配南美/美化等字样；150ms容差偏稳定，可保留。 |
| 31 | 韩国 regex | 当前样本通过；Korea 也会匹配 North Korea，不是地理真实性验证。 |
| 32 | 德国 regex | 当前样本通过；DE 使用字母边界正确避免 Sweden。 |
| 33 | 法国 regex | 当前样本通过；可按实际节点名补巴黎以外城市。 |
| 22 | node_exclude | 当前信息节点排除正确；“流量/倍率”等词也可能出现在正常节点名称中，应检查真实订阅样本。 |
| 18 | test_url | Cloudflare204适合基本测试；能访问此 URL 不代表 AI/媒体服务可用。 |
| 19 | test_interval | 600秒合理；没有移动端测量结果可证明“最优”。 |

**每个 provider 检查**

所有 provider 的 `type:http`、`interval:86400`、独立 `path` 和 URL 展开均检查过，无同一客户端内部路径冲突。mihomo 与 Stash 使用不同扩展名缓存 domain/ipcidr 列表；共享的 classical 缓存内容相同。格式以实际内容为准，`.txt` 文件中可以合法使用 YAML `payload`。

| spec 行 | provider | 本次上游规模/结论 |
|---|---|---|
| 71 | extra-direct | 1条 classical YAML；有效，但关键词规则较宽，见补充表。 |
| 72 | extra-ai | 5条 classical YAML；有效。 |
| 73 | extra-proxy | 3条 classical YAML；有效。 |
| 74 | private | 130条；mihomo MRS / Stash domain YAML 有效。 |
| 75 | private-ip | 18条；ipcidr有效。 |
| 76 | unban | 31条 classical text；F7。 |
| 78 | adrules | 197,054条；MRS有效。 |
| 80 | anti-ad | 100,064条；MRS有效；F11。 |
| 82 | awavenue | 961条 domain YAML；规模小，适合移动端；“约900”是近似注释。 |
| 83 | ai | 188条；Copilot已收录，优先级正确。 |
| 84 | googlefcm | 12条；有效。 |
| 85 | google-cn | 112条；有效，与 extra-proxy 的 googleapis.cn 不存在当前观察到的覆盖冲突。 |
| 86 | steam-cn | 19条；有效。 |
| 87 | github | 64条；有效。 |
| 88 | bing | 40条；有效。 |
| 89 | onedrive | 16条；有效。 |
| 90 | microsoft | YAML748条，MRS导出746条；索引压缩/冗余合并导致数量可不同，不能仅据条数认定丢规则。 |
| 91 | apple | YAML1792条，MRS导出1789条；同上。 |
| 92 | telegram | 21条；有效。 |
| 93 | telegram-ip | 12条；有效。 |
| 94 | netease | 54条；有效。 |
| 95 | epicgames | 30条；有效。 |
| 96 | ea | 165条；有效。 |
| 97 | sony | 115条；包含当前 playstation全部规则。 |
| 98 | playstation | 4条；F10，可去重。 |
| 99 | steam | 60条；有效。 |
| 100 | nintendo | 124条；有效。 |
| 101 | youtube | 178条；有效。 |
| 102 | netflix | 24条；有效。 |
| 103 | netflix-ip | 122条；有效，IP可能变化，定期更新合理。 |
| 104 | bahamut | 5条；有效。 |
| 105 | bilibili | 53条；有效。 |
| 106 | proxymedia | 372条 classical text；含域名、IP和AI关键词，存在重复/宽匹配，见下一表。 |
| 107 | gfw | 4374条；有效；不能等价于完整国外站点集合。 |
| 109 | cn (mihomo) | 111,224条；包含整个 `.cn` 后缀、国内DNS解析更优域名，既不是地理位置判定，也不是直连可用性保证。 |
| 110 | cn (Stash) | ACL4SSR635条；比 mihomo集合小，包含少量IP规则，两个客户端分流覆盖不同。 |
| 112 | geolocation-!cn | YAML27065条、MRS导出27064条；国外优先的路由有意解决cn交集，DNS还未对齐。 |
| 114 | cn-ip | 9648条；MRS有效，只供mihomo。 |
| 14 | CDN | 本次 URL均可下载；动态分支和CDN缓存会导致更新传播延迟。 |
| 15 | self_repo | 与本地补充列表内容核对一致；修改未推送时远程客户端不会自动使用本地文件。 |
| 16 | interval | 86400秒合理；不代表每次更新都已绕过CDN缓存。 |

Stash 为内存减少规则量是合理方向，但“11万行一定装不下”缺少实机峰值内存证据。其 DNS 又用了内置 geosite:cn，应测量内置索引和provider同时加载的开销，不能只用文本行数推断内存。与 mihomo 分流不完全一致，是当前设计的真实取舍。

**分流规则逐条检查**

| spec 行 | 规则 | 结论 |
|---|---|---|
| 121 | extra-direct -> 全球直连 | 最优先，能覆盖广告和AI等所有后续分类；这是强制例外，需控制范围。 |
| 122 | private -> 全球直连 | 排在广告前正确；建议固定 DIRECT，避免组被误切代理。 |
| 123 | private-ip / no-resolve | 正确；已解析/嗅探获得真实IP的连接也可命中，不仅限于“用户直接访问IP”。源注释应修正。 |
| 124 | unban | 顺序保证白名单生效，同时导致F7，不能当成无争议优化。 |
| 125 | adrules | 保留；可配置本地必要例外。 |
| 126 | anti-ad | 保留或评估合并；不能仅据交集删除。 |
| 127 | awavenue | 仅Stash生成，正确。 |
| 129 | AND UDP443 NOT cn | F1；两个客户端cn的domain/classical类型还不同，实际豁免范围不同。 |
| 131 | extra-ai | 在微软/Bing/媒体之前，正确。 |
| 132 | ai | 在微软/Bing之前，正确；不是所有AI登录/CDN域名的完整清单。 |
| 133 | googlefcm | 正确；提前于google-cn。 |
| 134 | google-cn | 直连取舍合理；必须用实际连通性复核，不应认为上游“cn”属性永远准确。 |
| 135 | steam-cn | 在steam前，正确，避免国内下载走代理。 |
| 137 | github | 在microsoft前，正确。 |
| 139 | extra-proxy | 在onedrive与cn前，正确；应同时有DNS例外。 |
| 140 | bing | AI已提前截走，正确。 |
| 141 | onedrive | 网页代理例外已提前，正确；其余直连是否可用要验证。 |
| 142 | microsoft | GitHub/Bing/OneDrive/AI已先分类，正确。 |
| 143 | apple | 可保留；其之前的QUIC规则会改变部分苹果流量。 |
| 144 | telegram | 域名先于IP，合理。 |
| 145 | telegram-ip / no-resolve | 合理；纯IP连接经前面的QUIC规则仍可能先被拒绝。 |
| 146 | netease | 合理。 |
| 147 | epicgames | 合理；下载关键词例外已优先处理。 |
| 148 | ea | 合理。 |
| 149 | sony | 合理。 |
| 150 | playstation | 当前与sony同策略且完全包含，可删除。 |
| 151 | steam | 国内子集已先直连，正确。 |
| 152 | nintendo | 合理；游戏联机需要fake-IP/STUN配套。 |
| 153 | youtube | 在通用媒体前，正确。 |
| 154 | netflix | 在通用媒体前，正确。 |
| 155 | netflix-ip / no-resolve | 合理；不能把shared CDN IP等价于只承载Netflix。 |
| 156 | bahamut | 合理。 |
| 157 | bilibili | 合理。 |
| 158 | proxymedia / no-resolve | 含多个已分类服务，专用规则优先正确。但上游有 DOMAIN-KEYWORD,openai/anthropic 等泛化规则，漏收AI域名会进媒体组而非AI组。建议用维护更明确的媒体集合或拆分，暂不认定必须整体删除。 |
| 159 | gfw | 正确；专用策略在其之前，可独立选择出口。 |
| 163 | geolocation-!cn | mihomo仅有；先于cn有实际理由，148条完全相同的交集已经核实。 |
| 164 | cn / no-resolve | mihomo纯domain中no-resolve冗余但无害；Stash classical中对IP有作用。 |
| 166 | cn-ip | mihomo仅有；解析放末尾合理，但可能被受污染/错误DNS结果影响。 |
| 167 | GEOIP,CN | Stash仅有；同样依赖解析质量。可以评估定期更新的CN IP provider，但要测内存，不能机械套用mihomo。 |
| 168 | MATCH | 正确，尾部兜底。 |
| build.py:101 | Stash DoH IP两条前置规则 | 正确实现指定DNS出站；也覆盖目标为这些IP的非DNS连接及其他端口。建议准确描述为DoH端点IP绑定，不称完全等价于mihomo #组。 |

**三个补充文件逐条检查**

| 文件/行 | 规则 | 结论 |
|---|---|---|
| extra-direct.txt:2 | DOMAIN-KEYWORD,epicgames-download | 能直连Epic下载；关键词可匹配任何含此字符串的域名，建议根据真实下载地址收窄为可维护的域名/后缀，避免任意同名域名被放行。 |
| extra-proxy.txt:5 | DOMAIN-SUFFIX,googleapis.cn | services.googleapis.cn确实命中此规则和cn后缀；补充有实际价值。DNS也应明确境外优先。 |
| extra-proxy.txt:7 | DOMAIN,onedrive.live.com | 确实命中onedrive和microsoft；提前走代理正确。 |
| extra-proxy.txt:8 | DOMAIN-SUFFIX,onedrive.com | api.onedrive.com等确实命中onedrive/microsoft；合理，但覆盖范围不只是网页版。 |
| extra-ai.txt:5 | DOMAIN-SUFFIX,together.ai | 当前上游AI未覆盖，补充合理。 |
| extra-ai.txt:6 | DOMAIN-SUFFIX,together.xyz | 补充合理；保留旧/新域名兼容性。 |
| extra-ai.txt:8 | DOMAIN,ai.azure.com | 当前命中微软通用域名，AI优先规则正确。 |
| extra-ai.txt:10 | DOMAIN,sydney.bing.com | 当前命中Bing，AI优先规则正确。 |
| extra-ai.txt:12 | DOMAIN,client-api.arkoselabs.com | 用同组出口有价值，但共享验证码服务不只用于ChatGPT；跨服务固定代理是取舍。单个域名不能保证全部登录链路出口一致。 |

**两份 INI 与国外覆写逐项检查**

INI两个客户端的结构一致，区别只在底包与注释；每个custom_proxy_group已按上面的策略组逐项核对。

| 位置 | 内容 | 结论 |
|---|---|---|
| INI:1 | [custom] | 正确。 |
| INI:6 | ruleset=漏网之鱼,[]FINAL | 正确；应在底包现有rules之后追加。上游overwrite=false的实现与设计相符。 |
| INI:8–37 | 所有custom_proxy_group | 组名/引用/regex均核对；PCRE风格负向环视由转换器/Xboard处理，不应作为mihomo原生Go regex直接使用。 |
| INI:30–37 | 地区url-test | 缺节点时自动DIRECT，F6；600,,容差语法有效。 |
| INI:39 | enable_rule_generator=true | 正确，需要它追加FINAL。 |
| INI:40 | overwrite_original_rules=false | 正确，避免删除底包分流。 |
| INI:42 | clash_rule_base | 正确指向对应底包；由服务端拉取GitHub原地址，网络失败时不能只靠客户端provider恢复。 |
| spec:173 | 国外 private -> DIRECT | 路由正确；DNS必须保留system例外。 |
| spec:174 | 国外 private-ip / no-resolve | 正确。 |
| spec:175 | 国外 unban | 仍提前放行F7中的跟踪域名，建议同国内模式一起收窄。 |
| spec:176 | 国外 adrules -> REJECT | 合理；直接REJECT，不跟随广告组选择。 |
| spec:177 | 国外 anti-ad -> REJECT | 合理。 |
| spec:178 | 国外 extra-ai | 正确；保持AI走指定组。 |
| spec:179 | 国外 ai | 正确。 |
| spec:180 | 国外 MATCH,DIRECT | 确实阻止后续国内模式规则继续匹配；因此不会继续执行原QUIC规则。 |
| spec:182–188 | 国外DNS基本项 | 与mihomo fake-IP设置一致；fake-ip-filter使用相同列表。 |
| spec:189 | respect-rules:false | 国外DNS直连意图明确；AI DNS也默认直连当地DoH，与AI代理出口未绑定，是取舍。 |
| spec:190–191 | use-hosts/system-hosts | 合理；不能替代LAN DNS policy。 |
| spec:192 | default-nameserver | 两个IP纯引导DNS；没有DNS服务器域名时不一定产生实际请求。 |
| spec:193 | nameserver | 国外两份IP DoH合理；F13。 |
| spec:194 | proxy-server-nameserver | 独立节点解析合理；没有国内DNS。 |
| overseas.yaml:10 | +rules | 插入最前面的设计正确；Clash Party实际合并语义仍需客户端验证。 |
| overseas.yaml:20 | dns! | 整段替换符合设计；必须关闭客户端“控制DNS设置”。 |

**生成器、校验器和文档的改进**

1. `render_rules()` 对缺失provider无条件跳过，当前用于跨客户端裁剪合理，但拼错provider也会被静默删掉。建议区分“另一客户端专有”与“源头未定义”，后者报错。
2. `rules()` 只检查RULE-SET引用，没检查全部策略目标、重复组名、组循环和DNS的#组引用。真实内核可发现部分错误，但在生成阶段报出源头问题更易维护。
3. DNS/嗅探/全局设置硬编码在build.py；对它们也建立spec字段，才能兑现“唯一源头”。
4. `check.py`只调用mihomo；Stash只检查了模拟地区regex，不能对外称为“Stash内核校验通过”。
5. Xboard真实PHP渲染会先移除regex再向数组末尾追加节点；Python模拟在regex原位置插入。地区组真实结果可能REJECT在前，启动/全节点失败时默认行为需要验证。
6. Xboard当前上游在无节点时regex处理位于节点循环内部，Python模拟并不相同；应加入0节点与全部被过滤情形。
7. subprocess timeout没有专门处理，校验超时输出可改成简洁明确的失败信息。当前不是配置有效性错误。
8. CI依赖latest内核是兼容性预警，但可另设受支持的最低版本以避免新版本通过、实际旧客户端不支持MRS或DNS字段。
9. CI下载命令可增加curl失败检查、资源为空检查和可执行文件验证；此次实际下载成功，不构成现存配置失效证据。
10. provider URL可增加定期下载/解析检查。`mihomo -t`走配置解析分支，没有启动运行时provider更新，无法覆盖远程内容错误。
11. “url-test永远不会选中REJECT”应改成“有健康节点时通常选健康节点；空组/全部不可用时REJECT可能成为当前项”。
12. “QUIC走代理时拒绝”“国内目标不受影响”“Stash完全等价#组”“所有url-test均lazy”的注释需按最终实现修正。
13. “no-resolve只匹配本来就是IP的连接”应修正为“不为此规则额外触发域名解析；若元数据已有真实IP仍能匹配”。

**建议实施顺序**

先修局域网DNS、Stash通配符过滤和空地区组行为；随后确定QUIC与DNS隐私/解析策略，补DNS例外；再收窄UnBan、清理PlayStation重复和完善真实渲染边界验证。广告列表合并、进一步减少策略组和调整测速频率应在观察内存、耗电和误杀后进行。

**可复核的外部依据**

- [mihomo v1.19.32](https://github.com/MetaCubeX/mihomo/tree/v1.19.32)：`adapter/outbound/direct.go` 的独立DIRECT解析、`dns/resolver.go` 的DirectFollowPolicy、`rules/provider/rule_set.go` 的no-resolve、`adapter/outboundgroup/urltest.go` 的选择行为、`main.go` 的`-t`分支。
- [Stash DNS](https://stash.wiki/features/dns-server)：follow-rule、system policy、节点解析、协议/版本门槛。
- [Stash官方配置样例](https://stash.wiki/configuration/example-config)：带中间星号的STUN fake-ip-filter。
- [Stash规则集合](https://stash.wiki/rules/rule-set)：domain/ipcidr/classical与yaml/text、path、inline的版本限制。
- [Stash iOS更新日志](https://stash.wiki/release-notes/ios)：3.4.0的nameserver-policy geosite支持。
- [subconverter导出实现](https://github.com/tindy2013/subconverter/blob/master/src/generator/config/subexport.cpp)：空组DIRECT、Lazy按配置输出、原始YAML保留与规则生成。
- [Xboard ClashMeta渲染](https://github.com/cedar2025/Xboard/blob/master/app/Protocols/ClashMeta.php)、[Stash渲染](https://github.com/cedar2025/Xboard/blob/master/app/Protocols/Stash.php)：正则在服务端执行、空组处理、订阅域名DIRECT插入。用户实际部署版本仍需对照。
- [MetaCubeX规则库](https://github.com/MetaCubeX/meta-rules-dat/tree/meta/geo)：实际下载的MRS/YAML列表。
- [ACL4SSR UnBan](https://github.com/ACL4SSR/ACL4SSR/blob/master/Clash/UnBan.list)、[ProxyMedia](https://github.com/ACL4SSR/ACL4SSR/blob/master/Clash/ProxyMedia.list)、[ChinaDomain](https://github.com/ACL4SSR/ACL4SSR/blob/master/Clash/ChinaDomain.list)：实际下载的text列表。
