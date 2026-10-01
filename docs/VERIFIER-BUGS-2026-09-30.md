# Os 6 bugs do verifier que faziam o nightwatch parecer "burro" (30/09)

>TL;DR: **cinco bugs de ambiente** e um **de semântica** faziam a convergência
> ser 0/N. Nenhum deles era o modelo. Todososta mesma família: **o verificador
> mentia, e o harness atribuía a mentira ao modelo.**

## Como foi encontrado

Não foi por leitura de código — foi por **instrumentação**. `_dump_evidence()`
grava, por tentativa: a task, o patch exato do modelo (old_text/new_text), a
saída da validação, `new_fails` e o baseline. Sem isso, a pergunta "o modelo
patchou errado ou a validação é ampla demais?" exige adivinhar — e da última
vez que adivinhei, errei por 6 horas.

A primeira evidência respondia:

```
summary:   "2 passed, 1 failed"
new_fails: []            ← a falha NÃO é do patch
val_output: "No module named pytest"
```

`new_fails` vazio + falha = **verificador, não modelo**. Essa foi a prova.

## Os 6 bugs

| # | Bug | Sintoma | Correção |
|---|-----|---------|----------|
| 1 | Validador chamava `python3 -m pytest`; o serviço **não tem pytest** (era só `nativeCheckInputs`, build-time) | `No module named pytest` contava como falha da task | `pytest` no closure + Nix escolhe o interpretador |
| 2 | Alternativa `nix develop --command python -m pytest` | No unit **quebra**: `ProtectSystem=strict` (nix não escreve cache), `MemoryMax=2G` (nix-eval estoura). Serviço saía com **código 0** no meio da task, journal vazio | **Rejeitada por medição.** O caminho certo é o item 1 |
| 3 | Check de import prefixava `"jarvis."` com um `rel` que **já vinha de dentro de `src/`** | `ModuleNotFoundError: No module named 'jarvis.jarvis'` em todo arquivo do pacote | módulo = o próprio `rel` com `/`→`.` |
| 4 | Testes importavam a **cópia stale do `/nix/store`** | `ImportError` em `context_budget` — o patch estava na fonte, o import lia o store | `_source_env()`: prepende `modules/ai/jarvis/src` ao PYTHONPATH |
| 5 | Env de teste tinha **só pytest**, sem as deps do projeto | `No module named 'requests'` em testes que importam requests/numpy/httpx | `pkgs.jarvis-test-env` = deps reais (`base.pythonDeps`) + pytest |
| 6 | **Validação falha mesmo com `new_fails=[]`** | Falha **pré-existente** (baseline) reprova a task → patch limpo nunca converge | **ABERTO** — ver abaixo |

## O bug 6 (aberto) é o mais importante

Medido:

```
summary:    "2 passed, 2 failed, 0 skipped"
new_fails:  []          ← nada novo
veredito:   Validation failed → retry → Loop Detected
```

As 2 falhas são **pré-existentes** (estão no baseline). O patch não quebrou
nada. Mas a task é reprovada, gasta os 3 retries e é bloqueada.

Isso é semanticamente errado: a pergunta não é "o teste passou?", é **"o patch
introduziu alguma falha?"**. Se `new_fails` é vazio, o patch está limpo.

Suspeita de implementação: `run_targeted_tests`/`validate_change` reportam
`passed = (returncode == 0)` do pytest, ignorando a distinção
baseline vs novo que o harness já calcula em `new_fails`.

**Não aceitar "convergência 0 porque o modelo não acerta" antes de resolver
isto.**

## Regra que daí decorre (a Lição 1,PAYOFF de 6 horas)

> Nunca atribuir uma falha ao modelo sem confirmar, **no mesmo registro de
> evidência**: (a) `new_fails` **não vazio**, e (b) nenhum bug de ambiente
> (import faltando, `ModuleNotFoundError`, path do store, `jarvis.jarvis`).

Enquanto (a) ou (b) falhar, o dado mede o **verificador**.

## Tentativas rejeitadas (para não repetir)

1. Achar um `python` com pytest no PATH do serviço → **não existe nenhum**.
2. `nix develop --command` por validação → **quebra no unit** (item 2).
3. `makeSearchPathOutput` sobre `propagatedBuildInputs` → o atributo Nix não
   bate com o `nix-support` real; pytest não entrava no path.
4. `python3` bare no PATH do unit → **não existe**
   (`/run/current-system/sw/bin/python3` não existe).

A via que funciona é a **canônica do Nix**: `python3.withPackages`, com as deps
reais do projeto + pytest, passado aoPython via `JARVIS_TEST_PYTHON`. O Nix
**escolhe**; o Python **obedece e se certifica** (`import pytest`) antes de usar.

## Pitfall de método (custou um rebuild)

Rodar a suíte com `-k "not e2e and not integration and not nightwatch"`
(1434 passed) **escondeu** a quebra: 2 testes de nightwatch usam um
`fake_run_command` com a assinatura antiga e o `env` novo quebrou o build.
A suíte **inteira** é **1462**. Foi o gate do `rebuild-host.sh` que pegou —
não confie no filtro de suíte para isso.

## Outra lição: branch do nightwatch

Editar código do harness com o nightwatch rodando **perde o trabalho**: o
abort da branch descarta o edit não commitado. Aconteceu **duas** vezes hoje.
Protocolo: parar → `main` → editar → testar → **commit** → só então rodar.
