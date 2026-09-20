# FAILURE TAXONOMY (20/09 — com atribuição §37)

| # | Falha | Camada | Evidência | Estado |
|---|---|---|---|---|
| 1 | Alucinação sem grounding (12345/42/13) | MODEL | EXP-A C0 | VERIFIED |
| 2 | Atração por números do contexto (exemplo, lesson, enunciado) | MODEL×CONTEXT | EXP-A/C/D | VERIFIED |
| 3 | Lesson com valores episódicos degrada (1/3, read-loop) | KNOWLEDGE | EXP-C B2/B3 | VERIFIED |
| 4 | Confusão recall→lessons 3/3 | TOOL/MCP | EXP-E | VERIFIED |
| 5 | Troca tool por resposta direta (nix 0/3) | MODEL | EXP-E | VERIFIED |
| 6 | Read-first mesmo incapaz (git→read_file) | MODEL | EXP-D | VERIFIED |
| 7 | Stale artifact passa world_check | BENCHMARK | EXP-C fase1 | FIXED (flag+testes) |
| 8 | approval_callback morto (sombra de human_approve) | HARNESS | código+EXP-A setup | OPEN (doc; fix=remover ou ligar) |
| 9 | Exemplo numérico contamina controle | BENCHMARK | EXP-A rodada 2 | OPEN (guia: exemplos neutros) |
| 10 | Teto: baseline 3/3 sem headroom (JSON simples) | BENCHMARK | EXP-C v1 | KNOWN (task +difícil) |
| 11 | Read-path degrada p/ "" silencioso | KNOWLEDGE | recon código | OPEN |
| 12 | Approval gap MCP vs Agent | TOOL | recon código | OPEN (boundary, §51) |
| 13 | 3 esquemas tools + 4 shadow | TOOL | recon código | OPEN |
| 14 | Vault duplo homônimo | KNOWLEDGE | recon código | OPEN |
| 15 | Dev loop sem completion gate (rc=0 texto) | HARNESS | recon código | OPEN |
| 16 | Variância domina n=1 (H1) | ENVIRONMENT | pré-existente | KNOWN (n≥5) |
