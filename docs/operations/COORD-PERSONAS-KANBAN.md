# COORD, PERSONAS, KANBAN, TELEGRAM — estado consolidado (12/11/2026)

Inventário do que está **vivo** no nixos-ai, como as ideias do legado
(`~/projects/team`, `team-suite`) foram absorvidas, lacunas e como operar
(com pesquisa: MBTI/local LLMs, Grok Bot, Meta Muse).

## 1. Sistema vivo (uma fila, um bus)

| Necessidade | Peça viva | Onde |
|---|---|---|
| Identidade (quem é, de onde vem, em que sistema roda, com que modelo) | Roster = Agent Card: nome, codinome, origem (host/os/arch), modelo, MBTI/persona, lane, repo, arquivos, contexto, sessão | `scripts/agent-roster.py`, `modules/ai/jarvis/src/jarvis/core/coord_roster.py`, MCP `jarvis_coord_roster`/`jarvis_coord_whoami`/`jarvis_coord_set_context` |
| Coordenação e mensagens (cross-machine, auditável) | Bus GitHub `coord-json` (append-only) + wake local | `modules/ai/jarvis/src/jarvis/core/coord.py`, `scripts/agent-msg.sh` + `scripts/agent-api.py`, MCP `coord_post/read/check/msg/pending`, watcher `scripts/agents-watcher.sh` |
| Kanban (claim/status da tarefa) | `nightwatch.task_queue.TaskQueue` por projeto (DISCOVERED→READY→IN_PROGRESS→VALIDATING→REVIEW→COMPLETED/BLOCKED/FAILED) | CLI `jarvis workitem ...`, MCP `coord_workitem` (`list|create|claim|done|blocked|next|burndown`), estado em `~/.local/state/jarvis/nightwatch/` |
| Lista leve A2A (compartilhada, git-friendly) | `agent-roster.py task add/close/list` em `.agents/roster.json` | `scripts/agent-roster.py task` (útil para tarefas curtas entre pares; para execução/harness use `workitem`) |
| Persona/MBTI por tarefa (fluido) | `core/team.py`: classifica tarefa → (MBTI, persona, motivo) + sugere modelo | `jarvis.core.team.{persona_for_task,assign,assign_text}`, Telegram `/assign` (e `/plano`), seleção de modelo cooldown-aware |
| Telegram (dono no celular) | Bot JARVIS: comandos, `/board`/`/quadro`, `/assign`, notificações; `coord_notify` envia | `modules/ai/jarvis/src/jarvis/providers/telegram.py`, `modules/services/jarvis-telegram.nix`, MCP `coord_notify` |
| Quadro/estado | Claims ativas + agentes vivos + colisões + pendências acionáveis | `comms.board/board_text`, Telegram `/board`, `coord_read`, `coord_pending`, `night-comms` |
| Despertar/keepalive | Watcher acorda por evento da fila/bus; keepawake segura tela; night-comms entrega pendências à noite | `scripts/agents-watcher.sh`, `scripts/agent-keepalive.sh`, `scripts/night-comms.py` |

**Regra vigente (comms.py):** fila única é o bus; sem kanban paralelo de
mensagens. O kanban de execução é o `task_queue` (workitem).

## 2. O que o legado (`team/`, team-suite) virou

| Legado | Absorvido como | Status |
|---|---|---|
| `team/queue.md` + `MEMORY.md` (kanban markdown) | `AGENTS-QUEUE.md` + bus/claims + memórias/RAG/vault | scripts em `~/projects/team/` mantidos, timers soltos em quarentena `~/.local/state/jarvis/legacy-units-2026-11-12/` |
| `suite-bot`/`drift-bot`/`coord.sh` por timer | `night-comms`, `agents-watcher`, checks opt-in por repo | não deletado, desabilitado |
| `tg.sh` + tokens por persona | Telegram do JARVIS + `coord_notify` | consolidado |
| `roles/` + codinomes ad-hoc | roster (codinome determinístico por modelo, claim com origem/modelo/MBTI/contexto) + `team.py` (MBTI por tarefa) | vivo |

## 3. Acesso móvel (Termux / opencode no celular) e confiança

- `opencode serve` expõe a sessão no tailnet: `http://100.121.100.103:4599`
  (`nixos-ai/home-manager/modules/services/opencode-serve.nix`) — o celular
  assume a mesma sessão em vez de abrir outra.
- MCP de coordenação no tailnet: `coord-mcp` em `:8765/mcp` (e conhecimento em
  `:8766`) — uma lane em outra máquina aponta para ele e usa `coord_*` sem
  reimplementar.
- SSH/chaves: relação de confiança do dono (chaves já provisionadas). Para
  acesso direto, usar SSH pelo tailnet para o host; para o agente do celular,
  tratar como outra origem (o roster/bus já distinguem `termux` via
  `host.kind`). O sdcard do Termux pode ter estado de sessão local; o bus é a
  verdade compartilhada.
- **Regra de saúde:** nunca afirmar serviço de pé pelo PID — teste a porta
  (`/tcp/host/port` ou o endpoint de health correto). O health do nv-gate é
  `GET /__gate/health` (não `/health`).

## 4. Pesquisa aplicada (o que medir e o que adotar)

- **MBTI em LLMs (útil, mas com limite):** priming produz desvios
  reproduzíveis e alinhamento tarefa×personalidade melhora execução em tarefas
  adequadas (MBTI-in-Thoughts arXiv:2509.04343; Personality-Guided Code
  Generation arXiv:2411.00006, ganho médio pequeno mas real e maior em alguns
  cenários). Em modelos abertos/pequenos o traço é mais frágil e
  "in-context" (AAAI 2025 "Open Models, Closed Minds?"); adaptação
  estruturada (arXiv:2601.10025, JPAF) sugere persona base + compensação pela
  tarefa. **Adoção aqui:** MBTI é *papel por tarefa* (fluido), não identidade
  fixa; serve para moldar framing/comunicação e divisão de trabalho, e deve
  ser validado por tarefa (não assumido como ganho universal).
- **Multi-agente tem custo:** sem objetivo e fronteira explícita duplica
  trabalho e custa muito mais tokens (Anthropic 2025; "Collaboration Tax"
  arXiv:2608.22152 mostra perda de coordenação em tarefas que já eram
  solo-tractable). **Adoção:** fronteira de arquivos no claim, wake raro e
  dirigido, fila única.
- **Grok Bot (xAI, 2026):** bots persistentes com computador próprio na nuvem,
  identidade/memória, trabalho em paralelo, handoff entre bots, rotinas/skills,
  aprovação para ações sensíveis. **Mapeamento:** nosso "computador próprio"
  é a sessão + host declarado no roster/bus; handoff e claim vivem no bus;
  aprovação e segurança já têm guardas (gates, never auto-push, porta/segredo
  no coord_http). Ganho a perseguir: handoffs e skills mais explícitos no
  quadro.
- **Meta Muse (2026):** agente pessoal com VM isolada, identidade de operação,
  subagentes/coordenação multi-agente, memória com controle, canal seguro e
  ações mediadas (sentinel/aprovação). **Mapeamento:** isolamento e
  credenciais já são princípio (sem segredo no repo, env fora do repo, MCP com
  auth a endurecer); subagentes/coordenação via bus+workitem; registrar
  "quem fez o quê" no claim/handoff continua sendo a trilha auditável.

## 5. Como operar (mínimo)

1. **Identifique-se antes de agir:** `python3 nixos-ai/scripts/agent-roster.py claim --name <nome> --lane <lane> --repo <repo> --files "<globs>" --model <provider/id> --context "<1 frase>" --task "<tarefa atual>"` (o claim sugere e preenche `--mbti/--persona` pela tarefa via `team.persona_for_task/assign` quando não informados; você pode sobrescrever com `--mbti <TIPO> --persona <id>`). Atualize com `set-context`/re-claim quando o contexto mudar. Informe origem/sistema no cartão (o claim grava `host/origin`).
2. **Pegue trabalho pelo kanban:** `coord_workitem` (MCP) ou `jarvis workitem --project <p> list|next|claim|done` para tarefas de execução; `agent-roster.py task` para tarefas leves compartilhadas. No Telegram: `/work [projeto]`, `/work stats|next`, `/work <id>`.
3. **Comunique pelo bus:** `coord_msg`/`send_message` (grava no bus + wake local). Telegram `/board`, `/pending <agente>` ou `/assign <tarefa>` para ver quadro e plano MBTI+modelo.
4. **No celular/Termux:** use a sessão via `opencode serve` no tailnet ou SSH com chave; declare origem `termux` e siga o mesmo protocolo (ver `docs/operations/TERMUX-MOBILE-ONBOARDING.md`).

### MBTI end-to-end (seguro)

- **Sugestão por tarefa (papel fluido):** `/assign <tarefa>` (Telegram) ou `jarvis.core.team.assign_text/persona_for_task` devolve `tipo`, `MBTI`, `persona` e modelo sugerido. A personalidade acompanha o tipo da tarefa (debug, arquitetura, pesquisa, coord, docs, operação, criação), não é identidade fixa.
- **Registrar no claim/roster:** `scripts/agent-roster.py claim --task "<tarefa>"` preenche MBTI/persona faltantes (só metadado de coordenação). Isso não altera o comportamento da sessão por si só.
- **Aplicar framing na sessão (opcional, com cautela):** o estado ativo de persona (`/mood <id>` no Telegram, `jarvis_persona`/estado em `~/.local/state/jarvis/persona.json`) entra no system prompt via plugin/harness. É estado global: mude conscientemente e evite assumir ganho sem evidência em modelos locais pequenos (medir A/B por tipo de tarefa antes de generalizar). Para limpar: `/mood off`/`clear_active_persona`.
- **Confirmação prática:** cheque roster/`whoami` (MBTI/persona registrados), board/Telegram (`/assign`, `/work`) e, se aplicou persona ativa, valide que o framing esperado está em vigor sem degradar a tarefa.

## 6. Próximos passos (medidos, não assumidos)

- Medir se `jarvis-sessions-index` cobre o que `jarvis-consolidate` faz antes de fundir.
- Tornar `coord_workitem`/task_queue a visão única no Telegram (comando de fila) e expor MBTI sugerido no fluxo de claim.
- Endurecer auth do `coord_http` (já auditado: hoje mais aberto que deveria no tailnet) — identidade atada ao chamador.
- Validar ganho de MBTI em tarefas reais com modelos locais pequenos (A/B por tipo de tarefa) antes de generalizar.

## 7. Proposta: hardening de `coord_http` (sem quebrar lanes remotas)

> Estado atual (auditado): `coord_http` responde no tailnet (`:8765/mcp`) com proteção principalmente de rede (Tailscale ACL) e, em alguns fluxos, sem identidade forte atada ao chamador. Endurecer é necessário, mas migração precisa ser compatível com Windows/Termux.

**Princípios**

- Fail-closed para novos clientes autenticados, mas com janela de compatibilidade para clientes legados conhecidos (não derrubar Termux/Windows).
- Identidade do chamador verificável (token/credencial por agente ou por origem) e auditável no bus/roster; não confiar só em campos do payload.
- Defesa em profundidade: ACL do Tailscale continua, não vira única barreira.

**Plano de migração seguro (sugerido)**

1. **Inventariar consumidores:** listar quem usa `:8765/mcp` hoje (Termux, Windows, scripts locais, watchers) e como autentica (headers, IP, sem auth).
2. **Introduzir auth opcional com telemetria:** aceitar credencial quando enviada, registrar origem/identidade e marcar chamadas "legacy" sem bloquear ainda; medir por alguns dias.
3. **Distribuir segredos por agente/origem:** segredo compartilhado inicial (mínimo) ou bearer por agente, armazenado fora do repo (env/secret store do host), com rotação possível sem rebuild do mundo.
4. **Modo compatível + prazo:** habilitar exigência de auth por allowlist de origem/agente primeiro; manter bypass temporário só para clientes legados mapeados, com data de corte conhecida.
5. **Fail-closed por padrão:** após migração, rejeitar chamadas sem identidade válida; manter exceção explícita e documentada apenas se houver cliente que não pode ser atualizado (último recurso).
6. **Testes antes de virar chave:** handshake + `tools/list` + `tools/call` (ex.: `coord_roster`, `coord_workitem`) a partir de Linux, Windows e Termux; confirmar que wake/board/pendências continuam funcionando.

**Critério de aceite**

- Windows e Termux continuam operando com credencial configurada.
- Chamadas sem credencial válida são rejeitadas e auditadas.
- `coord_pending`/inbox continuam protegidos contra spoofing de identidade (resolver identidade pelo chamador, não pelo payload).
