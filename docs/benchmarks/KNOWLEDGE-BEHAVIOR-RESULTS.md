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

## EXP-E — MCP tool selection (description discriminability) ⚠️ CONFUSÃO SISTEMÁTICA

- Método: probes single-turn (LLMClient, bonsai :8080), catálogo real de
  12 tools (nomes+descrições verbatim de `mcp_server.JARVIS_TOOLS`),
  resposta constrangida ao nome exato; n=3/task, 6 tasks.
- rag_search 3/3, lessons 3/3, web_search 3/3, read_file 3/3.
- **recall 0/3**: escolhe `jarvis_lessons` 3/3 ("what did we decide" →
  lessons). Descrição do recall ("recall past facts/decisions") perde
  para lessons ("recall lessons from past failures FIRST") — par de
  confusão SISTEMÁTICO, não ruído.
- **nix_search 0/3**: responde "jq" (o conteúdo, não a tool) 3/3 —
  violação de constrangimento quando a task parece pergunta direta.
- Total 12/18. Interpretation: verbos distintivos vencem; superfícies
  sobrepostas (recall/lessons) confundem; modelo pequeno troca seleção
  de tool por resposta direta quando o formato da pergunta sugere.
- Implicação (§12): "MANDATORY FIRST STEP" do recall é prosa que o
  próprio modelo não consegue operacionalizar na seleção — advisory,
  não enforcement. Candidata a REGRESSION-PLAN: desambiguar descrições
  recall vs lessons (recall=fatos/decisões gerais; lessons=falhas).
- Runner: `/tmp/exp-e/run_exp_e.py`; `/tmp/exp-e-summary.json`.
- Status: PARTIALLY VERIFIED (n=3; confusão recall→lessons replicada 3/3).

## EXP-D — substrate selection (probe-form) ⚠️ PARCIAL

- Método: mesmo probe single-turn do EXP-E; 6 tasks diferenciadas por
  substrato; n=3.
- recall 3/3 ("previous execution" → recall ✓ — notar: EXP-E "decide"
  falhou; a confusão recall↔lessons depende do verbo), lessons 3/3,
  rag_search 3/3, read_file-filesystem 3/3.
- **vault 0/3** → read_file 3/3 ("stable policy" → ler arquivo; AMBÍGUO:
  a policy mora em .md legíveis — falha do desenho da task tanto quanto
  do modelo; vault como superfície distinta não se justifica aqui).
- **git 0/3** → read_file 3/3 ("recent commit" → read_file, que NÃO
  responde; read-first bias, evita shell mesmo quando incapaz).
- Total 12/18. Interpretation: seleção funciona quando o verbo casa
  (execution→recall, rule→lessons, paper→RAG); falha em superfícies sem
  verbo próprio (vault, git-história). Implicação: ou vault ganha verbo
  ("stable policy" nas descrições) ou assume-se filesystem como verdade
  p/ policy (RAG-discovery + filesystem-truth, §31).
- Runner: `/tmp/exp-d-run.py`; `/tmp/exp-d-summary.json`.
- Status: PARTIALLY VERIFIED.

## EXP-E2/D2 — attribution by tool restriction ✅ ENTROPY, NOT CAPABILITY

- recall ("previous execution"): E1-all 3/3, E2-only 3/3, E3-pair 3/3 —
  confusão do EXP-E ("decide"→lessons) é verbo-dependente, não
  incapacidade geral.
- execute (git): E1 0/3 → E2-only 3/3 → E3-pair(+read_file) 0/3.
- vault (policy): E1 0/3 → E2-only 3/3 → E3-pair 3/3.
- Interpretation (§37): com a tool correta isolada o modelo SEMPRE
  seleciona certo (9/9 E2); com read_file no menu ele SEMPRE prefere
  read_file (0/6 E1/E3 git). Falha = entropia de escolha
  (MCP presentation), NÃO incapacidade. Restrição/divulgação
  progressiva é alavanca arquitetural real. R5/R6: E6 (progressive
  disclosure) passa a ser o próximo teste, não mais prosa.
- Runner: `/tmp/exp-e2-run.py`; `/tmp/exp-e2-summary.json`. n=3/célula.
- Status: STRONG EVIDENCE (replicado em 2 substratos: git e vault).

## R1 — EXP-A replication n=5 + generalization (2 new docs) ✅ STRONG

- T1 replicate (181): C0 **0/5**, C1 **0/5**, C2 **5/5** (turns 2 sempre).
  C0 outputs: 42,13,13,42,42 (exemplo + nº-modelos — mesmas classes).
- T2 (not-the-size, VCR 0.625, decimal): C0 0/3, C2 3/3.
- T3 (judge digest, count=5, small-int): C0 0/3 (turns 5,6,5 — tenta e
  erra), C2 3/3 (turns 2).
- Total: C2 11/11, controles 0/16, 3 docs × 3 formulações × 3 formatos.
  Interpretation: efeito arquitetural (retrieval→behavior), não
  memorização de benchmark. Confiança: STRONG EVIDENCE.
- Runner: `/tmp/exp-r1/run_r1.py`; `/tmp/exp-r1/r1-replication.jsonl`.
- Status: VERIFIED (replicado n=5 + generalizado 2 tasks).

## R2 — lesson representation ablation ✅ MECANISMO CONFIRMADO

Variant B (WARN/32/truth 8), bonsai, n=3 (B2/B0 estendidos a n=5):
- B0 no-lesson: **4/5** (3/3 + 1/2; baseline wobble: um 5).
- B2 values-lesson: **1/5** (1/3 + 0/2; ambos extras escreveram 10).
- L3 compressed value-free ("count exactly"): 1/3.
- L4 scoped values ("PAST EPISODE ONLY... truth was 10"): 1/3 —
  escreveu **10 duas vezes**: o rótulo NÃO neutraliza a atração.
- L5 rule form ("RULE: output = ... enumeration"): 2/3.
- Ranking: value-free (B3 3/3) > rule 2/3 > compressed/scoped/values
  1/3 ≈ values-lesson 1/5.
- Hipóteses: H-C8 (valores históricos lidos como atuais) SUPPORTED;
  H-C3 (verbosidade) REJECTED (L3 curta falha igual); H-C10 (variância)
  presente mas separação B2×B3 é larga (1/5 vs 3/3); H-C9 (representação
  nociva) SUPPORTED. L6 respondida por leitura: handlers MCP chamam os
  mesmos métodos EpisodicMemory (path-equivalente por código).
- REGRA (§15, regression R4): lessons sem números episódicos.
- Runner: `/tmp/exp-r2/run_r2.py`; coleção `exp_r2_lessons`.
- Status: STRONG EVIDENCE (preliminary-strong, n≤5 — sem teatro).

## EXP-F — context ablation (chain-D FAIL/40/truth 8) ⚠️ MORE ≠ BETTER

- F0 bare: **0/3** — escreveu 4,4,4 (erro SISTEMÁTICO, não ruído).
- F3 +value-free lesson: **1/3** (7, ausente, 8).
- F8 +lesson +RAG worked-example (4,8,12→3): **0/3** — escreveu 3,3,3
  (o número DO EXEMPLO). Interação negativa confirmada.
- Interpretation: menor condição suficiente NÃO encontrada aqui; cada
  substrato adicionado puxa o modelo p/ seus próprios números
  (atração generalizada). E: sensibilidade de variante — mesmo formato,
  superfície diferente (WARN/32 vs FAIL/40): baseline B 4/5 vs D 0/3.
  Benchmark integrity: wording/superfície da task decide o resultado
  tanto quanto a condição (§34 anti-gaming: variar é obrigatório).
- Runner: `/tmp/exp-f/run_f.py`; coleção `exp_f_lessons`.
- Status: STRONG EVIDENCE (efeito adverso replicado 2ª vez, outro par).

## EXP-G — self-knowledge (grounding) ⚠️ ADIVINHAÇÃO MATERIALIZADA

- Ga (qual arquivo define HybridSearch?): **0/3** — leu `core/ai/j…`,
  `core/hybrid…` (plausíveis, errados; verdade=rag.py). Sem busca
  sistemática (nenhum list_directory).
- Gb (nativeCheckInputs): **2/3** grounded (leu package.nix de verdade);
  1/6 crash real do provider (choices vazio → IndexError) — virou fix
  (guards + STUCK honesto + teste).
- **Side-effect grave**: um agente Ga CRIOU
  `modules/ai/jarvis/src/jarvis/core/hybrid_search.py` (`class
  HybridSearch:` placeholder) — materializou o palpite no repo
  (removido em fa9bb0e). Self-knowledge falha + escrita especulativa.
  REGRA (R6): agentes de experimento SEMPRE em jail /tmp (approval
  restrito por path), nunca approve-irrestrito no repo.
- Interpretation (§64): plausível ≠ verificado; grounding = leitura do
  arquivo autoritativo (Gb prova que funciona quando lê). RAG-discovery
  + filesystem-truth sustentado.
- Runner: `/tmp/exp-g/run_g.py`. Status: PARTIALLY VERIFIED.

## EXP-J — failure injection (Qdrant down) ⚠️ OUTAGE ≠ NADA

- Injeção: JARVIS_QDRANT_URL=:9 (refused), coleção isolada exp_j_probe.
- remember/remember_lesson/recall/lessons → **RAISED VectorStoreError**
  (conexão) — distinguível de "vazio" NA API, mas o inject de lessons no
  Agent engolia com `except: pass` → igual a miss (§27 viram fix).
- FIX: lessons_outage emitido no JSONL (tipo+motivo); run segue sem
  lessons; teste `test_lessons_outage_logged_not_silent`.
- count() degrada 0 (ok — é contador, não presença).
- FALSO-VERDE adicional (EXP-G): agente criou
  `core/hybrid_search.py` placeholder no repo (removido) — escrita
  especulativa guiada por self-knowledge errado. REGRA R6: agentes de
  experimento em jail /tmp, approval restrito por path.
- Status: PARTIALLY VERIFIED; R7 prioriza: Qdrant down ≠ "sem
  conhecimento" agora é observável.

## E6 — progressive disclosure (Ciclo 3) ✅ ARQUITETURALIZADO

- S1 all-tools: git 0, vault 0 (reproduz E1). S2a {só-correta}: git ✓,
  vault ✓, recall ✓. S2b categoria {correta+read_file}: git ✗ (atrai),
  vault ✓. S4 classifier determinístico: atingido por bug de prioridade
  de keyword ("commit" em "pushing commits" venceu "policy" — dependência
  do classificador, NÃO do modelo). E6-E router livre: picked rag_search
  (hop extra = entropia extra).
- Conclusão: categoria deve EXCLUIR attractors (read_file p/ ação);
  classifier simples+testado > router-livre. Threshold exato (2/4/6/8/12)
  fica p/ P2.
- Implementado: `core/tool_surface.py` (classify+surface+entropy) +
  `Agent(tool_class=)` filtro opt-in + `test_tool_surface` (8 testes).
- Harness-value (PHASE 17, mesma família 181): MODEL-ONLY 0/2,
  +TOOLS (C0) 0/3, +KNOWLEDGE (C2) 3/3→5/5, +VERIFICATION = honestidade
  (STUCK vs crash/mentira). Ganho = harness+representação, não modelo.

## CICLO 3 — contratos executáveis (implementado+testado)
- Contract A disclosure: tool_surface + tool_class (E6).
- Contract B value-free: lesson_lint + remember_lesson(lint/env
  JARVIS_LESSON_LINT, proveniência em meta) (R2).
- Contract C/D grounding+state: knowledge_state (CURRENT/HISTORICAL/
  SUPERSEDED/UNKNOWN/UNAVAILABLE/UNVERIFIED; OBSERVED/RETRIEVED/INFERRED)
  (G/J).
- Suite permanente: benchmarks/kb_regression.py (host-only).
- Docs: CAPABILITY-CONTRACTS.md, ANCHOR-PLAN.md (P0-P3/DEFERRED).

## PERSIST — context-loss persistence (PHASE 6) ✅ FUNCIONA VIA INJECT

- RUN A: fato "vault code QX-77" em coleção isolada. RUN B (agente
  fresco): escrever só o código. B0 sem memória: **0/3** (escreveu
  "vault_code" — palpite das palavras do prompt). B2 mesma memória
  (lessons() auto-injeta facts+lessons): **3/3** (QX-77 exato, turns 2).
  B3 (+tool_class): 3/3. UB (código no contexto): 3/3.
- Interpretation: persistência pós-reset funciona PELO inject
  (B2 == UB comportamentalmente); sem retrieval o modelo adivinha.
  Distingue model-memory (falha) vs retrieval+presentation (ok).
  Nota: facts SÓ valem porque lessons() inclui KIND_FACT — recall puro
  nunca é auto-chamado (boundary documentado).
- Runner: `/tmp/persist/run_persist.py`; coleção `persist_exp`.
- Status: VERIFIED (n=3; mecanismo = inject path).

## L9 — multi-step c/ regra arbitrária (PHASE 4/5) ❌ 0/9, FRONTEIRA MAPEADA

- Base 0/3 + tool_class=write 0/3 + base-pós-fix 0/3.
- Mecanismos: (1) attractor build_json_dataset (task diz CSV→JSON;
  ferramenta casa perfeitamente) → 3× ERROR → STUCK honesto pós-fix
  (antes: VERIFIED vácuo — fix de honestidade validado
  comportamentalmente); (2) dispositions CORRETAS mas evidence com
  números de linha do read-tool (fidelidade de evidência);
  (3) sem pivot p/ write_file (perseveração).
- Atribuição (§37): baseline falha + correct-tool-only falha → problema
  é CAPACIDADE (planejamento/serialização/fidelidade), não interface.
  Disclosure necessária mas insuficiente p/ L9.
- Crash-after-work (2/15 runs: Gb-0, l9-write-2, "list index out of
  range" tardio, arquivos escritos, resultado perdido) — OPEN,
  caçada em andamento (3 sites choices[0] já guardados; falta o site).
- Runner: `/tmp/l9/run_l9.py`; checker `/tmp/l9/l9_lib.py`.
- Status: UNVERIFIED (capability); fronteira = próximo bottleneck.

## SUBST-AGENT — substrate selection at agent level (PHASE 7) ⚠️ PARCIAL

- Git task (files HEAD~1..HEAD → out.txt), mcp on: default 0/3 (first
  tool list_directory ×3 — read-first), tool_class=action 0/3 (first:
  list,list,execute). Nenhum arquivo escrito em 6 runs. Probe→agente
  gap: nomear a tool ≠ executar a cadeia (git→parse→write).
- S2 lint (chain-B, coleção compartilhada + execute on): raw 0/3, lint
  0/3 — AMBOS escreveram 10 (número da lesson). Contaminação cruzada +
  execute mudam a dinâmica: experimento inválido como comparação;
  VÁLIDO como 3ª replicação da atração por números (6/6 escreveram o
  número da lesson!). Re-teste limpo (coleção só-linted, sem execute):
  stored value-free ✓ mecanicamente, comportamento 1/3.
- Wiring gap fechado: lint agora transforma error_pattern também
  (só-fix deixava "30 lines as 3" no texto injetado) + teste.
- Status: agent-level substrate = UNVERIFIED (0/6); lint mecânico
  VERIFIED, lint comportamental PARTIAL (1/3 limpo).

## TOOL-HONESTY FIX (L9 forense) ✅ COMPORTAMENTALMENTE VALIDADO

- Causa do VERIFIED vácuo: `{"ok": false}` de build_json_dataset virava
  string sem ERROR → successful_call → completion VERIFIED sem artefato.
- Fix: prefixo ERROR: quando ok==False (build_json_dataset +
  sanitize_secrets) + teste `test_deterministic_tool_failure_is_error`.
- Pós-fix L9: agente recebe ERROR, tenta 3×, STUCK honesto — zero
  VERIFIED vácuo. Falha legível ≠ falha resolvida (L9 segue 0/9).

## C6 — boundary decomposition (atômicas ✓, composição ✗)

- Probes (n=3): T1 3/3, T2 R1/R3/R4 perfect 3/3 (R2 0/3, R5 7/8),
  T3 3/3, T4 3/3, T5 3/3, T6 4/4.
- Agentes (n=3): S9 3/3, H2 3/3, H5 2/3, H6 1/3, R8 0/3 world (ação
  OK, "1 | hello" fidelidade), T8/X10A/X10B 0/9 (attractor).
- Crash tardio RESOLVIDO: Popen([]) em run_shell c/ cmd="" (reproduzido
  com traceback!) → ERROR 127 + teste. Era o "list index out of range"
  pós-trabalho (H2-0: arquivo certo + crash).
- Boundary: composição com observações (decorações vazam) + regra em
  loop (probe 3/3 → loop 0/9). Menor unsolved: R8-shape.
- Runners: `/tmp/c6/atomic.py`, `/tmp/c6/arms.py`.
- Status: VERIFIED (decomposição); boundary = COMPOSITION-LIMITED.

## C7 — R8 decomposition (fidelidade é o átomo)

- E1 (bytes exatos, sem recovery): 0/3 — decorações vazam, trailing-space
  some, tab vira ", ", newline final some. R3/R4/B4 (recovery/decisão/
  constante): 9/9. R5: 0/3 (rec 3/3, bytes 0/3). S6C/S6D/ST8/D2: 0/12.
- B-ladder: B1(E1) 0/3 tricky, B2(H2) 3/3 trivial, B3(H5) 2/3, B4 3/3,
  B5(R4) 3/3 simples, B6(R5) 0/3.
- S9/H2 passam (ASCII trivial); E1 falha (unicode/trailing/tab) — o
  átomo degrada com complexidade-de-byte. Refinamento do C6:
  "composition-limited" → fidelidade-átomo + composição amplifica.
- Runner: `/tmp/c7/run_c7.py`. Status: VERIFIED.

## C8 — byte boundary fechado (geração vs presentation vs tool)

- Probes F1-F17 (n=2): 13/17 exatos; falham F6/F7/F8/F9(1/2).
  Reps: escaped/hex/base64 2/2; literal/JSON-str/numbered/len 0/2.
- Arg-trace (n=2): disk==arg 100% (tool/FS inocentados); TR-F5 2/2;
  TR-F4/F13 corrompem no ARG (probe passava → presentation);
  CP escolheu write_file 2/2; SR/M2/M6 f.txt exatos 6/6 (bug meu no
  checker, corrigido na leitura); CPRO corrompe mesmo limpo.
- NIM referência: BLOCKED (6× timeout; sem invenção).
- Veredito: MODEL (F6/F7/F8) + PRESENTATION (decorações) + TASK-DESIGN
  (pedir repro quando str_replace 6/6). Responsabilidade: modelo opera,
  harness preserva. Runners: `/tmp/c8/probes.py`, `/tmp/c8/arms.py`.

## C10 — presentation + Harbor-variety (soberania + comparação)

- Presentation (n=3, payload generacionalmente OK): P0 raw 6/6 (trail +
  toolish); P1/P2/P3 (qualquer header/número) 0/6; P4 fence 3/6.
  Instrução explícita de strip NÃO adianta. Implicação: byte-tasks
  roteiam p/ str_replace (6/6, já implementado); SEM mudança de
  produção (read precisa de headers p/ navegar). L10-note: evidência
  por contenção vs exatidão é decisão de task-design futura.
- Harbor-variety: task E1 própria + terminus-2 + Bonsai fim-a-fim →
  reward 0.0 por mismatch de PROTOCOLO (prosa vs JSON-batch), classe
  INTEGRATION. Adapter próprio mapeado (BaseAgent; falta bridge
  exec/paths). opencode-agent BLOCKED (auth no container).
- Runners: `/tmp/c10/pres.py`; task `/tmp/harbor-work/bytecopy-task`.
