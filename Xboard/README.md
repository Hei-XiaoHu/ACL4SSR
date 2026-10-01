# Xboard 订阅模板（免 subconverter）

与本仓库 `Clash/config/ACL4SSR_Online_Full_AdblockPlus*.ini` 同一套规则，均由 `tools/build.py` 从 `src/spec.yaml` 生成，**请勿手改**。

| 文件 | 客户端 (flag) | 说明 |
|---|---|---|
| `custom.clashmeta.yaml` | Clash Meta / mihomo（Clash Party、CMFA、FlClash 等） | mrs 规则集 + AdRules/anti-AD + 嗅探 + DNS 走节点 |
| `custom.stash.yaml` | Stash（iOS/macOS） | yaml 规则集 + AWAvenue；DNS 走节点用 `follow-rule` 等价实现 |

Clash 原版/Premium 旧内核不再提供模板（不支持 mrs），这类客户端会拿到 Xboard 内置默认模板。

## 安装

把两个文件放到 Xboard 项目的 `resources/rules/` 目录（文件名不能改）：

```bash
# Docker Compose 部署（在 Xboard 目录）
cp custom.clashmeta.yaml custom.stash.yaml ./resources/rules/
rm -f ./resources/rules/custom.clash.yaml   # 如之前放过旧版
docker compose restart
```

Xboard 会按客户端 UA 自动分发对应模板，订阅地址不变。

## 模板机制备忘

- `proxies: []` 由 Xboard 注入节点
- 策略组里 `/正则/i` 是节点筛选器（PCRE，Xboard 侧执行）；不含正则的组 Xboard 会自动追加全部节点，所以不该含节点的组（🛑 广告拦截等）写了一个永不匹配的 `/^$/`
- 节点筛选正则统一排除名称含 剩余/到期/过期/官网/套餐/流量/重置/倍率 的节点
- 地区组末尾的 `REJECT` 是保活占位：无匹配节点时防止组被删除导致引用报错；url-test 永远不会选中 REJECT
- Xboard 会自动把订阅域名加为 DIRECT 首条规则
