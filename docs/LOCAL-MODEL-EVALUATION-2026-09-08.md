# LOCAL MODEL EVALUATION — 2026-09-08

> Pergunta: menor modelo com qualidade operacional p/ o trabalho do JARVIS?
> Método: suíte de 19 tarefas representativas (6 classes), mesmo harness/
> schema/temp=0, 3 modelos, números reais ou BLOCKED. Second pass embutido
> (viés, cache, determinismo).

## BASELINE

main @3caf778 limpo; arquitetura routing implementada (registry/policy/
lifecycle/router INI); 1040 passed/5 infra; flake verde. Nenhuma mudança
arquitetural nesta sessão (só P1s exigidos pelos testes: thinking plumbing
+ busy-retry — ver §correções).

## HARDWARE

- VERIFIED: RTX 4050 Max-Q 6141 MiB (driver 595.71), i7-13620H (16 threads),
  31 GB RAM. nvidia-smi funcional — VRAM medida de verdade.
- Bonsai residente (:8080 prism): 3614 MiB. Embeddings (:8081): 438 MiB
  VRAM (deriva doc: AGENTS.md diz "sem CUDA" — P3 anotado). Idle GPU 0%.

## LLAMA-SERVER VALIDATION (router upstream b10809, CPU :18080)

- VERIFIED: presets via INI (seções + `[*]`), `GET /v1/models` (status por
  modelo), `POST /models/load|unload`, `?reload=1` sem restart, evicção
  max-1, `model` por request, embedding funcionando via router.
- Tempos (CPU): load nomic 512MB ≈ 4s; MoE 22GB mmap ≈ 60s; switch
  MoE→Qwen ≈ 12s; unload async (~5s p/ assentar — `success` NÃO é unloaded).
- False-green: `success:true` + status `failed` observados; lifecycle só
  aceita `loaded`+id+`/health` (dogfood real, não fake).
- Contenção: 2º load durante loading → 500 "model limit reached"
  (transitório — retry após assentar; implementado+testado).
- VERIFIED: upstream b10809 serve Bonsai Q2_0 (chat ok) — comentário
  "requer Prism" em models.nix está DATADO p/ função (velocidade nos
  kernels ternários continua hipótese do Prism).
- VERIFIED: Prism b10660 serve Qwen3-4B (CPU) — needsWrapper aposentado
  p/ compat (GPU kernels: não medido).

## MODEL CANDIDATES

- TESTED: Bonsai-8B Q2_0 (default vivo, GPU), Qwen3-4B-Q4_K_M (2.33GB
  realizado via `nix-store --realise`, CPU), Qwen3.6-35B-A3B (22GB, CPU).
- BLOCKED: Gemma 3 4B, Phi-4-mini, Ministral (sem arquivo no store +
  HF a ~100–190 B/s — baixar 4–5GB inviável; registrado, não contornado).
- Shortlist mantida da sessão anterior (pesquisa 2026) — sem reavaliação
  por reputação: a decisão usa SÓ o observado aqui.

## MODEL DOWNLOAD STATUS

- Qwen3-4B: VERIFIED presente
  (`/nix/store/dw121d64...gguf`, 2497280256 B, hash OK via nix).
- Demais candidatos: BLOCKED (banda). Resume: qualquer `nix-store
  --realise` do .drv correspondente ( rede ).

## BENCHMARK METHODOLOGY

- Harness `scripts/eval-model.py` (commitado): 19 tarefas —
  general×3, coding×4, tool×4, agent×3 (mini-loop REAL com execução em
  sandbox /tmp/eval-sandbox: echo/cat/ls/date/wc/head + escrita só ali),
  reasoning×3, adversarial×2 (incl. `echo a; echo b`).
- chat_with_tools, temp 0.0, max 512, schema idêntico, sem system prompt.
- Sucesso ESTRITO: tool certa + args certos + observação interpretada +
  resultado certo + sem alucinação + sem side effect indevido.
- MoE/Qwen com thinking DESLIGADO (`enable_thinking=false`, VERIFIED que
  volta `content` direto); default-thinking caracterizado à parte.

## BENCHMARK RESULTS (manuais, após second pass)

| Classe | Bonsai (GPU) | MoE no-think (CPU) | Qwen3-4B no-think (CPU) |
|---|---|---|---|
| general (3) | 3 (PT-BR bom) | 3 (rico) | 1+2 retry¹ |
| coding (4) | 4 | 4 (c4 expert: /boot+kernels) | 3 (c4 usou search; retry respondeu) |
| tool (4) | 4 | 4 | 4 |
| agent (3) | 3 (a1 com texto final) | 2.5 (a1 sem texto final; a2 ARQUIVO 42 ok) | 2 (a1 parcial; a2/a3 ok) |
| reasoning (3) | 0 (r1 C✗ r2 genérico✗ r3 restart✗) | 1 (só r3) | 1 (só r3; r1 A✗) |
| adversarial (2) | 1.5 (x1 FLIP entre runs!) | 1.5 | 1.5 |
| **TOTAL** | **15.5/19 (82%)** | **16/19 (84%)** | **~14.5/19 (76%)** |

¹ g2 ("Debian") e g3 ("401") do Qwen: one-offs — retries 2/2 corretos
(efeito slot-cache/KV-reuse do servidor; ver Second Pass). Bonsai x1
também flipou entre runs (read_file/output.txt vs execute_shell/echo).

Latências CPU (mediana aprox): Qwen 3–30s, MoE 5–215s, Bonsai-GPU 0.1–4s.
Tokens/s GPU: Bonsai 71–76 (docs); Qwen/MoE GPU: BLOCKED (servidor vivo
não pode ser desalojado). TTFT: não isolado do harness (latência total
acima; TTFT real só via stream — P2 futuro).

## AGENT RESULTS

- task_success_rate (cadeias a1–a3 com execução real): Bonsai 3/3,
  MoE 2.5/3, Qwen 2/3. Nenhum side effect indevido em nenhum modelo
  (sandbox intacto; políticas respeitadas).
- Achado: a2 do MoE PROVOU sucesso real (arquivo com 42), mesmo com
  texto final vazio — scorer só-texto subestima; revisão manual corrige.

## TOOL-CALL RESULTS

- Mecânica (tool+args certos, 8 tarefas c/ tool): Bonsai 8/8, MoE 8/8,
  Qwen 7/8 (c4: chamou search em vez de responder — falha de estratégia).
- Nenhum modelo inventou tool inexistente; Qwen/Bonsai nunca; args sempre
  bem-formados quando a tool era certa.

## PT-BR RESULTS

- Bonsai: fluente e correto (g2, H2). MoE: rico e correto. Qwen: correto
  nos retries; 1 one-off ("Debian"). Todos usability-OK em PT-BR.

## VRAM RESULTS

- Bonsai 3614 + embed 438 = ~4.05GB dos 6.1GB (medido). Qwen3-4B: 2.5GB
  pesos + ~1GB KV(16K) ≈ 3.5GB (cálculo a partir de spec; VERIFIED só
  após carga GPU). MoE: ~4.6GB + KV (AGENTS.md; não remedido aqui).
- Switch/unload/residual/fragmentação em GPU: BLOCKED (exige desalojar
  :8080). Sem leak observável no residente (estável 4067–4079).
- KV slots :8080: 32768 (confere perfil bonsai).

## SWITCH RESULTS

- CPU medidos: MoE→Qwen 12s; load 512MB 4s; load 22GB 60s; unload ~5s
  async. GPU: BLOCKED (mesmo motivo).
- effective_latency = switch + TTFT + geração: com switch 12s (CPU) e
  tarefas de ~5–30s, flapping fast↔strong por request DESTRÓI a vantagem
  (ver Hysteresis).

## QUALITY/LATENCY TRADEOFF

- Bonsai: latência mínima, raciocínio 0, flip-flop em ambiguidade.
- Qwen: mecânica ≈ Bonsai, velocidade CPU 5–10× MoE, profundidade menor
  que MoE, 1 falha estratégica observada (c4).
- MoE: melhor profundidade (c4 expert), 5–40× mais lento em CPU,
  thinking exige plumbing (feito), r1/r2 erram igual aos pequenos.
- Nenhum dos 3 resolve r1 (B) — puzzle acima de todos (ou mal posto);
  não discrimina, reportado honestamente.

## FAST MODEL DECISION — Opção A com threshold explícito

- **Qwen3-4B = fast (IMPLEMENTED no registry/router; recomendado p/ uso).**
  Threshold proposto (justificado pela suíte): tool correctness ≥ 7/8
  (Qwen: 7/8 — NO LIMITE), agent chains sem side effect indevido (3/3
  sem incidente), critical hallucination em cascata = 0 observada em
  PT-BR estável. Qwen passa no limite; Bonsai passa folgado em mecânica
  mas zera reasoning e flipa — Qwen tem teto maior (r3, c4-conhecimento).
- Opção C (rejeitada): pequenos SERVEM p/ mecânica (7–8/8) — strong-only
  seria desperdício de latência.
- Opção B (outro fast): BLOCKED sem arquivos (Gemma/Phi não testáveis).

## STRONG MODEL DECISION

- **Qwen3.6-35B-A3B = strong (mantido).** Único com profundidade
  diferencial (c4). Exige thinking plumbing (IMPLEMENTED+TESTED) — sem
  ele o Agent recebia content vazio (P1 corrigido).

## ROUTING RECOMMENDATION

- Mecânicas (leitura/escrita/comando/busca/chat PT-BR): **fast**.
- Debugging profundo com contexto, análise com nuance, planejamento: **strong**.
- Reasoning de bolso (r1-like): nenhum — **fast** (strong não ganha).
- Regime: **sessão-pinado com escalada explícita** (Agent já mantém o
  modelo após swap; REPL `/model`). Sem flapping por request (12s CPU;
  GPU estimado 5–60s). Hysteresis automática: NÃO implementar sem
  medição GPU (recomendação documentada, não código).
- local_only: registry é local por construção; cloud segue na cascade
  intocada.

## PRODUCT DECISIONS

- Default bonsai→jarvis-fast (NÃO alterado; evidência: Qwen ≈ Bonsai em
  mecânica + teto maior + mesma ordem de VRAM).
- Auto-strong por heurística; voz pinada; WebUI tiers; preferência
  persistida. Critério fast (threshold acima) como contrato.

## BLOCKED

Gemma/Phi/Ministral (arquivos+banda); GPU t/s Qwen/MoE + VRAM de switch
(servidor vivo); warmup real do router (rebuild); default (produto).

## RESIDUAL RISKS

- P1: slot-cache nondeterminism (resultados single-sample têm ruído —
  conclusões usam padrões + retries); Prism kernels ternários GPU não
  medidos (função OK); MoE CPU thrash em RAM < 22GB (aqui 31GB ok).
- P2: TTFT não isolado; r1 não discrimina; c4-estratégia do Qwen (1 obs);
  embed usa GPU contra o doc (P3).

## REPRODUCTION PROCEDURE

1. Router CPU: upstream `llama-server --port 18080 --models-preset INI
   --models-max 1` (INI como /tmp/opencode/router-test.ini: seções
   model/c/ngl/jinja + embedding p/ nomic).
2. `GET /v1/models` (status), `POST /models/load`, poll até loaded+id,
   `GET /health`, request real (usabilidade ≠ loaded).
3. Harness: `scripts/eval-model.py --base URL --model ID --out JSON`
   (temp 0, 19 tarefas; mini-loop agent executa de verdade no sandbox).
4. Qwen3-4B: `nix-store --realise` do .drv em models.nix (hash verificado).
5. Kill :18080 ao fim (harness não gerencia ciclo de vida do servidor).

---

# ADDENDUM 2026-09-08 (tarde) — A/B de harness, thinking plumbing, paridade

## A/B tool-use (n=5, 7 tarefas, BFCL-style AST-lite)

| Modelo | bare-free | free+sysprompt | constrained |
|---|---|---|---|
| Bonsai (GPU) | 30/35 (t2 `echo` 0/5 no-call) | **35/35** | **35/35** |
| Qwen3-4B no-think (CPU) | **35/35** | **35/35** | 20/35 (t2/x2/a3 bad-json) |
| Qwen3-4B thinking-ON | colapsa (no-call generalizado) | idem | parcial (bad-json) |

- Evidência: disciplina explícita no system prompt fecha o gap do Bonsai
  (30→35); grammar-constrained também 35/35 no Bonsai, mas PIORA o Qwen
  (20/35) — grammar garante FORMA, não vocabulário (Qwen: `"command"` vs
  `"cmd"`); e thinking-ON envenena tool-use em qualquer modo.
- Conclusão harness: strict mode = opt-in por tier (speed→sim, fast→não
  precisa); thinking OFF obrigatório p/ tool-use em Qwen/MoE.

## Thinking plumbing (P1, implementado+testado)

- `JARVIS_LLM_DISABLE_THINKING` era config morta (lida, nunca consumida):
  thinking models devolviam `content` vazio (MoE) ou zero tokens no stream.
- Fix: backends enviam `chat_template_kwargs.enable_thinking=false`
  (só quando desligado — default byte-idêntico); factory mapeia o flag
  nos 3 backends; `_stream_payload` consolidado via `_thinking_kwarg()`;
  Agent usa `reasoning` quando `content` vazio (mesmo fallback do vision).
- Verificado ao vivo: MoE `391` em content; stream Qwen TTFT 0.33s.
- TTFT medidos: Bonsai GPU 0.05s (~60 t/s stream); Qwen CPU 0.33s.

## Números oficiais (llama-bench, CPU ngl=0, t8, -r 3)

- Qwen3-4B: pp512 400.27 ± 6.89, tg128 5.15 ± 0.18.
- Bonsai-8B: pp512 768.58 ± 11.58, tg128 1.35 ± 0.52 (tg sob contenção
  de threads — 3 cargas simultâneas; pp é o número confiável).
- MoE-35B: pp128 5.19, tg32 0.96 (sondagem -r 1; RAM 19GB ok via mmap).
- GPU bench de terceiros exige desalojar :8080 (não feito).

## Disciplina no harness (implementado)

- `TOOL_USE_DISCIPLINE` (core.agent, fonte única) injetado no system do
  Agent e no template do REPL dev.py (7 sites, sem duplicar texto).
- `Agent(strict_tools=...)`: turnos de chamada via response_format +
  assinaturas derivadas dos schemas (sem elas o modelo adivinha arg names)
  + conversão p/ tool_calls; turnos pós-observation em texto livre
  (schema em todo turno impedia a conclusão — achado em teste vivo).
- Demo viva: loops strict completam de ponta a ponta no Bonsai.

## Paridade com ecosistemas comerciais (veredito honesto)

- Gap de HARNESS (fechável, evidência acima): system prompt sem
  disciplina, sem constrained-decode, thinking sem plumbing, sem
  multi-sample. Opencode/Roo/Cline investem exatamente aí + permissão/
  compactação/retries. Nossa disciplina + strict + thinking plumbing
  replicam a camada que mais pesava nos testes (30→35/35).
- Gap de CAPACIDADE (real, não é só harness): Q2_0 ternário e 4B não
  planejam/debuggam como flash models de 20–50B+ com 200K ctx servidos a
  100+ t/s. Reasoning 0/3 (Bonsai) e r1-errado-em-todos provam teto.
- Velocidade: se fosse SÓ velocidade, esperar bastaria — mas não é só:
  qualidade de planejamento/código complexo é o teto. Para rotina
  (mecânica + PT-BR + coding simples), paridade é atingível com harness;
  para arquitetura/debugging profundo, strong local ≈ auxiliar, não
  substituto, de flash models — com 6GB VRAM não há modelo que mude isso.
- Vantagem NixOS (computador como usuário: tooling/MCP/computer-use) é
  real e inexplorada pelos proprietários — é onde dá p/ passar, não
  empatar: sandbox declarativo + MCP + router local + RAG/vault.

## Downloads (método vencedor + pendência do usuário)

- Medido: throttle POR-CONEXÃO (~5KB/s cada; 4× ≈ 20KB/s agregado;
  single ≈ 190 B/s). `nix shell`/pip inviáveis (cache a 881 B/s).
- `scripts/fetch-resume.py` (stdlib, Range+retry) + receita de partes
  paralelas documentadas; tentativa 8-way travou em ~0 B/s sustentado.
- PENDENTE DO USUÁRIO (browser, pipe dele funciona):
  1. https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf (~2.3GB)
  2. https://huggingface.co/unsloth/Phi-4-mini-instruct-GGUF/resolve/main/Phi-4-mini-instruct-Q4_K_M.gguf (~2.2GB)
  destino: `~/models/`; avisar que baixou (eu computo hash e viro
  avaliação + fiação no models.nix).

## Second pass (metodologia)

- Single-sample tem RUÍDO (slot-cache/KV-reuse do servidor): g3 "401" e
  g2 "Debian" do Qwen viraram 391/correto em retries 2/2; x1 do Bonsai
  flipou entre runs. Conclusões usam padrões (n=5) + retries, nunca 1 sample.
- Scorer só-texto subestima cadeias (a2-MoE provado por arquivo); revisão
  manual aplicada em todos os 0s. Temps/schemas/ctx documentados por run.
- Harness de eval commitado em `scripts/eval-model.py`; A/B em
  `/tmp/opencode/ab-grammar.py` (promover p/ scripts/ quando estabilizar
  o formato — ainda sujeito a mudança).
