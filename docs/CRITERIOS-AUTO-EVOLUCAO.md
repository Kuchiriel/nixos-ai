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
