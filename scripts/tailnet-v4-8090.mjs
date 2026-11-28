#!/usr/bin/env node
// Forward minimo: 100.121.100.103:8090 (Tailscale IPv4) -> [::1]:8090 (webui backend IPv6-only).
import net from 'node:net';
const TARGET_HOST = process.env.FORWARD_TARGET_HOST || '127.0.0.1', TARGET_PORT = Number(process.env.FORWARD_TARGET_PORT||8090), BIND = process.env.FORWARD_BIND || '100.121.100.103', PORT = Number(process.env.FORWARD_PORT||8090);
net.createServer((down) => {
  const up = net.connect({ host: TARGET_HOST, port: TARGET_PORT, family: 6 });
  down.pipe(up).pipe(down);
  down.on('error', () => up.destroy());
  up.on('error', () => down.destroy());
}).listen(PORT, BIND, () => console.log(`[forward] ${BIND}:${PORT} -> [::1]:${TARGET_PORT}`));
