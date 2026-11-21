# Estado de resolução no painel de pendências (21/11)

`/api/pending` passou a incluir `resolution` e `counts.resolution_*` lendo
**um único arquivo versionado**: `ai-mesh/docs/auto-improve-resolution.json`.
Esse arquivo é publicado pelo `auto-improve --snapshot` no celular e chega ao
hub pelo sync do repo — não há segundo estado local no servidor.

Valores medidos no ar:

| campo | valor |
|---|---:|
| `arquivadas` | 23 |
| `pendentes_de_fechamento` | 0 |
| `ts` | 2026-11-21T12:32:20+00:00 |
| `fonte` | `auto-improve --audit (resolution)` |

O item aparece na aba 📌 pendências com `kind=resolution` e o mesmo badge dos
demais itens; nenhuma rota nova foi criada.

Bug corrigido na origem: a chave `resolution` não tinha sido inserida em
`pendingFiles()` porque o texto esperado usava aspas simples; a rota respondia
`indisponivel: true`. Após a correção, `/hub/api/pending` respondeu 200 pelo
IPv6 do tailnet com 42 itens, varredura de segredo 0 ocorrências.
`node --check` limpo; só `agent-hub.service` reiniciado.
