// Clash Party 本地覆写（JavaScript）· 指定域名 / IP 固定走某个节点，并可开本地端口隧道到该节点后面的服务
// 文档：https://clashparty.org/docs/guide/override/javascript
//
// 场景：自己的服务器只放行某个节点的出口 IP；某台机器只能从特定地区访问；或用 tunnels 把远端端口映射到本机。
// 两组规则：RULES 插在所有规则最前面（按域名或纯 IP 匹配，零解析）；LATE_IP_RULES 插在 cn-ip 前面
// （按解析后的 IP 匹配，只有前面所有域名规则都没命中的域名才会到这里，cn-ip 本来就要解析它们，不多花一次 DNS）。
// 节点不在订阅里时（换了机场、节点下线）：引用它的规则改走 FALLBACK，FALLBACK 为 null 则跳过这些规则；
// 隧道只在节点存在时添加。其他规则（如写了 DIRECT 的）照常加入。
// 用法：复制到 Clash Party → 覆写 → 新建 JavaScript 覆写，改下面几个常量。重复导入是幂等的。
// 本文件是模板，不含任何节点、域名或 IP。

const NODE = '节点名或策略组名';
const FALLBACK = null; // 节点不存在时的替代去向，如 '🚀 节点选择'；null = 跳过引用该节点的规则

// 不写去向 = 走 NODE；写了去向按写的。不要在这里写 MATCH。
// 最前面的规则：域名规则直接比对域名；IP 规则自动补 no-resolve，只匹配按 IP 直接访问的连接
//（否则排在最前面的 IP 规则会让每个域名连接都先在本地解析一次，白等一轮 DNS）。
const RULES = [
  // 'DOMAIN,example.com',
  // 'IP-CIDR,203.0.113.5/32',
  // 'DOMAIN,b.example.com,DIRECT',
];

// cn-ip 之前的 IP 规则：想让"解析到这些 IP 的域名"也命中时放这里（不加 no-resolve）。
// 前提是这些域名没被前面的集合截走——个人域名一般如此（foreign 只含 .google 这类品牌顶级域，不含 .de/.io/.com）。
const LATE_IP_RULES = [
  // 'IP-CIDR,198.51.100.7/32,DIRECT',
];

// 本机端口 → 经 NODE 转发到远端（mihomo tunnels）
const TUNNELS = [
  // { network: ['tcp'], address: '127.0.0.1:51040', target: '203.0.113.5:51040' },
];

function main(config) {
  const hasNode =
    (config.proxies || []).some((p) => p.name === NODE) ||
    (config['proxy-groups'] || []).some((g) => g.name === NODE);
  if (!hasNode) console.log(`未找到节点「${NODE}」：${FALLBACK ? `改走 ${FALLBACK}` : '跳过引用它的规则'}，不添加隧道`);

  const isIp = (type) => /^(IP-CIDR6?|IP-SUFFIX|IP-ASN|GEOIP)$/.test(type);
  const build = (list, noResolve) => {
    const out = [];
    for (const raw of list) {
      const parts = raw.split(',');
      if (parts.length < 3) parts.push(NODE);
      if (parts[2] === NODE && !hasNode) {
        if (!FALLBACK) continue;
        parts[2] = FALLBACK;
      }
      if (noResolve && isIp(parts[0]) && !parts.includes('no-resolve')) parts.push('no-resolve');
      out.push(parts.join(','));
    }
    return out;
  };

  const mine = new Set([...build(RULES, true), ...build(LATE_IP_RULES, false)]);
  const old = (config.rules || []).filter((r) => !mine.has(r)); // 幂等：先清掉上次加的
  let at = old.findIndex((r) => r.startsWith('RULE-SET,cn-ip,'));
  if (at < 0) at = Math.max(old.findIndex((r) => r.startsWith('MATCH,')), 0);
  config.rules = [...build(RULES, true), ...old.slice(0, at), ...build(LATE_IP_RULES, false), ...old.slice(at)];

  if (hasNode && TUNNELS.length) {
    const existing = new Set((config.tunnels || []).map((t) => t.address));
    config.tunnels = [
      ...(config.tunnels || []),
      ...TUNNELS.filter((t) => !existing.has(t.address)).map((t) => ({ ...t, proxy: NODE })),
    ];
  }
  return config;
}
