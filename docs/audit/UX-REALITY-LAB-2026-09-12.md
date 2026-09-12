# NIGHT SHIFT — Reality Lab: relatório parcial (madrugada 2026-09-12)

> Evidência executável, não afirmações. Transcripts em /tmp/ux-*.json.

## BASELINE (driver PTY + `jarvis dev`, bonsai, suite 8 tasks)

- 7/8 success. Mundo verificado externamente (arquivo existe+conteúdo).
- Ferramentas: `scripts/ux_driver.py` (PTY, timeout duro, auto-resposta
  de aprovação registrada, transcript JSON) + `scripts/ux-suite.py`.

## REAL USER PATH

`jarvis dev "tarefa" --transcript` → dev_once → _run_agent_loop
(próprio, NÃO o core Agent) → LLMClient bonsai → tools → observation.
`ask` = roteador fastpath; `agent` = core Agent separado. Dois loops
distintos confirmados (convergência pendente, §26/§31 da missão).

## CADEIA OS PROVADA (critério D: OK)

`cria pasta + 3 arquivos`: list → error → mkdir (deny policy) →
... → com aprovação respondida: execute_shell mkdir+touch, rc 0.
LLM→OS→observation→next decision FUNCIONA quando a policy deixa.

## FALHAS REAIS (transcripts preservados)

- **F1 (P0, interface falsa)**: "vou criar a pasta..." sem tool call,
  loop encerra rc=0, nada feito. FIX: promise-catcher (nudge, max 2)
  + `_looks_like_promise` (PT/EN). Status: implementado, T3 ainda
  falha por F5 (abaixo) — retestar após F5.
- **F2 (P0)**: write_file em path de diretório criava ARQUIVO com
  nomes como conteúdo + "✓ OK". FIX: recusa com hint + cria pais
  (devtools.py). Regression tests verdes.
- **F3 (P1)**: mensagem de sucesso dizia "substituição(ões)" para
  write_file. FIX: branch por tool name.
- **F4 (P1)**: prompt de aprovação trava PTY para sempre sem humano.
  FIX (driver): auto-resposta registrada (métrica approvals).
- **F5 (P0, tool selection)**: mkdir/touch negados pelo allowlist;
  modelo não descobre write_file-completo. MITIGAÇÃO: descrição
  das tools ensina o caminho. T3 segue aberto (tarefa ambígua sem
  nomes — clarificação impossível em dev_once; UNVERIFIED parcial).
- **F6 (P0, imaginação)**: browser open OK (B1: título certo,
  tool escolhida sozinha); B2 (clica e diz o que mudou): modelo NÃO
  tentou click e alucinou mudança ("texto do botão mudou").
  HIPÓTESE: menção "pedem aprovação" desincentiva; ou limite do
  modelo. TESTE PENDENTE: mesmo task no Qwen (A/B justo, §17).

## BROWSER (critério E: parcial)

- Infra: `core/browser.py` (Playwright + chromium do sistema;
  ms-playwright NÃO roda no NixOS), tool `browser` no loop dev
  (open livre, click/fill com aprovação), site lab :8931
  (título/botão/campo/estado dinâmico). Cadeia unitária open→click
  →fill→click OK. B1 user-faithful OK. B2 falha (F6). B3 pendente.
- Playwright adicionado ao devShell do flake (declarativo).

## ROUTER MODE (achado operacional)

:8080 agora opera em modo router (`--models-preset`, max 1,
model id "bonsai"). Modelo descarrega em idle → primeira chamada
paga load (minutos; estourou timeout de 300s 2×). Warmup/boot ou
timeout de primeira chamada pendente (Nix + rebuild, com usuário).

## NÃO PROVADO (UNVERIFIED/BLOCKED)

- A/B Qwen (não mexer no :8080 produtivo de madrugada).
- B3 (fill+confirm), recovery com restart/crash (§27-28).
- WebUI via Playwright (§25). Testemunho Roo-vs-JARVIS (§29).

## PRÓXIMO EXPERIMENTO DE MAIOR VALOR

A/B B2 no Qwen (mesmo driver, mesma task) → decide se F6 é
harness (descrição/aprovação) ou modelo. Depois: F1-retest T3.

## BATERIA FINAL (00:40, bonsai, driver+aprovação+fixes)

- 11/12, mean 2.2 turns, mean 3.8s, p95 5.7s, false_done 1 (só T3).
- B2/B3 com verificação SERVIDOR independente (/state): clicks e
  fills registrados fora do browser do modelo. Critério E: OK.
- T3 0/5 determinístico no modo de falha (arquivo-no-lugar-da-pasta
  ou promessa). Tarefa ambígua sem nomes + sem mkdir tool = limite
  arquitetural, não estocástico.
- F6 resolvido: causa = approval (click exigia flag, modelo ou
  alucinava ou mendigava). Fix: Confirm.ask interativo no REPL.
  Qwen A/B: NÃO executado (Qwen-CPU não serve o prompt gigante do
  dev; GPU exigiria mexer no :8080 à noite). UNVERIFIED c/ motivo.
- Router: descarrega em idle; primeira chamada paga minutos.
  TODO declarativo (warmup/timeout) documentado, sem execução.
- World-state: scripts/ux_world.py (filesystem + /state servidor).
  NÃO é tool do modelo (benchmark-side).
- Suite: scripts/ux-suite.py (T1-T9, B1-B3) + ux_driver.py
  (aprovação auto-respondida e registrada).
