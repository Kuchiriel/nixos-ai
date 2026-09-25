# MODEL-SAFETY — onde moram os modelos e o que NUNCA apagar

> Regra-mãe (AGENTS.md §PROIBIÇÕES.1): nunca apague dado. Incidente que
> criou este arquivo (25/09/2026): `Ternary-Bonsai-27B-PQ2_0.gguf` (7.2GB)
> baixado sem caber na VRAM (6GB) — apagado por ordem explícita do dono;
> no mesmo dia o Bonsai 8B "sumiu" da vista (estava no nix store, não em
> `~/models`). Custo de baixar de novo: tempo + banda + quota. Evitar.

## Inventário (fonte: disco em 25/09/2026)

| Modelo | Onde | Tamanho | Papel |
|---|---|---|---|
| Ternary-Bonsai-8B-Q2_0_g64.gguf | `/nix/store/nc3rnnsmz17mnhbqfry1xiw3lk5sni0x-...` (via `models.nix llm-bonsai`) | 2.3GB | default router :8080 |
| Ternary-Bonsai-8B-unpacked (HF) | `~/.cache/bonsai-unpacked/` | 16GB | finetune/quant base |
| Qwen3-4B-Q4_K_M.gguf | `~/models/` | 2.5GB | jarvis-fast :8083 |
| Qwen3-30B-A3B-Q4_K_M.gguf | `~/models/` | 18.5GB | jarvis-strong :8084 |
| Qwen3.5-4B / Qwen3.6-35B Uncensored | `~/models/` | 2.7GB / 21-23GB | raw profiles |
| gemma-3-4b, Phi-4-mini, xLAM-2-8B | `~/models/` | — | reserva |

## Regras

1. **Antes de apagar qualquer `.gguf`/pesos**: conferir este inventário +
   `models.nix` (quem referencia?) + `lsof` (servidor usando?) + perguntar
   ao dono. Sem exceção para arquivos >1GB.
2. **Antes de baixar modelo novo**: checar VRAM (6GB, 1 residente) e disco;
   27B+ não cabe — nem baixar (lição 25/09).
3. **Arquivo do nix store some?** Não foi apagado — foi GC. `nix-store --realise`
   ou rebuild traz de volta (o `sha256` no `models.nix` garante o mesmo byte).
4. **Recomendado Prism p/ 8B** (não o que temos): `Ternary-Bonsai-8B-Q2_0.gguf`
   (g128, 2.18GB, "lossless for ternary") — o nosso `Q2_0_g64` (2.31GB) é o
   pack grupo-64, válido mas maior. Troca = decisão do dono (baseline muda).
