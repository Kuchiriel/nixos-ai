# CYCLE-9 REPORT — Harbor external calibration (21/09)

## Estado inicial / infra
Suite 1431/0 · L8 WORLD OK · L9 0/12 congelada · sem tuning.
Harbor: **BLOCKED** — framework ausente, daemon permission-denied p/
este usuário, uv ausente, zero referências no repo/sistema (gap exato
em CYCLE-9-PLAN §2; caminho: dono libera docker/host).
Agent-loop via API: **BLOCKED** (~9933 créditos; loops precisam 10-100x).

## Dataset/tasks (verifier = igualdade de bytes / world)
9 probes atômicos (T1, T2-R1, T4, T5, F6, F7, F8, E1, T-fact), n=3,
mesmos prompts p/ API (`google/gemini-3.5-flash-lite`, HTTP direto) e
Bonsai (ciclos 6/8). Células C/D Harbor: NOT INTEGRATED.

## Matriz (API × Bonsai, probe-level)
| Task | API | Bonsai | Diferença | Causa |
|---|---|---|---|---|
| T1/T2-R1/T4/T5/T-fact | 3/3 | 3/3 | nenhuma | CONSISTENT |
| F6 mixed-ws | 3/3 | 0/2 | gap | BONSAI-SPECIFIC |
| F7 blanks | 3/3 | 0/2 | gap | BONSAI-SPECIFIC |
| F8 final-\n | 0/3 | 0/2 | nenhuma | GENERAL (trim de protocolo) |
| E1 compound | 0/3* | agent 0/3 | parcial | GENERAL (*API erra só o \n final; probe Bonsai n/a) |

## Falhas por categoria
MODEL (bonsai-specific): F6, F7. GENERAL: F8, E1-composto.
HARNESS/TOOL/ENV/TASK/VERIFIER/INTEGRATION: n/a neste nível.
UNKNOWN: E1-probe Bonsai (não medido — não comparar).

## Interna ↔ externa (transfer)
- TRANSFER: regra/leitura/serialize/evidência/fato funcionam nos dois.
- CONSISTENT FAILURE: F8/E1 (ambos falham).
- Diferencial real API↔Bonsai = whitespace misto/blanks — estreito e
  específico, NÃO "8B incapaz" (§12: neste protocolo, nestas tasks).
- NON-TRANSFER / FALSE NEGATIVE: sem dados Harbor (BLOCKED).

## Limites / não-medido / hipóteses
- Agent-loop API, Harbor C/D, E1-probe Bonsai, custo total gasto (~3k
  tokens, dentro do saldo).
- Suportada: gap Bonsai é específico (F6/F7), não geral.
- Descartada: "Bonsai falha em tudo que API passa" (5/9 iguais).

## Próximo bottleneck
Docker p/ este usuário (ou host Harbor) + R8-shape permanente +
approval_callback morto. Sem isso, calibração externa não avança;
interna está esgotada no observável (ciclos 1-8).
