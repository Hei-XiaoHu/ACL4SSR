// Clash Party 本地覆写（JavaScript）· 按本机 SOCKS5 端口给游戏分配节点，配合 ProxiFyre 使用
// 文档：https://clashparty.org/docs/guide/override/javascript
//
// 原理：ProxiFyre 按进程把游戏流量送到 127.0.0.1 的不同端口；这里为每个端口开一个 SOCKS5 监听，
//       并指定它走哪个节点。节点名按正则匹配订阅里的节点（也可以直接写策略组名），
//       没有匹配到时走 FALLBACK（默认 DIRECT：游戏照常能玩，只是不加速）。
// 用法：复制到 Clash Party → 覆写 → 新建 JavaScript 覆写，改 GAME_PORTS 里的端口与节点关键词；
//       ProxiFyre 里把对应游戏进程指向同一个端口。重复导入是幂等的：旧的同名/同端口监听会先被清掉。
// 本文件是模板，不含任何节点信息。

const GAME_PORTS = [
  // name：监听名（任意，唯一）  port：ProxiFyre 里填的端口  match：节点名正则或精确的节点/策略组名
  { name: 'game-a', port: 7899, match: /节点关键词A/i }, // 例：PUBG / Apex
  { name: 'game-b', port: 7898, match: /节点关键词B/i }, // 例：三角洲
];
const FALLBACK = 'DIRECT'; // 没匹配到节点时的去向，也可填策略组名（如 '🎮 游戏'）

function pick(match, proxies, groups) {
  if (typeof match === 'string') {
    return proxies.includes(match) || groups.includes(match) ? match : null;
  }
  return proxies.find((n) => match.test(n)) || groups.find((n) => match.test(n)) || null;
}

function main(config) {
  const proxies = (config.proxies || []).map((p) => p.name);
  const groups = (config['proxy-groups'] || []).map((g) => g.name);
  const names = new Set(GAME_PORTS.map((g) => g.name));
  const ports = new Set(GAME_PORTS.map((g) => g.port));
  const listeners = (config.listeners || []).filter((l) => !names.has(l.name) && !ports.has(l.port));

  for (const g of GAME_PORTS) {
    const target = pick(g.match, proxies, groups) || FALLBACK;
    listeners.push({ name: g.name, type: 'socks', listen: '127.0.0.1', port: g.port, udp: true, proxy: target });
    console.log(`${g.name} 127.0.0.1:${g.port} -> ${target}${target === FALLBACK ? '（未匹配到节点）' : ''}`);
  }

  config.listeners = listeners;
  return config;
}
