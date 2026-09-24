# MODEL × HARNESS MATRIX — score é POR MODELO (24/09)

> Regra que este arquivo existe para impedir: **"o harness está ótimo"**.
> Frase inválida sem nomear modelo, binário, layout de quantização e flags.
> Harness = ferramenta; modelo = floors. Mudar de modelo invalida o veredito.

## 1. Throughput medido (RTX 4050 6GB) — não misturar

| Alvo | Binário | Layout | t/s | Fonte |
|---|---|---|---|---|
| **Bonsai 8B ternário** | prism **b10735** (fonte `prism-bin/`) | Q2_0_g64 | **71,6 sustentado** (71,4–72,0; 5 reps) | `bonsai-vs-qwen-2026-09-05.md` |
| Bonsai 8B (re-selftest) | prism b10735 | Q2_0_g64 | **72,9** | `bench-llm.sh` selftest 24/09 |
| Qwen3-4B denso | nix upstream | Q4_K_M | ~10 | 7,2× mais lento que bonsai (mesma doc) |
| Qwen3.6-35B-A3B MoE | **ik_llama.cpp** | Q4_K_M | **35,5** (35,6/35,5) | `overnight-24-09/ik-vs-upstream.log` + `bench-ik35-final` |
| Qwen3.6-35B-A3B MoE | ik | Q4_K_M | **19,25** (ncmoe **36**) | 24/09 — **config pior**, não o bonsai |
| Ternary-Bonsai-27B | prism | PQ2_0 | 3–7 inviável | 24/09 |

**Armadilha registrada (24/09):** "19 t/s" foi lido como se fosse o bonsai.
É o **MoE com `--n-cpu-moe 36`** (35 experts forçados na CPU). O bonsai é
**70+ t/s** e é o mais rápido da casa. MoE ≠ mais lento que o bonsai em
latência de token; ele é **maior/melhor em qualidade** e aceita
`n-cpu-moe 35` (35,5 t/s). A pergunta em aberto: **A3B experts ativos na GPU
nunca foi provado** — `-ngl 45 + ncmoe 35/36` é a única configuração medida
(ATTN na GPU, experts na CPU).

## 2. Scores de harness são POR MODELO

| Run | Modelo | Binário | easy | medium | hard | ptbr | fd | Observação |
|---|---|---|---|---|---|---|---|---|
| v6 (24/09) | bonsai-8B | prism b10735 | 3/3 | 3/3 | 1/3 | — | 0 | hard oscila 1–2/3 = fronteira/ruído |
| v2 (24/09) | bonsai-8B | prism b10735 | 3/3 | 3/3 | 2/3 | — | 0 | lucky H1 via retry |
| ptbr-v2 (24/09) | bonsai-8B | prism b10735 | — | — | — | **3/3** | 0 | 6,1s; **PT-BR não é a fraqueza** |
| MATRIX (24/09) | jarvis-fast (Qwen3-4B) | nix upstream | *rodando* | | | | | |
| MATRIX (24/09) | jarvis-strong (35B-A3B) | ik | *rodando* | | | | | |

### Fraquezas do bonsai-8B (medidas, 24/09)
- **Semântica/path jail**: repete `~`/`~projects` (agora normalizado), caça
  `auth.json` por confusão semântica (H1) → 1–2/3 em hard.
- **Compounding**: mesmo `str_replace` 5× (guard anti-compounding agora
  recusa a 3ª; H2 segue falha honesta ~1/5).
- **PTY/tool-calling em PT-BR**: **NÃO confirmado** — 3/3 quando a infra está
  de pé. O 0/3 anterior era **server órfão de bench** segurando 4,5GB → router
  500 → suíte contou como falha do modelo. **Preflight obrigatório agora.**
- Ternário (`Q2_0_g64`) + fork prism: rápido, mas qualidade/token fica atrás
  do MoE — daí a matriz existir.

## 3. Infra antes de medir (obrigatório, 24/09)

1. `harness-suite.py` roda **preflight**: uma completion real (não só
   `/health` — o b10735 responde `ok` com o modelo unloaded) e **aborta sem
   medir** se falhar. Score com infra caída = veredito inválido.
2. `bench-llm.sh` tem **guard de VRAM**: aborta se outro `llama-server`
   segura >1,2GB (órfão de bench). `nvidia-smi` antes de benchar.
3. 1 modelo por vez na 6GB. `--` antes das flags do server (getopts `-n`
   come `-ngl`).

## 4. Tier PT-BR (sonda, não escada)

E/M/H ficam em inglês (comparabilidade entre modelos; o local rende mais).
Tier `ptbr` (3 tasks: acento-exato, extração APENAS, negativa "não crie")
é **sonda de deficiência** — a língua real do dono. Score separado, nunca
somado no ladder.
