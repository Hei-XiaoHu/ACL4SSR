# Xboard 订阅模板（免 subconverter）

与本仓库 `Clash/config/ACL4SSR_Online_Full_AdblockPlus*.ini` 同一套规则方案，由 Xboard 直接渲染完整配置，无需 subconverter。

| 文件 | 客户端 (flag) | 说明 |
|---|---|---|
| `custom.clashmeta.yaml` | Clash Meta / mihomo（clash-verge、FlClash、CMFA 等） | 完整功能：多路 DoH 竞速 + DNS 走节点 + AdRules/anti-AD |
| `custom.stash.yaml` | Stash（iOS/macOS） | 同上，DNS 走节点用 `follow-rule` 等价实现 |
| `custom.clash.yaml` | Clash 原版/Premium 旧核（CFW、ClashX、旧 CFA） | 旧核 provider 只吃 YAML payload，分流列表改用 blackmatrix7 同类规则；无 DNS 走节点、无 EasyList 级 AdBlock |

## 安装

把三个文件放到 Xboard 项目的 `resources/rules/` 目录（文件名不能改）：

```bash
# Docker Compose 部署（在 Xboard 目录）
cp custom.clash.yaml custom.clashmeta.yaml custom.stash.yaml ./resources/rules/
docker compose restart
```

Xboard 会按客户端 UA 自动分发对应模板，订阅地址不变。

## 模板机制备忘

- `proxies: []` 由 Xboard 注入节点
- 策略组里 `/正则/i` 条目是节点筛选器（PCRE，Xboard 侧执行）；不含正则的组自动追加全部节点
- 地区组末尾的 `REJECT` 是保活占位：无匹配节点时防止组被删除导致引用报错；url-test 永远不会选中 REJECT
- Xboard 会自动把订阅域名加为 DIRECT 首条规则

## 与 ini 方案的关系

规则内容、分组、去广告与 `Clash/customBaseConfigs/dns_enhanced*.yml` 保持一致；改规则时两边同步维护。
