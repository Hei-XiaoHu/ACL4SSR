# ACL4SSR（Hei-XiaoHu 自用版）

一套规则，覆盖三个客户端：

| 客户端 | 获取方式 | 使用的文件 |
|---|---|---|
| Clash Party（电脑） | subconverter + ini，或 Xboard 订阅 | `Clash/config/ACL4SSR_Online_Full_AdblockPlus.ini`（底包 `dns_enhanced.yml`）/ `Xboard/custom.clashmeta.yaml` |
| Clash Meta for Android | 同上 | 同上 |
| Stash（iOS） | subconverter + Stash ini，或 Xboard 订阅 | `Clash/config/ACL4SSR_Online_Full_AdblockPlus_Stash.ini`（底包 `dns_enhanced_stash.yml`）/ `Xboard/custom.stash.yaml` |
| 国外模式（仅电脑） | Clash Party 远程覆写 | `Clash/override/overseas.yaml` |

## 修改规则

**只改 `src/spec.yaml`**，然后：

```bash
pip install pyyaml
python3 tools/build.py                 # 生成全部配置
python3 tools/check.py /path/to/mihomo # 可选：用真实内核校验
```

推送后 GitHub Actions 会检查生成文件是否与 `src/spec.yaml` 一致，并用最新 mihomo 跑 `mihomo -t`。

自定义补充规则（直接改，无需生成）：
- `Clash/rule/extra-direct.txt`：强制直连
- `Clash/rule/extra-ai.txt`：geosite 未收录的 AI 域名

## 方案要点

- **规则来源**：MetaCubeX/meta-rules-dat（v2fly 社区，每日同步）。mihomo 用 mrs 二进制格式，匹配快、内存小；Stash 用 yaml 版。
- **去广告**：mihomo 用 AdRules + anti-AD（mrs）；Stash 用 AWAvenue（iOS 网络扩展约 50MB 内存上限）。
- **性能**：含 IP 的规则集一律 `no-resolve`，需要解析域名的 `cn-ip` / `GEOIP,CN` 放在最后；已知国外域名由 `geolocation-!cn` 直接分流，不触发 DNS 查询。
- **耗电**：url-test 组 `lazy` + 600 秒测速；日志 `warning`；DoH 只保留 2 个。
- **安全**：`allow-lan` 关闭，DNS 仅监听 127.0.0.1；国外 DoH 经节点发出，国内域名用国内 DoH。
- **QUIC**：发往国外的 UDP 443 一律拒绝，浏览器自动回落 TCP。

## 国外模式（Clash Party）

1. 设置里**关闭「控制 DNS 设置」**（否则软件自身 DNS 优先级更高，覆写里的 DNS 不生效）；建议同时关闭「控制域名嗅探」，统一使用配置内的嗅探设置。
2. 覆写 → 导入远程链接：`https://testingcf.jsdelivr.net/gh/Hei-XiaoHu/ACL4SSR@master/Clash/override/overseas.yaml`
3. 出国时在订阅的「编辑信息」里勾选该覆写：AI 走 `💬 Ai平台`，广告照常拦截，其余全部直连，DNS 换成国外 DoH。
4. **回国后取消勾选。**
