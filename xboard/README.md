# Xboard 订阅模板（免 subconverter）

与本仓库 `Clash/config/ACL4SSR_Online_Full_AdblockPlus*.ini` 同一套规则，均由 `tools/build.py` 从 `src/spec.yaml` 生成，**请勿手改**。

| 文件 | 后台模板槽位（按 UA 分发） | 说明 |
|---|---|---|
| `custom.clashmeta.yaml` | `clashmeta`（UA 含 meta / verge / flclash / nekobox / clashmetaforandroid）与 `clash`（其余含 clash 的 UA） | mrs 规则集 + AdRules/anti-AD + 嗅探 + DNS 走节点 |
| `custom.stash.yaml` | `stash` | mrs 规则集 + AWAvenue；DNS 走节点用 `follow-rule` 等价实现；需 Stash iOS 3.6+ |
| `custom.stash-full.yaml` | （暂不部署） | Stash 完整版：规则与 `custom.clashmeta.yaml` 完全一致（下载同一批 `mihomo/` mrs），不用原生 GEOSITE；iOS 内存实测通过后再替换 `stash` 槽位 |

- `clash` 槽位也放 mihomo 模板：Clash Premium 已停更且不支持 mrs，现在 UA 落到 `clash` 的基本是 mihomo 内核但 UA 不含上述关键字的客户端（Clash Nyanpasu、Clash Mi 等）。
  注意 Xboard 的 Clash 渲染器只下发 ss/vmess/trojan/socks/http 节点，VLESS/Hysteria2/TUIC/AnyTLS 会被过滤——这是 Xboard 的限制，不是模板的问题；能改 UA 的客户端建议把 UA 改成含 `meta` 的值。
- `singbox` / `surge` / `surfboard` 槽位留空，Xboard 会下发自带默认模板（只有国内直连 + 节点选择）。本仓库暂不维护这三种格式：需要 rules 分支另发 .srs 与 Surge 文本列表，且 DNS/QUIC 语义与 mihomo 不同。

## 部署方式

新版 Xboard 的订阅模板存在数据库（后台 → 系统配置 → 订阅模板），`resources/rules/custom.*.yaml` 文件已不再读取。
OVH 上 `/docker/service/xboard/scripts/sync-subscribe-template.sh` 每小时（cron `15 * * * *`）从本仓库 master 拉取 `xboard/custom.clashmeta.yaml` → `clash` + `clashmeta`、`xboard/custom.stash.yaml` → `stash`，
校验 YAML 后经 `php artisan tinker` 写入数据库并清 Redis 缓存；内容无变化不写入。日志在 `/docker/log/xboard-template-sync.log`。
推送 master 后最多 1 小时生效，想立即生效可手动执行该脚本。

## 模板机制备忘

- `proxies: []` 由 Xboard 注入节点
- 策略组里 `/正则/i` 是节点筛选器（PCRE，Xboard 侧执行）；不含正则的组 Xboard 会自动追加全部节点，所以不该含节点的组（🛑 广告等）写了一个永不匹配的 `/^$/`
- 节点筛选正则统一排除名称含 剩余/到期/过期/官网/套餐/流量/重置/倍率 的节点
- ♻️ 自动选择末尾的 `REJECT` 是保活占位：无匹配节点时防止组被删除导致引用报错；url-test 永远不会选中 REJECT
- Xboard 会自动把订阅域名加为 DIRECT 首条规则
