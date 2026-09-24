# BINÁRIOS E FORKS — qual usar, sem exceção

> Router rodando ≠ binário certo. O router usa prism; bench no binário errado
> INVALIDA o veredito (incidentes D2/D5, 24/09 — veredito no prism refeito).

## Tabela (fork → binário → uso)

| Caso | Binário EXATO | Usos VÁLIDOS | Usos INVÁLIDOS |
|---|---|---|---|
| Ternário Bonsai (Q2_0, binário) | `~/projects/prism-bin/llama-prism-b10660-e311ed3/llama-server` | Bonsai 8B/27B, `binary-*`/`ternary-*` | dense Q4, MoE, spec-decode, DFlash |
| MoE (Qwen3-A3B, 30B/35B) | `~/projects/ik_llama.cpp/build/bin/llama-server` | MoE + `--cpu-moe`/`-n-cpu-moe` | denso, ternário |
| TUDO o mais (benches, dense, spec, DFlash) | `/nix/store/*llama-cpp-*/bin/llama-server` (upstream nix) | Qwen3/Phi/Gemma/Llama dense, spec-decode, ngram, DFlash | ternário Bonsai, MoE offload |

## Proibidos
- `prism-llama.cpp/` (fonte sem build), `llama.cpp/` e `nixpkgs/` (track only,
  NÃO editar), `llama-wackmall/` (só via wrapper), `~/models/qwen3-coder/*0-byte*`
  (download morto — não usar).

## Regra de validade (vale p/ qualquer agente, qualquer bench)
1. ANTES do bench: rode `<bin> --version`, cole path+versão na evidência (STATE).
2. Binário fora da tabela p/ o caso = veredito AUTOMATICAMENTE inválido,
   mesmo com números bons. Sem path registrado = sem veredito.
3. Router (:8080) é prism — servir por ele NÃO valida bench de denso/MoE/spec.

## Checklist pré-bench (colar no STATE)
- [ ] modelo + quant + caso (ternário/MoE/denso/spec)
- [ ] binário (path exato da tabela) + `--version`
- [ ] flags + n reps + prompt fixo
- [ ] router parado/devolvido após (se parou)
