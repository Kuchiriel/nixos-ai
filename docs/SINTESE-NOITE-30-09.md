# SÍNTESE DA NOITE 30/09 → 01/10

> Do que o loop noturno autonomo aprendeu, mediu e destravou. 13
> correções de harness, 4 bugs de verifier, 2 testes decisivos. Tudo
> medido, nada suposto. O que vem a seguir é a pergunta que os dados
> agora respondem com honestidade.

## O que foi CORRIGIDO (e era o que impedia tudo)

| # | Correção | Medido |
|---|---|---|
| 1 | Discovery só produz task acionável (actionable-first) | 0 review-task no topo |
| 2 | LLM discovery emite target_files **reais** | 4/4 targets válidos |
| 3 | Discovery tem **ground-truth dos testes** | para de propor "add tests" q já existem |
| 4 | Discovery **exclui archive/** (código morto) | 5/5 tasks foram p/ código morto → 0 |
| 5 | Contexto do patcher: 84× → 9.2× maior | `Hunk not found` 6 → **0** |
| 6 | `_realign_indent` (deslize de indent) | `Syntax error` 3 → **0** |
| 7 | Prompt: indent é sagrada, mudanca mínima, exemplo | junto com #6 |
| 8 | Traceback real no retry (não contagem) | o modelo vê a falha |
| 9 | **Grounding**: entrega o teste que reprovou | o modelo vê o contrato |
| 10 | `discover_test_files` acha layout Nix | 0 → **111** testes |
| 11 | `_has_tests` (fallback parava no tests/ vazio) | "no tests ran" → **1637 passed** |
| 12 | **Baseline de teste** (falha de ambiente ≠ falha do patch) | não culpa o modelo por ambiente |
| 13 | **Filtro de meta-task** (`_is_meta_task`) | discovery para de gerar add-test |
| 14 | Retry com orçamento + convergência medida | mais ciclos/dado por noite |
| 15 | Anti-reward-hacking (teste vazio não é melhoria) | fecha auto-premio |
| 16 | Parser tolera before/after + grammar-vazia→texto | patch não é mais descartado |

## 🔬 Os DOIS TESTES DECISIVOS (o dado mais importante da noite)

Mesmo MoE, mesmo grounding, mesmo patcher do nightwatch:

- **T1** — bug de 1 linha (typo `projectz`→`projects`): **ACERTOU**
  (old_text exato, new_text certo).
- **T2** — bug realista (IndexError sem guarda): **ACERTOU** (produziu
  `if not self.items:`).

**O modelo TEM a capacidade (2/2).** A "não convergência" (0/N nos
ciclos) **não é limitação do modelo** — nem de contexto (T2 é um
arquivo de 769 linhas e ele acertou). É a **task** e o **ciclo**:

1. **Task auto-referencial/ambígua** — "add test coverage" (modelo
   escreve o teste E o contrato, que pode não bater com o código).
   "add docstring" não tem resposta única. **Filtrado (#13).**
2. **Ainda não converge no bug-fix real** — o modelo acerta o bug
   isolado mas o ciclo real (branch, 4 tasks, contexto acumulado) não.
   0/19 convergência nos 4 ciclos com bug-fix-only.

## Os 4 BUGS DE VERIFIER (a Lição 1, 5ª–8ª vez)

Todos **verifier mentindo**, não modelo:

1. `run_targeted_tests` parava no `tests/` **vazio** da raiz → "no
   tests ran" → 112 testes reais nunca alcançaados.
2. `test_llama_cpp_chat` falha por **ambiente** (exige LLM) — o modelo
   era culpado. Baseline resolve.
3. `discover_test_files` não achava o layout Nix (corrigido de manhã).
4. `2 passed 2 failed` era o **mesmo** fallback quebrado + teste de
   ambiente, não o patch.

**Lição que se repete:** quando um fix de layout funciona, **audite
os outros que assumem o mesmo layout**. E antes de culpar o modelo
por "não convergir", **verifique se o verifier nem media certo**.

## O estado do pipeline (honesto, 07h)

- ✅ Gera task REAL, em código VIVO, com target válido
- ✅ Patch APLICA (não é mais "no target"/"hunk not found")
- ✅ Teste roda, é honesto, não culpa o modelo por ambiente
- ✅ Rejeita o que quebra, não se premia com vazio
- ✅ Retry entrega traceback + teste que falhou
- ✅ Reporta convergência medida por run
- ❌ **Ainda 0 commits** — 0/N convergência no bug-fix real

## A pergunta que os dados agora respondem (próximo passo)

O modelo **acerta isolado** (2/2) e **não converge no ciclo**. A
diferença testável: no meu teste, o modelo vê **um arquivo, uma task,
sem pressão de branch/contexto acumulado**. No ciclo real ele tem
**4 tasks numa branch, contexto que cresce, e o mesmo arquivo visto N
vezes**. Hipóteses (em ordem):

1. **Contexto acumulado**: o 2º/3º task do ciclo vê o arquivo já
   modificado pela task anterior (a branch não foi resetada) → o
   `old_text` que ele gera não casa com o arquivo **atual** (drift).
   → Teste: um ciclo com **1 task só** e ver se converge.
2. **O `old_text` casa, mas a validação reprova por outro motivo** —
   o modelo acerta o bug, mas o teste tem uma expectativa mais ampla.
3. **Ruído no sinal** — o traceback+grounding chega mas é demais para o
   modelo parsear junto com o arquivo.

**Nenhum destes é "limite do modelo".** Todos são engenharia de
harness — exatamente onde a literatura (arxiv-2607.28802) diz que o
ganho está. A régua do dono (paridade 1:1 de ENTREGA) segue com
trabalho de software claro pela frente.

## Como retomar de manhã
- `docs/CRITERIOS-AUTO-EVOLUCAO.md` — este arquivo + histórico
- `docs/REIDRATAR-APOS-COMPACTAR.md` — prompt de reidratação
- `/tmp/opencode/overnight/loop-night6.log` — dado bruto dos ciclos
- Vault `noite-30-09-harness-loop.md` — contexto noturno

---

## 🌅 A CAUSA RAIZ DO "NÃO CONVERGE" (08h) — o maior achado

Depois de 2 testes decisivos provarem **capacidade 2/2**, o gap
permanecia. A causa real só apareceu medindo a cadeia inteira:

1. **`models.nix` mente sobre o contexto.** Declara `ctx = 32768` pro
   `jarvis-strong`, mas a unit llama-cpp usa **`prof.ctxSize` do profile**
   (`chat` = **8192**). O `/props` do servidor confirma: `n_ctx: 8192`.
   Dois campos (`ctx` do modelo, `ctxSize` do profile) divergem — o
   registry não descreve a realidade.
2. O patcher mandava o **arquivo inteiro**: `context_budget.py` = 769
   linhas = 30k chars ≈ **7.5k tokens**.
3. Sob ctx 8192 sobra ~600 tokens. O cliente recorta `max_tokens` e a
   **resposta trunca**: medido, JSON de 334 chars cortado em **99**,
   sem `}` → `substring not found` → patch **descartado**.
4. Isso parecia "grammar falha" e "modelo não acerta" — mas era o
   **PROMPT comendo o contexto**. Nem o modelo nem a grammar.

**Fix:** `files_bit` com orçamento derivado do **ctx real do servidor**
(`_context_window()`), deixando ~1024 tokens para a resposta — em vez
de mandar tudo e truncar a resposta no fim (o que perde o patch
inteiro).

**Verificado no MESMO bug que antes falhava: `ok=True`, patch com a
guarda correta.** Este é o fix que pode destravar a convergência.

### A lição mais cara da noite (e a mais útil)
Por **seis horas** o sintoma foi "o modelo não converge". A verdade
era: **o harness estava truncando a resposta do modelo antes dela
chegar ao patcher**, e eu estava olhando a camada errada (o modelo) em
vez do instrumento (o orçamento de prompt). Isso é literalmente o
*repair-assignment problem* do paper — e a **6ª** vez que a Lição 1
me pegava. **Sempre que algo "não funciona", perguntar: o instrumento
mediu certo?**

---

## ✅ Fim da noite — v7 com o fix (09h30)

O loop v7 rodou **6 ciclos** com o fix de budget de prompt.
**Instrumento limpo de ponta a ponta:**

| Erro de instrumento (antes constante) | v7 |
|---|---|
| `substring not found` (resposta truncada) | **0** |
| `no tests ran` (suite não achada) | **0** |
| `Hunk not found` | **0** |
| `Syntax error` (indent) | **0** |

Convergência 0/23, 0 commits — mas **agora a falha é legítima**: o
patch **aplica** (json-patch 15-33s, resposta inteira) e o **teste
reprova**. Isso é trabalho real sendo medido, não instrumento quebrado.

### Onde estamos (09h30, 24 commits na noite)
- Pipeline **mede certo** do discovery ao gate — cada camada verificada.
- O modelo **tem capacidade** (2/2 testes decisivos).
- Falta: ele acerta o bug **isolado** mas não no ciclo real
  (branch + 4 tasks + validação ampla).

### A pergunta seguinte (dados apontam para cá)
Com o instrumento correto, a convergência 0 é do **modelo no contexto
do ciclo** ou da **validação ser mais ampla que o bug**? O próximo
teste decisivo: **1 task por ciclo** (isola drift de branch) e
comparar com 4 tasks. Se 1 task converge → era drift/contexto
acumulado. Se nem 1 converge → a validação é o filtro estrito demais
(o bug é corrigido mas o teste exige mais).

Nenhum dos dois é "limite do modelo" — são hipóteses de harness, e é
exatamente onde a literatura diz que o ganho está.
