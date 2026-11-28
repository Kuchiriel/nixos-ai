#!/usr/bin/env node
// host-proxy.mjs — proxy HTTP que REESCREVE o Host (para o vite preview, que
// so aceita localhost/IP e devolve 403 com o nome magico do tailnet).
//
// (15/11, crouton-alpha) O Tailscale Serve entrega o Host original
// (host tailnet) e o vite preview do JARVIS recusa com 403.
// Aqui o Host e trocado por 127.0.0.1 e o X-Forwarded-Host preserva o
// original (o backend do webui le o host para montar URLs).
//
// uso: host-proxy.mjs <porta_local> <porta_proxy> [host_aceito]
import { createServer, request } from 'node:http';

const PORT = Number(process.env.PORT || 5174);
const TARGET = Number(process.env.TARGET || 5173);
const HOST_HEADER = process.env.TARGET_HOST || '127.0.0.1';

createServer((req, res) => {
  const opts = {
    host: '127.0.0.1',
    port: TARGET,
    method: req.method,
    path: req.url,
    headers: { ...req.headers, host: HOST_HEADER, 'x-forwarded-host': req.headers.host || '' },
  };
  const p = request(opts, (up) => {
    res.writeHead(up.statusCode || 502, up.headers);
    up.pipe(res);
  });
  p.on('error', (e) => { res.writeHead(502); res.end(String(e)); });
  req.pipe(p);
}).listen(PORT, '127.0.0.1', () => console.log(`[host-proxy] ${PORT} -> 127.0.0.1:${TARGET} (Host reescrito)`));
