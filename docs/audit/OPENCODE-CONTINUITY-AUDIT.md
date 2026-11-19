# OPENCODE-CONTINUITY-AUDIT — DB, plugins, rehydrate, checkpoint (Fase 4)

> Medido em 2026-11-19 com conexão SQLite `mode=ro` em
> `~/.local/share/opencode/opencode.db` (1,9 GB). Nenhuma escrita no DB.
> Re-medido 19/11 (retomada 14): 33 tabelas no total; contagens abaixo são
> um retrato, crescem enquanto o host trabalha (`session_v2` 1.183,
> `session_message` 115.435 na segunda leitura).

## 1. Schema real (V2)
| tabela | linhas | papel |
|---|---:|---|
| `session` | 723 | sessões tituladas (2026-08→11) |
| `session_v2` | 1.182 | sessões V2 |
| `session_message` | 114.820 | conteúdo DENTRO de `data` (V2 ativo) |
| `message` (V1 congelado) | 93.465 | schema antigo — não usar |
| `part` (V1) | 346.044 | `tool`, `text`, `step-start`, `reasoning`, `step-finish`, `patch` |
| `session_part` (V2) | **0** | não usado; partes vivem em `session_message.data.content` |
| `event` | 151.018 | eventos agregados |
| `todo` | 132 | tarefas por sessão |
| `session_inbox` | 0 | fila V2 (sem mensagens pendentes no momento) |

Tipos em `session_message`: `assistant` 98.835, `user` 11.794, `idle` 1.650,
`model-switched` 1.281, `system` 520, `synthetic` 453, `compaction` 260,
`agent-switched` 27. Chaves do assistant: `time, agent, model, content, cost,
tokens, snapshot, finish, error`.

## 2. Captura de ferramentas (verificado)
- **90.440 mensagens assistant contêm referências a tool**; `content` traz
  itens `reasoning` e `tool`. Logo tool calls **são preservados** no V2.
- `part` (V1) mantém os tipos granulares; `session_part` (V2) está vazio —
  consumidores que leem `session_part` não veem nada.
- Arquivos históricos em `storage/` não são o DB ativo (regra da missão).

## 3. Continuidade / rehydrate
- `jarvis_rehydrate` existe em `mcp_server.py` (`_handle_rehydrate`) e está no
  **hidden catalog** (`_META_TOOLS`/lista em `:805`) — economia de contexto,
  coerente com RCR-Router. Verificado via `tools_call`: `isError: False`,
  devolve GUARDS + estado do projeto.
- No celular, o meta-tool `mcp` cobre apenas `coord`/`knowledge` — use
  `~/bin/ta-state` como equivalente local.
- Regras pinadas injetadas pelo plugin: primeira tool = rehydrate; claim antes
  de escrever; `agent-msg.sh` para entrega; `remember` ao final da tarefa.

## 4. Compaction (P1 medido)
260 registros `compaction`, **27 degenerados** (<300 chars, 5 com 0), piorando
em nov/2026. Guard `summaryIsDegenerate()`+`fallbackSummary()` portado para o
host (`57c91765`) **avisa** na re-injeção mas não substitui o resumo do core.
Correção real: `agents.compaction.model` (minimax) já configurado desde 15/11.

## 5. Checkpoint de missão (criado nesta sessão)
`docs/audit/PROJECT-AUDIT-STATE.md` + `PROJECT-AUDIT-LOG.md` (append-only).
Protocolo de retomada: ler AGENTS.md → state → log → rehydrate → roster → git.
Checkpoint associa HEAD, fase, arquivos, testes, pendências e riscos.

## 6. Riscos
- `git add -A` proibido: 42 alterações não commitadas (`.bak` + trabalho de outros).
- Worktrees: `.worktrees/coord-mcp` ativo; `/tmp/ack-patch-wt` prunable.
- Agentes ativos (Falcao/Cervo/Lince): verificar claim antes de editar.
- Tailnet oscila quando duas VPNs ligam no Android.
