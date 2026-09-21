# CYCLE-9 PLAN — Harbor external calibration (21/09)

## §1 Estado (código confirmado)
CURRENT_COMMIT 9769fd4 (+ciclo 8) · branch main, ahead 6, tree limpo.
INTERNAL_SUITE 1431/0 · L8 WORLD OK (hard) · L9 0/12 (congelada).
MODEL_CURRENT bonsai (router :8080 default, `models.nix:routing`).
HARNESS_CURRENT Agent+EvalHarness+world_check. Bonsai_ENDPOINT :8080 ok.

## §2 Harbor: BLOCKED (gap exato)
- `harbor`: ausente. `uv`: ausente. Repo/sistema: zero referências.
- docker client 29.6.2 ok, mas **daemon: permission denied**
  (socket inacessível p/ este usuário; docker-group é do dono).
- Sem daemon não há container Terminal-Bench → células C/D e A/B-em-
  Harbor **NOT AVAILABLE**. Declarativo via nix: sem pacote Harbor.
- Caminho: dono libera docker ou host Harbor; adapter mínimo = Harbor
  pip + backend OpenAI-compatível apontando :8080 (Bonsai) / OR (API).
  Nenhuma instalação feita (regra §15).

## §4 Experimento executável (sem Harbor): A-vs-B análogo
Mesmo harness (EvalHarness+world_check), mesmas tasks, mesmos limites;
só o modelo muda (paridade §6). Células C/D: NOT INTEGRATED.
- Tasks (verifier determinístico, relação c/ ciclos):
  T-fact: número GCD 181 c/ chunk (Bonsai C2 5/5, C0 0/5).
  T-count: chain WARN/32/verdade 8 (B0 4/5, B3 3/3).
  T-r8: R8-shape bytes exatos (Bonsai 0/3).
- n=3/braço (limitação registrada se custo impedir).
- API referência: `google/gemini-2.5-flash` via OpenRouter
  (RemoteBackend existente, sem mudar harness). Prompts mínimos.
- Métricas §8, falhas §9, transfer §10, manifest §14 em
  `docs/audit/cycle-9/`.
- Tuning: NENHUM (§7). Verifier externo = autoridade (§17).

## Ordem lógica (caminho natural)
§1 estado → §2 disponibilidade → §4 plano → runner A-vs-B → matriz →
falhas → transferência → REPORT → STOP (§20, sem melhorar Bonsai).
Backlog ciclos 1-8 auditado: todos os todos cumpridos; restam
DEFERRED (L10+, E6-threshold, compiler, M3/M4, finetune/Qwen/MoE) e
OPEN (approval_callback morto, R8-shape permanente, kb weekly,
lint-comportamental). Nada disso bloqueia a calibração.
