# Auditoria dos itens abertos em CYCLE-4..9 (21/11)

Varredura dos 7 relatórios + `CYCLE-9-PLAN.md` e verificação do estado atual no
código/host. Nada foi instalado, apagado ou ativado.

## Classificação

| item (origem) | estado hoje | evidência |
|---|---|---|
| Crash tardio `Popen([])` / `IndexError` (C4–C6) | **RESOLVIDO** | `core/devtools.py:658` (`if not cmd`); `core/security.py:292` registra a causa; `test_security.py` 10/10 |
| `approval_callback` morto (C9) | **RESOLVIDO** | `core/router.py:472` injeta; `core/agent.py:916,941,955` consome; testes `-k approval` 22/22 |
| `str_replace` como resposta arquitetural para E1-shape (C8) | **DISPONÍVEL** | presente em `cli/dev.py`, `core/tool_surface.py`, `core/validator.py` |
| Agent-loop via API bloqueado por créditos (C9) | **MITIGADO** | API V2 `/api/session/<id>/prompt` operacional; `fleet-dispatch` usa wake steer via coord/hub |
| Referência externa NIM 6× timeout (C8) | **MITIGADO** | gate/model registry e MiniMax NIM medidos; A/B remoto rodou no Kaggle |
| Harbor / Terminal-Bench C-D (C9) | **POLICY-BLOCKED** | `harbor`/`uv` ausentes; docker agora OK e usuário no grupo docker, mas ADR-005 §10 diz "Harbor só pós-kernel". Instalar exige decisão |
| R8-shape / E1-shape (C6–C9) | **LIMITE DO MODELO** | reprovação byte-exata é do modelo, não do harness; manter como regression, não "fixar" no checker |
| L9 0/9 e L10+ (C4/C9) | **ABERTO / DEFERIDO** | fronteira honesta do modelo; sem planner novo (ADR-005) |
| `kb weekly` e `lint-comportamental` (C9) | **ABERTO** | zero referências no código; itens do plano nunca implementados |
| Formato de observação menos contaminante (C6) | **ABERTO** | experimento não executado; C8 mostrou que presentation contamina |

## Linha de tempo consolidada

- C4–C6: world-observable e falha de serialização; crash corrigido depois.
- C7–C8: fidelidade byte-exata e whitespace; `str_replace` é a saída
  arquitetural, não mais um ajuste de benchmark.
- C9: calibração externa parada; o que mudou desde então foi o runtime
  (ADR-005) e o gate de modelos, não o Harbor.

## Decisão

A dívida "CYCLE-4..9 com itens abertos (Harbor BLOCKED por framework ausente)"
está **parcialmente resolvida e mais precisa**: dois itens críticos foram
corrigidos, dois foram mitigados, Harbor mudou de bloqueio técnico para
decisão de produto, e o restante é limite de modelo/deferido. Não instalar
Harbor nem reabrir L9 sem autorização.
