# LOOP-STATE — agente A (opencode/glm) · atualizado 2026-09-24 00:20

## Ciclo 1 + 2 CONCLUÍDOS (evidência nos commits)
- T1 transcripts (a parte do agente A): Bonsai-27B + DFlash lidos e extraídos →
  `~/Books/codacus/FINDINGS.md` (agente B = Muse continua a fila oldest→newest).
- T2 bench spec-decode: **REFUTADO 2x** na 4050 — bonsai 72 t/s e Qwen3-4B
  60 t/s, zero ganho com draft/ngram. Commit **159ba7a** (veredito no models.nix
  = anti-regressão: a linha está fechada, não refazer sem hardware novo).
- Download **Ternary-Bonsai-27B-Q2_0_g128** (7.17GB) → `~/models/` RODANDO
  (PID 183386, log /tmp/overnight/dl-ternary27.log) — era ~2h no ritmo do Drive.

## PRÓXIMO CICLO (quem acordar: leia o LOOP-PROMPT e continue daqui)
1. Verificar download ternário-27B (ls -la ~/models/Ternary*; se incompleto,
   retomar com curl -C -).
2. **BENCH ternary-27B com offload parcial** (router pode ficar UP; se OOM,
   parar/reiniciar como nos ciclos anteriores): llama-server -m ~/models/
   Ternary-Bonsai-27B... -ngl ~X (attn na GPU, ~1.3GB livres) + resto CPU
   (kernels ternários prism). Meta: 15-25 t/s = tier "smart-dense" viável.
   Comparar com régua do vídeo: 22 t/s no 3060 inteiro.
3. **BENCH Qwen3-30B-A3B-Q4_K_M** (~/models, 18.6GB) com -n-cpu-moe /
   --cpu-moe offload — régua: 48 t/s no 3060; meta >=15 t/s na 4050.
   Cuidado RAM (32GB; Muse rodando downloads ao lado).
4. Se ternary-27B ou A3B vencerem em qualidade/t/s: propor ao dono (bom dia)
   como tier novo — NÃO trocar default sem ele (regra AGENTS).
5. Binary-27B 3.5GB: descartado p/ cérebro (fabrica convicto — FINDINGS.md).

## Estado geral
- Router :8080 OK (bonsai default intacto). Embeddings/rerank intocados.
- Coordenação: Muse = agente B nos transcripts; FINDINGS.md é o encontro.
- Ternary-27B download em curso. qwen3-coder GGUF = 0 bytes (re-baixar ~12GB,
  decidir com o dono). DPO Kaggle = ERROR (decidir retry com o dono).
- Perícia dia 28: dossiê + roteiro v1 prontos; docs psicólogo chegam de manhã.

## Ciclo 3 (00:20–00:45) CONCLUÍDO
- A3B-30B-Q4_K_M + --cpu-moe: **1.9–3.5 t/s = INVIÁVEL** (laptop CPU não segura
  experts; --load-mode none nem carrega 18.6GB). Linha fechada, registrado.
- **Ternary-Bonsai-27B-Q2_0.gguf baixado OK (7.17GB, ~/models/)** — era o filename
  certo Ternary-Bonsai-27B-Q2_0.gguf (o "g128" não existe; dspark-Q4_1 = drafter
  oficial 27B se um dia precisar).
- Router :8080 OK. Coordenação viva: Muse logou claims (Q1 legendas, Q2 DPO log).
## PRÓXIMO CICLO (assim que ler isto):
1. **BENCH ternary-27B**: parar router → llama-server -m ~/models/Ternary-Bonsai-27B-Q2_0.gguf
   -ngl ~34-38 (deixar ~5.5GB GPU p/ pesos; resto CPU ternário prism; -c 4096 -fa on)
   → 3 reps prompt código (bench-spec.sh como base) → router de volta.
   Régua: 22 t/s no 3060 inteiro; meta >=12 t/s = tier smart-dense viável vs bonsai-72.
2. Se viável: propor ao dono tier "bonsai-27b" p/ tarefas difíceis (não default sem ele).
3. Muse: FINDINGS.md crescendo? ler e virar benchmarks meus.

## Ciclo 4 (07:38) — RETRATAÇÃO + CONFIRMAÇÃO
- **jarvis-strong (Qwen3.6-35B-A3B, flags da casa: ngl45+ncmoe35, upstream bin):
  32.1–32.7 t/s pico (5 reps) — CONFERE com sweep 26/08 (32,9) e memória do dono.**
- Ciclo 3 "A3B inviável" = VEREDITO MEU ERRADO: prism bin + --cpu-moe tudo-CPU
  + ngl99 + sem warmup. MoE offload É viável: ~32 pico / ~19 sustentado.
- Fica na fila: re-testar Qwen3-30B-A3B com flags da casa (secundário);
  bench ternary-27B (baixado); FINDINGS do Muse.
