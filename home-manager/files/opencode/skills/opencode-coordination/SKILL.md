---
name: opencode-coordination
description: "Coordenar com OUTRO agente opencode desta máquina (roster, claim de lane, entrega por API, wake). Use quando precisar falar com um colega agente, dividir/claimar trabalho, não colidir em arquivos, entregar nota sem rodar o alvo, cancelar o turno de alguém, ou reidratar a sessão (1ª tool = jarvis_rehydrate). Triggers: colega, outro agente, multi-agente, coordination, roster, claim, lane, wake, rehydrate, memoire."
license: MIT
---

# Coordenação multi-agente (nixos-ai, 02/11)

## 0. Primeira tool da sessão (regra do harness)

`jarvis_rehydrate(task="<o que vou fazer>")` — devolve em **1 call**: guardas
+ fila (topo) + HANDOFF + memórias + lições + RAG + roster. É o resgate: sem
isso o agente repete diagnóstico já pago (a regra existe porque o RAG era
usado só para *registrar*, nunca para *resgatar* — 2607.08032: memória
reversível > resumo; 2608.22752: 5 compactações derrubam regras de 53%→10%).

## 1. Roster = quem existe (fonte única)

`scripts/agent-roster.py` (estado em `~/projects/.agents/roster.json`):

```bash
scripts/agent-roster.py claim --name <n> --lane "<repo/area>" --repo <repo> --files "<glob1,glob2>"
scripts/agent-roster.py list          # live/stale/dead + lanes + tasks
scripts/agent-roster.py release --name <n>
scripts/agent-roster.py task add --title "..." --owner <n>
```

- **claim antes de falar** (sem claim você não é endereçável).
- 2 claims com **arquivos sobrepostos** são recusados (fronteira explícita →
  sem trabalho duplicado). `--force` só com intenção declarada.
- Mesma lane com arquivos disjuntos é OK (2 janelas, 1 assunto).

## 2. Entrega (API do opencode — nunca wtype/focus)

`scripts/agent-msg.sh` entrega **na sessão do alvo** (`POST /session/:id/message`):

```bash
scripts/agent-msg.sh --to <nome> "texto"      # PEDIDO: o alvo roda (prompt_async)
scripts/agent-msg.sh --note "texto"            # NOTA: entra na sessão, NÃO roda (noReply) — zero token
scripts/agent-msg.sh --cancel <id>             # aborta o turno do alvo (POST /session/:id/abort)
scripts/agent-msg.sh --list                    # dry-run: alvos, sessão, ocupado?
scripts/agent-msg.sh --pending                 # pedidos sem resposta
```

Regras:
- `--note` = notificação (não dispara run). **Nunca** "deixar texto na caixa
  de input": bloqueia o typing do humano e não entra na fila (erro real).
- Sem roster, `--to other` **não envia nada**; broadcast só com `--broadcast`
  explícito (custa ~15x tokens por multi-agente — Anthropic 06/2025).
- 1 LINHA por mensagem; cada envio loga em `~/projects/AGENTS-MSG.log`.

## 3. Wake (o watcher acorda o dono do repo)

`scripts/agents-watcher.sh`: wake **via API** (não rouba foco) e **lane-aware**
— commit do repo X só acorda o agente cujo `repo`/lane é X; fila/hooks são
globais; sem roster = legado global.

## 4. Quando um erro se repete (o tropeço)

1. `jarvis_rehydrate(task="<erro>")` — a lição pode já estar lá.
2. `jarvis_lessons("<padrão do erro>")` se a lição não aparecer.
3. Ao consertar: `jarvis_remember(text=..., category="decision"|"error")` +
   `agent-pains.sh scan-apply` (o scanner pega o erro sozinho).

## 5. Fila e HANDOFF (estado compartilhado)

- `~/projects/AGENTS-QUEUE.md`: o topo é o estado **real** (missão atual).
  Atualize por **delta** no topo, nunca reescreva o histórico (ACE 2510.04618:
  playbook evolui por patch; reescrita monolítica degrada).
- Vault: `HANDOFF-<data>-<slug>.md` (ponteiro de retomada) — `jarvis_vault_list`.

## 6. Papers que fundamentam (RAG `books`, ~/Books/papers)

2607.08032 (reversível > resumo) · 2608.22752 (compactação quebra regras) ·
2609.40118 (query-conditioned) · 2609.28771 (retrieval por feature) ·
2510.05381 (contexto longo fere) · 2602.11988 (AGENTS.md inflado = custo) ·
2601.20404 (AGENTS.md mínimo = −28% runtime) · 2510.04618 (deltas) ·
A2A v1.0 (roteamento determinístico, messageId, tasks/cancel).
Síntese: `nixos-ai/docs/REHYDRATACAO-E-COORDENACAO.md`.
