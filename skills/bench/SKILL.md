---
name: bench
description: Run a valid local GPU bench on RTX 4050 6GB — right binary per model case, pre-bench checklist, evidence format. Use when benchmarking inference, comparing t/s, or validating a verdict.
---

# bench — bench válido de inferência local

## 1. Binário certo (fonte: docs/models/BINARIES.md — sem exceção)

| Caso | Binário |
|---|---|
| Ternário Bonsai (Q2_0) | `~/projects/prism-bin/llama-prism-b10660-e311ed3/llama-server` |
| MoE (A3B) + `--cpu-moe` | `~/projects/ik_llama.cpp/build/bin/llama-server` |
| Denso / spec-decode / DFlash / ngram | `/nix/store/*llama-cpp-*/bin/llama-server` (upstream nix) |

Router :8080 é prism — servir por ele NÃO valida bench de denso/MoE/spec.
Binário errado = veredito inválido, mesmo com números bons (incidentes D2/D5).

## 2. Antes de rodar (colar no STATE)

- [ ] modelo + quant + caso
- [ ] binário (path exato) + `--version`
- [ ] flags + nº reps (mín 3) + prompt fixo + n tokens
- [ ] GPU livre (`nvidia-smi` 0% — não benche junto com outro agent)
- [ ] router parado se precisar da VRAM; DEVOLVIDO após (`systemctl start llama-cpp-server`)

## 3. Protocolo

1. baseline SEM o truque (3 reps) → COM o truque (3 reps), mesmo prompt/binário
2. ranges sobrepostos = ganho zero (não médias soltas)
3. veredito + flags no models.nix comment (anti-regressão) ou commit

## 4. Réguas conhecidas (RTX 4050 6GB, não refazer — linhas encerradas)

- bonsai 8B Q2_0 (prism): ~72 t/s · spec/draft/ngram = zero ganho
- Qwen3-4B Q4 (upstream): ~60 t/s · spec/draft/ngram = zero ganho
- A3B MoE (ik + cpu-moe): meta >=15 t/s · spec em MoE = piora
- ternary-27B Q2_0 (prism, offload parcial): meta >=12 t/s
