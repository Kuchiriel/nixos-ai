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
