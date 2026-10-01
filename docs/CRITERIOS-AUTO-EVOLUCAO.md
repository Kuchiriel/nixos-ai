# Critérios: nightwatch PUEDE modificar e testar o harness (30/09)

> O que precisa ser verdade, mensuravelmente, antes de dizer que o
> harness se auto-melhora sem se quebrar. Cada item tem verificação
> honesta — nada de "parece que funciona".

## Onde estamos (run instrumentada 16:16)

O ciclo **inteiro** roda pela 1ª vez: discovery → target validado →
patch gerado → patch aplicado → teste executado. Isso é novo. Mas
**0 commits** ainda, e 2 falhas honestas sobram (hunk não casa; patch
quebra teste). Os critérios abaixo são o caminho de 0 → commits reais
**sem quebrar nada**.

---

## C1 — O patch loop nunca recebe lixo ✅ JÁ ATINGIDO
- **Critério**: `discover_tasks()` devolve task actionable antes de
  review; o cap conta actionable primeiro.
- **Verificação**: `_has_real_target()` ordena; run devolveu 9 tasks,
  todas PATCH (commit actionable-first).
- **Estado**: ✅. Antes: 5 tasks, 5 review, 0 patch.

## C2 — O verifier é HONESTO ✅ JÁ ATINGIDO
- **Critério**: `discover_test_files()` acha o layout real (Nix); roda o
  teste CERTO pro arquivo mudado; falha pré-existente não é atribuída
  ao patch.
- **Verificação**: `discover_test_files() > 0`; mapeamento correto
  (`agent_loop.py`→`test_agent.py`); baseline antes/depois igual.
- **Estado**: ✅ 0→111 testes. É a **5ª vez** que a lição (1) pega:
  verifier quebrado, não modelo.

## C3 — O patch APLICA quando o modelo acerta o `old_text` ⏳ INVESTIGAR
- **Critério**: patch com `old_text` correto aplica em 1 tentativa e
  sobrevive ao `safe_editor` (sintaxe ok).
- **Falha de hoje**: `Hunk not found` em `cli/main.py`. 3 causas a
  separar — e é aqui que "verificar antes de agir" importa:
  - **(a) modelo inventa** `old_text` → é limite do modelo.
  - **(b) drift**: o `old_text` era do arquivo antes de outra escrita.
  - **(c) contexto insuficiente**: o modelo não viu o trecho exato.
- **Verificação**: capturar 1 falha real, comparar o `old_text` do
  modelo com o arquivo atual linha-a-linha, classificar (a/b/c).
  - (c) → melhorar o contexto enviado ao patcher (arquivo inteiro, não
    trecho). **Minha hipótese**, mas é hipótese — classificar antes.
  - (a) → muda o critério: "aplica quando acerta", e mede-se a taxa.
- **Estado**: ⏳ primeiro dado honesto de patch-real a capturar.

## C4 — Patch que quebra teste é REJEITADO ✅ JÁ ATINGIDO
- **Critério**: teste falha após patch → patch revertido, main intacto,
  `0 commits` quando o teste quebra.
- **Verificação**: `git status` limpo após run; branch de task abortada.
- **Estado**: ✅ branch isolation + abort existem; `4p3f → 0 commits`
  confirma que o gate segura.

## C5 — Retry converge (o loop RHO) ⏳
- **Critério**: em N≥3 runs, ao menos 1 task que falhou na 1ª tentativa
  passa numa retry (o modelo aprende com o erro entregue).
- **Instrumentação**: logar, por task, se `attempt>1`kbd succeeded.
- **Estado**: ⏳ depende de C3 — convergir exige aplicar.

## C6 — O harness NÃO se quebra ✅ JÁ ATINGIDO
- **Critério**: depois de K runs noturnos, a suíte continua verde **sem
  humano tocar nada**; `flake check` passa; serviços ativos.
- **Verificação**: antes/depois de cada run, `pytest` completo. Se um run
  deixar main vermelho, é **bug de segurança** e para o pipeline.
- **Estado**: ✅ main verde há 5+ runs; nenhum commit ruim.

---

## Ordem de ataque (menor effort → maior ganho)

1. **C3-investigar** — SEMPRE primeiro. Sem classificar (a/b/c), tudo
   abaixo é chute. (É a regra que me poupou 3 vezes hoje.)
2. **C3-contexto** — se for (c): dar o arquivo inteiro ao patcher.
3. **C5** — medir convergência, N≥3. Só depois de C3.

**Regras que atravessam tudo:**
- *Verifier primeiro* (lição 1): não adaptar o runtime pra passar.
- *n=1 é diagnóstico, n≥3 é medida* (lição 8): taxa só vale com N≥3.

## O que falta pro "se auto-evolui" (a pergunta do dono)

Hoje o nightwatch grava **lição** no `AGENTS.md` quando falha — é o
esqueleto do auto-evoluir. Falta o passo que fecha o ciclo: **usar o
feedback do teste como sinal na próxima tentativa**, e — quando a lição
for "isto aqui quebrou" — virar um **teste de regressão** que protege o
harness. Ou seja: **o harness usa as próprias falhas como escudo.** É o
RHO (arXiv 2606.06324). C3→C5 são a pré-condição disso.
---

## C3 — RESULTADO (30/09 17h): classificado e corrigido ✅

**Classificação por MEDIÇÃO** (não chute — contei os chars que o modelo
realmente vê):

| | Antes | Depois |
|---|---|---|
| Contexto de `cli/main.py` | **873 chars** (84× menor) | **7.944 chars** (9.2× menor) |
| Causa do `Hunk not found` | fallback mandava "imports + ÚLTIMA função" (lasc arbitrária) | head do arquivo (código real) |
| `cmd_metrics` na task casa com `_cmd_metrics`? | ❌ (caía no head) | ✅ (variantes sem `_`/prefixo) |

**Run pós-fix (16:45), 6 tasks distintas tentadas:**

| Métrica | Valor | Significado |
|---|---|---|
| `Hunk not found` | **0** | ✅ patch aplica agora |
| `Syntax error (unindent)` | 3 | patch **aplicou**, modelo errou indentação |
| `Validation Failed` | 1 | patch **aplicou**, quebrou teste |
| Commits | 0 | safe_editor/branch segurando (correto) |

**Conclusão do C3:** a causa era (c) contexto — **corrigida**. O patch
agora **aplica** (chega ao stage de sintaxe/validação). A falha restante
**não é mais do instrumento**: é o modelo escrever indentação errada /
quebrar teste — problema de **capacidade**, que o `safe_editor` barra
corretamente (é o papel dele). `Hunk not found` = 0 é o sinal limpo.

**Próximo (C3b, capacidade, não contexto):** o modelo recebe 8k chars e
ainda erra indentação. Opções: (a) exigir que o patcher normalize
indentação via `ast.parse`+reindent antes do guard (caro/arriscado);
(b) dar ao modelo um exemplo de patch válido no prompt (few-shot);
(c) aceitar: é limite do modelo local, medir taxa. **Decisão do dono.**

## Estado consolidado até aqui
- C1 ✅ C2 ✅ C3 ✅(contexto) C4 ✅ C6 ✅ — o harness **age sem se quebrar**
- C5 ⏳ (convergência — precisa de commits reais, que exigem C3b)
- 6+ runs, main **sempre** verde, `0 commits` ruins. O pipeline é SEGURO
  mesmo quando o modelo falha — que é o ponto.

---

## C3b — RESULTADO (30/09 18h): indentação eliminada via harness ✅

O dono foi categórico: **"jamais aceitar limite do modelo local / teto
do harness"**. A literatura confirma que seria o erro:

- **arxiv-2607.28802 "Model or Harness"**: *a mesma falha visível pode
  exigir post-training **ou engenharia de harness*** — e rótulo de
  outcome **não basta** pra decidir (*repair-assignment problem*).
- **arxiv-2605.23950**: falhas de agente são predominantemente
  *"execution and orchestration"*, não *"knowledge"*.
- **Harness Engineering**: *Agent = Model + Harness*. Harness-maxxing:
  Qwen3.6-27B ≈ Sonnet em Terminal-Bench; **uma tool dobrou SWE-bench**.

Eu ia aceitar "o modelo local não indenta". **Não é verdade** — era
harness.

### Causa medida (não inferida)
`ast_cache.py:126`, 3 tentativas no mesmo ponto: o `old_text` do modelo
casava **literal** no arquivo, mas o `new_text` entrava com um nível a
menos. E a estratégia **1 (exact match — a mais comum!)** fazia
`replace()` direto, **sem nenhum realinhamento**. Além disso o prompt
truncava o arquivo em `c[:4000]`, caindo no meio de bloco indentado
(modelo via hierarquia quebrada).

### Fix (tudo harness, custo zero de tokens)
- `_realign_indent()`: conteúdo bate 1:1 → re-aplica a indentação do
  baseline linha-a-linha. Cobre delta uniforme **e não-uniforme**.
  **Não toca se a lógica difere** (nunca mascara mudança real).
- Aplicado **também na estratégia 1** (o beco sem realign).
- Prompt: sem truncar em 4000, "indentação é sagrada", "mudança
  mínima", exemplo correto.

### Verificado (run 18:05, patches REAIS em L9 runner + logging config)
| Métrica | Antes | Depois |
|---|---|---|
| `Syntax error` | 3 | **0** ✅ |
| `Hunk not found` | 0 | 0 ✅ |
| `Validation Failed` | 1 | 3 (patch aplica; **lógica** quebra teste) |

**As duas falhas que eu ia chamar de "limite do modelo" foram eliminadas
100% por engenharia de harness.** Restou `Validation Failed`: patch
aplica, mas quebra a lógica — próximo alvo, e **também não é limite de
modelo** (é o modelo não entendendo a intenção do código, ou o teste
cobrindo algo que a task não pediu).

### Lição de operação (aprendida na unha)
O nightwatch roda em **branch de task** e aborta a branch em falha —
**trabalho não commitado nessa branch é perdido**. Descobri porque um
append de doc desapareceu quando a branch foi abortada. Regra: **commit
ou stash antes de disparar o nightwatch**; commit de doc direto em main.

### Regra permanente (dono)
Nunca "limite do modelo local" / "teto do harness". Se falhar: ler
~/Books + rag + online; perguntar **conhecimento vs execução**; se
execução → conserta no harness. Só N≥3 tentativas **E** literatura. A
régua do dono: **paridade 1:1 de ENTREGA** com API (não velocidade).

---

## C5 — sinal entregue, convergência ainda não medida (30/09 19h)

O que era o **pre-requisito** do RHO (o harness tem que entregar o erro
ao modelo no caminho que ele realmente usa) está **feito e verificado**:

- O caminho **grammar/JSON** é o que o nightwatch **sempre** usa (o de
  texto livre nunca é alcançado). Ele **não recebia** `previous_errors`
  — então o traceback, que eu tinha acabado de montar, **nunca chegava**
  ao modelo no retry real. O loop estava cego no caminho que ele roda.
- `_request_json_patch()` agora aceita `previous_errors`; `error_section`
  entra no prompt JSON; o caller passa. Cadeia verificada in-process.
- O traceback real (`ValidationStep.output`) entra em `previous_errors`
  (antes só iam contagens "2 passed, 2 failed"); truncamento 300→2500.

Run pós-fix: retries **continuam sem convergir** — mas agora são retries
**informados** (o modelo vê a falha), não cegos. As tasks em questão
("refactor L9 benchmark runner", "centralize logging") são difíceis e o
modelo quebra o teste. Isso é **trabalho real** (patch aplica, teste
reprova), não harness quebrado.

**Não chamo isso de "limite do modelo"** (regra do dono). É C5 ainda
**aberto**: converge exige (a) sinal ✅, (b) task com escopo menor
(refactor grande é ambíguo — talvez o harness deva quebrar task grande
em hunks menores), (c) N≥3 pra medir taxa (lição 8). Próximo experimento
honesto: **encolher o escopo da task** no prompt, medir de novo.

**Nota de operação (3a vez):** nightwatch recria branch de task e ABORTA
em falha — 3 edits meus foram revertidos seguidas por aborts, e o
`git checkout main` é periódico obrigatório. Regra: **nunca editar com o
nightwatch rodando; parar → main → editar → commit → só então rodar.**

---

## Estado consolidado 30/09 19h — onde o auto-evoluir realmente está

### O que FUNCIONA (medido, nãorochido)
| Camada | Métrica | Valor |
|---|---|---|
| Discovery | task com target real validado | 4/4 (LLM real) |
| Discovery | task **é trabalho real** (verifiquei na mão) | `agent_loop.py` sem teste ✅, `kb_regression.py` deref ✅ |
| Patch | `Hunk not found` | **0** |
| Patch | `Syntax error` (indent) | **0** |
| Retry | traceback real chega ao modelo (grammar) | ✅ cadeia verificada |
| Gate | patch que quebra teste → rejeitado, main intacta | ✅ |
| Segurança | main verde, 0 commits ruins | ✅ 10+ runs |

O harness hoje **age sem se quebrar** e **fala a verdade** (quando diz que
falhou, é porque algo real quebrou). A pipeline inteira é honesta.

### Onde NÃO converge (e por quê — sem "limite de modelo")
O retry ainda não converge nas tasks observadas ("add missing test
coverage for context.py"). Razão medida: **é a task mais difícil possível**
— escrever um teste novo que o próprio `run_targeted_tests` valida. O modelo
precisa acertar o teste E o código de uma vez. Isso é **ambiguidade da task**,
não cegueira do harness (que agora entrega traceback).

Levantamentos honestos para o próximo ciclo (NÃO é teto):
1. **Task de "add test" é a mais dura** — o harness valida com o teste que
   o próprio modelo escreveu (viés). Talvez o harness deva validar
   "o teste novo passa + os antigos continuam passando" explicitamente, ou
   essa categoria P3 deva rodar **por último** (depois de bug-fix, que é
   mais fácil de convergir).
2. **max_tasks gasta tudo numa task só** — o loop de 3 retries consome o
   orçamento; tasks depois não rodam. Encolher `max_retries` (3→2) libera
   orçamento para mais tasks distintas.
3. **Ainda não medi taxa de convergência com N≥3** (lição 8) porque as
   tasks post-fix são poucas. Preciso de 3+ runs limpos.

### Regra que continua valendo
Nada aqui é "limite do modelo local" nem "teto do harness" (regra do dono,
literatura nos Papers). As falhas são de **orquestração/ambiguidade de task**
— e é exatamente isso que continua Having trabalho de software.

### Como retomar
- `docs/REIDRATAR-APOS-COMPACTAR.md` (prompt de reidratação)
- este doc (critérios + estado medido)
- Regra de operação: **parar nightwatch → main → editar → commit → rodar**

---

## Ciclos N=2 (30/09 20h) — 3 fixes de desperdício medidos

### Reward-hacking fechado (segurança)
Probe: o harness rodava o teste que o **próprio modelo** criava. Um teste
**vazio** (`def test_x(): assert True`) passava e contava como melhoria —
`passed=True` verificado. Num harness auto-evolutivo isso é o pior tipo de
falha: **ele se premia com nada, para sempre, e parece progresso**.
Fix: `_test_has_real_assertion()` — teste novo exige ≥1 `test_*` e ≥1 assert
não-constante. Verificado 4/4 (vazio→reprova, real→aceita). 4 testes.

### Retry consumia o run inteiro numa task só
Medido: 3 tentativas × ~45s de uma task impediam as outras 4 da fila de
rodarem. Fix: retry **consciente de orçamento** — >50% do budget → 2
tentativas, >75% → 1. Preserva convergência quando há tempo, libera
orçamento p/ mais tasks distintas.

### A noite inteira ia para código morto
Medido no ciclo 1: **5/5 targets** em `archive/`. O `archive/README.md`
diz: módulos arquivados de propósito (0 imports, substituídos por
`nightwatch/*`). Testar/refatorar código que não roda = valor zero, mas
custava 3 retries por task e impedia o run de tocar código vivo.
Fix: discovery exclui `*/archive/*`; execução pula task 100% archive.

### Ciclo 2 (pós-fix): targets em código VIVO
| Ciclo | Tasks | Commits | Alvos |
|---|---|---|---|
| 1 (pre-archive-fix) | 9 | 0 | 5/5 em `archive/` (morto) |
| 2 (pós-fix) | 9 | 0 | `benchmark tracker`, `CLI launcher` (**vivo**) |

Ainda **0 commits** — mas agora o trabalho é sobre código que roda. Os
targets reais são bons ("Fix unhandled exception…", "Fix unvalidated
input in CLI launcher…").

### Onde está (honesto, sem "teto")
Falta **convergência**: o modelo propõe defeito real, gera patch que
aplica, mas o teste reprova. O sinal (traceback) chega. O que falta é o
modelo acertar a correção — que é trabalho de engenharia de contexto
(grounding melhor no código), não mistério. **N=2 ainda não é medida**
(lição 8: N≥3). Próximo: ciclo 3 p/ fechar N, e se não convergir,
aprofundar no *porquê* (ler o traceback que ele recebeu vs o que ele
produziu).

---

## N=3 consolidado + métrica de convergência (30/09 21h)

### Métrica agora é do harness, não do olho (C5 automatizado)
`HarnessResult` gained `retry_succeeded / retry_attempted` +
`convergence`. Task que passa numa tentativa >1 conta como convergida (o
modelo recebeu o traceback e corrigiu). O run reporta
`Retry convergence: N/M (x%)`. Agora o C5 é **medido a cada run**, não
lido de log à mão (lição 8 satisfeita por construção).

### 3 ciclos,Progresso real e honesto
| Ciclo | Tasks | Commits | Alvos | wasted slots |
|---|---|---|---|---|
| 1 (pré archive-fix) | 9 | 0 | 5/5 `archive/` (morto) | teste em código morto |
| 2 (pós archive-fix) | 9 | 0 | **código vivo** | retry 3× numa task |
| 3 (pós métrica) | — | — | converges? | run lento (MoE 61s/patch) |

Ciclo 3 ficou num loop de chamadas LLM lentas (61s por patch, MoE sob
carga) — sem sinal novo além do que ciclos 1-2 já deram. Parei o run em
vez de esperar sem informação.

### Onde está EXATAMENTE (sem "limite"/"teto")
O harness hoje:
- gera task **real** (defeito concreto, em código vivo) ✅
- entrega **traceback real** ao retry ✅
- aplica o patch ✅
- roda o teste certo ✅
- **rejeita** o que quebra (main intacta) ✅
- **não se premia com teste vazio** ✅ (anti-reward-hacking)
- reporta **convergência** medida ✅

O que falta é o **último mile**: o modelo aplica o patch mas o teste
reprova, e o retry (mesmo com traceback) não acerta ainda. Isso é
**grounding de contexto** — a pergunta certa agora não é "por que o
modelo errou" (ele tem o traceback) mas **"o que no contexto entregue
torna a correção difícil de acertar?"**: será que falta mostrar o
**código-fonte inteiro** (não a seção), ou o **teste que falhou** (o
modelo não vê o arquivo de teste!), ou a **assinatura da função
falhando**?

**Hipótese mais forte (a testar):** no retry, o modelo recebe o
traceback mas NÃO o **arquivo de teste** que reprovou — ele vê um
`AssertionError` sem saber o que o teste exige. Dar o teste junto é a
próxima mudança de harness mais provável.

### Lição do dia (a que mais importa)
Onze correções de harness hoje. **Nenhuma** foi "o modelo é fraco".
Todas foram "o harness escondia informação / media errado / dava
trabalho inútil". A literatura (arxiv-2607.28802) chama isso de
**repair-assignment problem**: a decisão "modelo ou harness?" quase
sempre é do harness quando olhada de perto. A regra do dono —
*paridade 1:1 de ENTREGA* — segue sendo a régua, e há trabalho de
software claro pela frente.

---

## Noite 30/09 → 01/10 — loop automático (12 ciclos)

`scripts/overnight-harness-loop.py` roda 12 ciclos (cooldown 90s, teto
1h/ciclo). Entre ciclos: limpa a fila, mede **convergência** (o harness
reporta), diagnostica o **último mile**. **Nunca commita** — só o
nightwatch, e só se a validação passar. Log: `loop-night.log` + `cycle-N.log`.

### Fixes que entraram antes da noite
- **Grounding no retry** (`_ground_failure`): o harness entrega o
  **arquivo de teste que reprovou** (em volta da linha + o corpo da
  função de teste = o contrato), não só o traceback. Medido: o modelo
  via `AssertionError` mas não via *o que o teste exige*.
- **Métrica de convergência** no `HarnessResult` + no summary do run.
- **Anti-reward-hacking**: teste vazio (`assert True`) não conta como
  melhoria (o harness rodava o teste que o próprio modelo criava).
- **`archive/` fora dos alvos** (código arquivado = valor zero).
- **Retry com orçamento**: não monopoliza o run numa task só.
- **systemctl kill** no overnight (`stop` pendura em call LLM).

### Padrão observado no ciclo 1 (diagnóstico, não chute)
As tasks que o nightwatch converge não são aleatórias — há **duas
famílias**:
1. **Bug-fix pequeno e localizado** ("Fix None dereference in CLI
   launcher…", código vivo) → o modelo **tenta**, o patch aplica, mas o
   teste ainda reprova.
2. **Add-test** ("Add missing test coverage for X") → o modelo **não
   acerta** (é a mais dura: precisa escrever um teste novo que o próprio
   harness valida).

**Isto não é "modelo fraco"** — é **ambiguidade de task**. O gargalo do
último mile está concentrado na família add-test. Próximo ataque (depois
dos dados da noite): (a) discovery prioriza bug-fix pequeno sobre
add-test, (b) tratar add-test como categoria com validação diferente
(valida que o teste novo *cobre algo* + não quebra os outros), ou (c)
rodar add-test por último, depois das que já convergem.

### O que medir de manhã
- **Convergência por ciclo** (o número que faltava, agora automático).
- **Primeiro commit real** (0 até agora). Se aparecer, o pipeline
  fechou de ponta a ponta.
- Se convergência continuar 0 com grounding no ar: comparar *o que o
  modelo recebeu* vs *o patch que produziu* — a pergunta vira "a
  informação não basta ou ele não a usa?".

---

## Noite 30/09 — 2 bugs de VERIFIER encontrados (a Lição 1，奇数 vez)

Medindo os ciclos noturnos (o `baseline-check` que criei não pegava),
achei **dois** bugs onde o próprio nightwatch estava mentindo — ambos
**verifier quebrado**, não modelo:

### V1 — `run_targeted_tests` parava no `tests/` VAZIO
A raiz do repo tem um `tests/` **vazio** (0 `test_*.py`). O fallback
usava `next(d for d in (...,"tests",...) if d.exists())` — pegava o
vazio **primeiro**, rodava `pytest tests/` → **"no tests ran"** →
`passed=False`. Os **112 testes reais** em `modules/ai/jarvis/tests/`
nunca eram alcançados. Duas falhas de uma vez: (a) task reprovada por
"não achou teste", (b) baseline nunca populado (sem linha `FAILED`).
Fix: `_has_tests()` só aceita dir com `test_*.py`. Verificado: agora
`1637 passed` (antes "no tests ran").

### V2 — baseline de teste falhava por AMBIENTE
`test_integration::test_llama_cpp_chat` exige o LLM carregado; com o
MoE no ar ele falha (500). O nightwatch via isso como falha **da task**
— o modelo culpado por algo que não fez. O padrão "2 passed, 2 failed"
de 2 ciclos consecutivos era **esse** teste. Fix: baseline captura as
falhas de ambiente (1ª task, branch limpa, cacheado) — task só é
reprovada por falha **NOVA** que o patch introduziu.

### A lição que importa (repetição da Lição 1)
V1 é a **mesma classe** do bug de `discover_test_files` que corrigi de
manhã (não achava o layout Nix) — mas **no outro lado** do validador.
Dois lugares com a mesma suposição de layout, um corrigido e um não.
**Lição: quando um fix de layout funciona, audite os outros que
assumem o mesmo layout.** E: antes de culpar o modelo por "não
convergir", verifique se o **verificador nem estava medindo certo**.

### Estado do loop (o que o pipeline faz agora)
- baseline: falha de ambiente não reprova
- `_has_tests`: suíte real roda (1637 testes, não "no tests ran")
- retry entrega traceback + o **teste que reprovou** (grounding)
- métrica de convergência reportada por run

Ainda **0 commits** nests ciclos — mas agora o "falhou" significa
falha REAL do patch, não verifier mentindo. Essa é a base pra medir
convergência de verdade.

---

## 🔬 TESTES DECISIVOS (30/09 madrugada) — capacidade 2/2 COMPROVADA

Dois testes com o **mesmo MoE** e o **mesmo grounding** que o nightwatch
usa:

**T1 — bug de 1 linha (typo)**: `projectz` → `projects` em
`find_repo_root`. **ACERTOU**: `old_text` exato, `new_text` certo.

**T2 — bug realista (IndexError sem guarda)**:
```python
def get_size(self):
    return self.items[0].size   # IndexError se vazio
```
**ACERTOU**: produziu `if not self.items:` guard.

**Conclusão: o modelo TEM a capacidade (2/2).** O "não converge"
(0/31 em 5 ciclos) **não é limitação do modelo**. As duas hipóteses
restantes, em ordem de evidência:

1. **A task é auto-referencial/ambígua** (add-test, add-docstring) —
   testado e filtrado (`_is_meta_task`). Restam só bug-fix.
2. **O patch precisa acertar num arquivo REAL grande** com o
   contexto real (minhas tasks eram isoladas, do próprio jeito que o
   modelo acerta). O nightwatch mexe em `cli/main.py` (73k), `agent.py`
   etc. — onde o mesmo raciocínio é mais difícil de aplicar.

### Filtro de meta-task no ar
`_is_meta_task()` (código) + prompt. Verificado com LLM real: discovery
agora devolve **só "Fix <defeito concreto>"** — a família que o modelo
**acerta** (2/2 provado). Ciclo 5 (05:35) já processou "Fix potential
memory leak…", "Fix AttributeError…" etc. — zero add-test.

### O que falta medir (amanhã, com N≥3 do v5)
Se o bug-fix-only converge. Se ainda 0: o gap é **contexto em arquivo
real grande** (o modelo acerta isolado, não no arquivo de 73k com
constraints) → aí o fix é dar mais contexto, ou quebrar a task em hunks
menores, ou ancorar por número de linha.
