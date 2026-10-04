# ACL4SSR（Hei-XiaoHu 自用版）

一套规则，覆盖三个客户端：

| 客户端 | 获取方式 | 使用的文件 |
|---|---|---|
| Clash Party（电脑） | subconverter + ini，或 Xboard 订阅 | `Clash/config/ACL4SSR_Online_Full_AdblockPlus.ini`（底包 `dns_enhanced.yml`）/ `Xboard/custom.clashmeta.yaml` |
| Clash Meta for Android | 同上 | 同上 |
| Stash（iOS） | subconverter + Stash ini，或 Xboard 订阅 | `Clash/config/ACL4SSR_Online_Full_AdblockPlus_Stash.ini`（底包 `dns_enhanced_stash.yml`）/ `Xboard/custom.stash.yaml` |
| 国外模式（仅电脑） | Clash Party 远程覆写 | `Clash/override/overseas.yaml` |

## 修改规则

配置、策略组、DNS 与嗅探参数统一在 `src/spec.yaml`。本地规则在 `Clash/rule/`；修改后重新生成：

```bash
pip install pyyaml
python3 tools/build.py                 # 生成全部配置
python3 tools/build.py --check         # 检查七份输出一致
python3 tools/check.py /path/to/mihomo  # 渲染与真实内核校验，含缺地区/全过滤场景
python3 tools/check_routing.py /path/to/mihomo # 离线连接、DNS、QUIC 与广告回归
```

推送后 GitHub Actions 会检查生成文件一致性，并用最新 mihomo 校验配置和离线分流。Stash 的结论来自官方文档与静态检查，不能用 mihomo 代替 Stash 实机验证。

主要本地规则：

- `Clash/rule/extra-direct.txt`：强制直连
- `Clash/rule/extra-proxy.txt`：强制走 🚀 节点选择（被墙但会被 cn 截走直连的域名）
- `Clash/rule/extra-ai.txt`：geosite 未收录的 AI 域名
- `Clash/rule/claude*.txt`：Claude 家族、必要功能例外、可选遥测和自有 IP
- `Clash/rule/shared-auth.txt`：共享验证码，走通用节点，不固定到 AI
- `Clash/rule/quic-exempt.txt`：某个游戏/应用因 QUIC 拦截连不上时，把域名加到这里
- `Clash/rule/functional-direct.txt`：精简的功能白名单，替换宽泛 UnBan

Stash DNS 的国内属性标签展开为少量字面域名，缓存于 `src/stash-dns-cn.yaml`，避免依赖未确认的 `geosite:name@cn` DNS 语法。更新上游标签时运行：

```bash
python3 tools/update_stash_dns.py       # 更新小型 DNS 缓存
python3 tools/build.py
python3 tools/update_stash_dns.py --check # 只核对上游差异，不写文件
```

路由 provider 仍每日使用维护中的上游列表；DNS 缓存需随标签变化同步。

## 方案要点

- **规则来源**：MetaCubeX/meta-rules-dat（v2fly 社区，每日同步）。mihomo 用 mrs 二进制格式，匹配快、内存小；Stash 用 yaml 版。
- **去广告**：mihomo 保留 AdRules + anti-AD（mrs），两者有独有规则；Stash 用轻量 AWAvenue。规则条数不能直接证明 iOS 峰值内存。
- **性能**：已有 IP 的直接分类使用 `no-resolve`，需要额外解析的 `cn-ip` / `GEOIP,CN` 放末尾；已知国外域名提前分流。
- **测速**：600 秒；Xboard 显式 `lazy:true`，INI 的 mihomo 依赖内核默认 true，其他转换器/客户端以实际输出为准。空地区与全过滤的自动组保留 REJECT。测速不验证 AI/媒体解锁，AI 支持地区应手动选择，固定出口可直接选单个节点。
- **DNS**：内网 system → 本地代理例外 → 国内游戏/娱乐标签 → 国外集合 → cn。mihomo 境外 DoH 显式 `#🛰️ DNS-Proxy`；节点域名使用独立直连解析器，DIRECT 遵循 policy。Stash follow-rule 加 DoH 端点 IP 绑定指定组；绑定也影响这些 IP 的其他流量。
- **安全**：mihomo `allow-lan:false`，代理控制器与 DNS 监听本机；DNS `ipv6:false` 只控制解析，不能代替系统 IPv6 设置。Bootstrap 仍用明文引导 DNS。
- **QUIC**：默认走代理的境外域名（AI、媒体、gfw、geolocation-!cn、共享验证码等）及 Anthropic 自有 IP 的 QUIC 被拒绝，回落 TCP（VLESS 等 TCP 传输承载 QUIC 效果差）。默认直连的苹果/微软/Bing/OneDrive/网易云/B站、国内、游戏、游戏下载、通信语音、`quic-exempt.txt` 和未知裸 IP 不拦；保留 `google-cn` 的 QUIC 豁免。mihomo 按 UDP443 判断；Stash 用 `PROTOCOL,QUIC` 只拦真正的 QUIC。规则按默认分组判断，手动切换策略组后不会跟着变。
- **谷歌服务**：`google-cn` 与完整 `google` 集合走 `🌐 谷歌服务`，默认选择 `🚀 节点选择`，使用境外 DNS；Chrome 商店、Google 资源与 `dl.google.com` 下载统一分流。AI、谷歌 FCM 和 YouTube 保留各自专用策略。
- **分类**：游戏下载使用完整的 `category-game-platforms-download`（约 490 条，含 Steam/PSN/Epic 等全球 CDN），默认直连；国内下载/娱乐子集优先；Battle.net、Ubisoft、GOG 等补入游戏平台。通用媒体改用社区娱乐集合。
- **iOS**：Stash 规则与 mihomo 基本一致，差异仅在广告源（AWAvenue 轻量版）及用 Stash 原生 GEOSITE/GEOIP 替代 cn、geolocation-!cn、cn-ip 规则集。若希望与电脑完全一致，可用内置 mihomo 内核的 Clash Mi（KaringX/clashmi，App Store 上架，iOS 15+），直接使用 mihomo 模板；本仓库未做 Clash Mi 实机测试。
- **Stash**：DNS geosite policy 需 iOS3.4.0+。原生 GEOSITE 数据首次从 GitHub 按需加载，需 GitHub 可达；未加入需要3.6+的独立节点 DNS 字段。

完整改动与验证边界见 [修复结果](docs/config-updates.md)、[Claude 分类依据](docs/claude-routing.md)。[初始逐项审计](docs/mihomo-stash-audit.md)保留修改前的行号与问题。

## 国外模式（Clash Party）

1. 设置里**关闭「控制 DNS 设置」**（否则软件自身 DNS 优先级更高，覆写里的 DNS 不生效）；建议同时关闭「控制域名嗅探」，统一使用配置内的嗅探设置。
2. 覆写 → 导入远程链接：`https://testingcf.jsdelivr.net/gh/Hei-XiaoHu/ACL4SSR@master/Clash/override/overseas.yaml`
3. 出国时在订阅的「编辑信息」里勾选该覆写：AI 走 `💬 Ai平台`，广告照常拦截，其余全部直连，DNS 换成国外 DoH。
4. **回国后取消勾选。**

国外覆写也保留内网 system policy。AI DNS 使用所在地的境外 DoH，业务可另选代理；二者未强制同出口。Xboard 零订阅节点时所对照的上游可能残留筛选 regex，需要服务端处理。文件推送并刷新订阅/规则后才会影响远程客户端；旧连接可重启内核清理。
