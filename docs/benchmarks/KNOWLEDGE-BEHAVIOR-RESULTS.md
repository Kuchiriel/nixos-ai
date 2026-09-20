# KNOWLEDGE → BEHAVIOR — resultados (campanha 20/09)

Padrão por experimento (§60): Task, Baseline, condição, Retrieval,
Behavior, custo, Interpretation. Modelo: bonsai via :8080 salvo menção.
Runner: `EvalHarness.compare` semântica (n=3/braço), world_check externo.

## EXP-A — RAG causality (presentation → action) ✅ CAUSAL

- Task: "per the NVIDIA GCD-bash arena study (13 models), how many
  transition pairs were REGRESSIONS where grammar fought model bias?
  Write ONLY that integer as entire content of answer.txt" (fato do
  digest `~/Books/harness/nvidia-gcd-bash-small-models.md`, posterior ao
  cutoff — impossível por pesos; retrieval-hit simulado por injeção
  direta do chunk, qualidade de retrieval medida à parte em eval_rag).
- Baseline C0 (sem conhecimento): **0/3 world_ok** (turns 4,2,2).
  Respostas: `12345`, `42` (copiou o exemplo do prompt!), `13` (nº de
  modelos do enunciado) — alucinação sem grounding.
- Controle negativo C1 (chunk irrelevante, ASCII codes): **0/3**
  (turns 2,2,2). Respostas: `13`,`13`,`13` — distrator não ajuda; modelo
  agarra o único número do enunciado. Retrieval irrelevante ≠ crédito.
- Targeted C2 (chunk com o fato): **3/3 world_ok** (turns 2,2,2,
  1 tool cada). Respostas: `181` ×3 exato.
- Custo de contexto: +~120 tokens no prompt (chunk 3 linhas).
- Interpretation: evidência causal de contribuição comportamental do
  conhecimento entregue — mesmo modelo, task, tools, mundo; só o
  conhecimento mudou. Efeito: tool-selection/write correto 0/3→3/3.
- Armadilhas encontradas: (1) `approval_callback=` do Agent é parâmetro
  MORTO (nunca chamado; approval real = `human_approve` de módulo —
  wore finding §47); (2) exemplo numérico no enunciado (`e.g. 181`)
  contaminou C0 numa rodada (copiou) — exemplos devem ser neutros
  (`e.g. 42`); (3) primeira rodada C0 3/3 porque o fato 62.5% estava nos
  pesos — fatos pós-cutoff/autorais são necessários p/ headroom.
- Runner: `/tmp/exp-a/run_exp_a.py`; resultados:
  `/tmp/exp-a/exp-a-rag-causality.jsonl` + `summary.json`.
- Status: VERIFIED (n=3/braço; replicar n=5 antes de fechar dimensão).

## EXP-C — lesson causality (retrieval+behavior half) ⚠️ LESSONS CAN HURT

- Task: read data.txt, count lines with WORD, write ONLY the number.
  Variant A (ERR/30 lines/truth 10) → Phase 1 genuine failure
  (success=False, wrote 3, 6 turns). Lesson built programmatically from
  observed wrong-vs-truth (no hand-written content).
- B0 (no memory) variant B (WARN/32/truth 8): **3/3** (5,5,5 turns).
- B2 (lesson WITH Phase-A numbers "counted 30…as 3 but truth 10"):
  **1/3** — failures = read×3 + stray str_replace, never write_file
  (over-verification loop, turns burned, no output file).
- B3 (VALUE-FREE lesson, same advice, zero episodic numbers): **3/3**
  (7,8,6 turns). Isolada a variável: só o conteúdo da lesson mudou.
- Interpretation (§62): delivery funciona (retrieval ✓, injeção altera
  comportamento ✓) mas lesson com valores episódicos PREJUDICA modelo
  pequeno (atração por números / perturbação — mesmo padrão do C1 no
  EXP-A). REGRA DE QUALIDADE (§15): lessons value-free (condição, causa,
  sinal, alternativa, escopo; sem números do episódio). B0 3/3 também
  mostra: sem headroom não há efeito a medir (teto, não falha da lesson).
- Limitation: creation-half assistida (Agent só auto-lembra falhas de
  shell exit!=0 — achado: criação de lesson NÃO é sistemática).
- Runners: `/tmp/exp-c/run_exp_c2.py`, B3 inline; resultados
  `/tmp/exp-c2/*.jsonl`, `/tmp/exp-c3/`; coleções isoladas
  `exp_c2_lessons`, `exp_c3_lessons` (compartilhada `memories` intacta).
- Status: PARTIALLY VERIFIED (n=3/braço; efeito adverso replicado B2 vs
  B3 em mesma variante — mecanismo confirmado).
