# CLAIMS — append antes de assumir tarefa (data-hora | agente | tarefa)
2026-09-24 00:0X | opencode-glm | models.nix spec prep + veredito bench (DONE dc8b7dc)
2026-09-24 00:02 | opencode-muse | codacus harvest oldest-newest + FINDINGS.md
2026-09-24 00:13 | opencode-muse | codacus harvest DONE 57/59 FINDINGS.md (2 newest sem legenda)
2026-09-24 00:20 | opencode-glm-A | ciclos 1-2 DONE: FINDINGS(2 vídeos) + bench spec 2x refutado (159ba7a) + dl ternary27 rodando | PRÓXIMO: bench ternary-27B offload + A3B -n-cpu-moe
2026-09-24 00:20 | opencode-muse | continua loop-A passo 1: URL ternary-27B corrigida + download relancado
2026-09-24 00:21 | opencode-muse | CORRECAO claim anterior: download ternary-27B JA em curso pelo GLM (2.5GB+), meu curl cancelado, sem interferencia
2026-09-24 00:22 | opencode-muse | Q1 retry legendas bcGO7xre46o xbedfuqYQYA
2026-09-24 00:24 | opencode-muse | Q2 ver log DPO-r32 ERROR (Kaggle)
2026-09-24 00:4X | opencode-glm-A | A3B MoE-CPU bench: 1.9-3.5 t/s INVIÁVEL + load-mode none não carrega — LINHA FECHADA. Ternary-27B baixado (7.17GB OK). PRÓXIMO CICLO: bench ternary-27B (router-stop → -ngl parcial p/ ~1.3GB sobrando... ATT: precisa ~5GB GPU → parar router, -ngl X p/ caber, resto CPU ternário prism; régua 22 t/s no 3060 inteiro)
2026-09-24 07:36 | opencode-muse | Q6 push DPO-r32 v3 (save_total_limit=1 anti-ENOSPC)
2026-09-24 07:42 | opencode-muse | Q1 retry-2 legendas (pos-01:30)
2026-09-24 07:40 | opencode-glm-A | RETRATAÇÃO: strong tier CONFIRMADO 32 t/s (flags casa). Ciclo-3 A3B 'inviável' era config minha errada. Router OK. Fila: ternary-27B bench + A3B-30B re-test c/ flags casa
2026-09-24 08:0X | opencode-glm-A | DISCREPÂNCIA p/ resolver c/ bench: BINARIES.md (Muse) diz upstream INVÁLIDO p/ MoE, mas strong=32 t/s veio do upstream (idem sweep casa b64739e). BRAÇO NOVO no sweep-plan: ik_llama vs upstream no 35B (ngl45+ncmoe35) — quem vencer atualiza BINARIES.md. LIÇÃO de higiene: git status ANTES de commit (meu commit varreu staging do Muse — 12 files misturados)
2026-09-24 08:1X | opencode-glm-A | CLAIM braço 1: ternary-27B prism -ngl parcial (rodando agora)
2026-09-24 08:20 | opencode-muse | Q7 push DPO-r32 v4 (enable_gpu=true, v3 era CPU)
2026-09-24 09:0X | opencode-glm-A | BINÁRIO NOVO prism-b10735 (12.8, launcher run-prism-b10735.sh) resolve offset do 27B; lição R2: baixei layout errado (Q2_0 padrão) — PG: PQ2_0 (27B) baixando; 8B=g64. Q2_0 27B errado (7GB) removido
2026-09-24 08:38 | opencode-muse | vigia v4 + fila finetunes (dono saiu)
2026-09-24 09:4X | opencode-glm-A | CHAIN 27b+strong-t6 executada (resultados /tmp/draft/chain27.log)
2026-09-24 09:5X | opencode-glm-A | R6 canal remoto: @jarvis_lab_bot ativo (comandos /remember /vault /agent p/ dono na rua); sunshine nunca configurado (setup pendente em casa)
2026-09-24 10:2X | opencode-glm-A | ⚠ commit ceb5079 MISTO (meu router b10735 + batch do Muse: sunshine.nix, skills.py+tests, telegram.py, agent/devtools). REGRA NOVA: path-limited commits (git commit <paths>), bare-commit PROIBIDO c/ 2 agentes. Rebuild-host lançado p/ ativar b10735 no router + sunshine (se módulo do Muse quebrar, switch falha atômico = safe)
2026-09-24 14:2X | opencode-glm-A | BRAÇO 6 RESOLVIDO: ik 35,8-36,0 t/s > upstream 32 (+11%) — BINARIES.md do Muse VALIDADA; router já aponta strong->ik (sistema ótimo). bench-llm.sh consolidado+selftest OK (72,9 t/s). ik rebuild novo FALHOU (NIX_ENFORCE_NO_NATIVE x march=native) — parked; ik velho segue. pkill -f self-match footgun: usar [b]racket pattern
