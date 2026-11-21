# Painel de pendências no mission control (21/11)

Rotas novas no `agent-hub` (`:8091`, servidas por Tailscale Serve em `/hub`):

- `GET /api/pending` — JSON com `counts`, `items` e ponteiro para o estado.
- `GET /api/pending/state` — o próprio `PROJECT-AUDIT-STATE.md` em Markdown.

Mesmo padrão de `/api/cards`: read-only, paths derivados de evidência, e
bloqueio da resposta se o payload contiver marcador de credencial.

Fontes (nenhuma duplicada no servidor):

| fonte | itens |
|---|---:|
| `docs/audit/TECHNICAL-DEBT.md` (seções P0–P3) | 24 |
| `ai-mesh/docs/auto-improve-gaps.jsonl` | 11 |
| `docs/audit/PROJECT-AUDIT-STATE.md` (próximos passos) | 5 |

A UI ganhou a aba **📌 pendências** com badge `kind`/nível, link para o estado
canônico e botão de refresh. A doc não é reescrita — o painel apenas a lê.

Validação: `node --check` limpo; só `agent-hub.service` reiniciado (opencode
intacto); do celular via IPv6 do tailnet `/hub/api/pending` e
`/hub/api/pending/state` responderam 200; 40 itens servidos; varredura de
segredos nos payloads: 0 ocorrências.
