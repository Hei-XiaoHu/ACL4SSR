// Clash Party 本地覆写（JavaScript）· 追加订阅之外的自有节点（落地机、家宽等），加进所有手选策略组
// 文档：https://clashparty.org/docs/guide/override/javascript
//
// 效果：节点插到最后一个名字匹配 ANCHOR 的订阅节点后面（面板里挨着同类节点），并加入所有已经含有
//       订阅节点的 select 组；不进自动测速组，也不进只放策略组/DIRECT/REJECT 的组（如 🛑 广告）。
// 用法：复制到 Clash Party → 覆写 → 新建 JavaScript 覆写，填 NODES。重复导入是幂等的；
//       改过名字的旧节点写进 OLD_NAMES 会被一并清掉。
// 本文件是模板。填入真实凭据后只保存在本机覆写里，不要提交到仓库或分享。

const NODES = [
  // 任意 mihomo 节点格式，下面是 Shadowsocks 示例
  { name: '🏠 自有节点', type: 'ss', server: 'example.com', port: 443, cipher: 'aes-128-gcm', password: '', udp: true },
];
const OLD_NAMES = []; // 以前用过、现在要清掉的节点名
const ANCHOR = /自有节点/; // 插到最后一个匹配的节点后面；没有匹配则放末尾。null = 直接放末尾

function insertAfterAnchor(list, item) {
  const nameOf = (x) => (typeof x === 'string' ? x : x.name);
  let idx = -1;
  if (ANCHOR) list.forEach((x, i) => { if (ANCHOR.test(nameOf(x))) idx = i; });
  if (idx < 0) list.push(item);
  else list.splice(idx + 1, 0, item);
}

function main(config) {
  const drop = new Set([...NODES.map((n) => n.name), ...OLD_NAMES]);
  const proxies = (config.proxies || []).filter((p) => !drop.has(p.name));
  const subNames = new Set(proxies.map((p) => p.name)); // 订阅自带的节点
  for (const node of NODES) insertAfterAnchor(proxies, node);
  config.proxies = proxies;

  for (const g of config['proxy-groups'] || []) {
    if (!Array.isArray(g.proxies)) continue;
    g.proxies = g.proxies.filter((x) => !drop.has(x));
    if (g.type !== 'select' || !g.proxies.some((x) => subNames.has(x))) continue;
    for (const node of NODES) insertAfterAnchor(g.proxies, node.name);
  }
  return config;
}
