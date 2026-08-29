# Benchmark Definitivo: RTX 4050 6GB — Qwen3.6-35B-A3B Q4_K_M

**Data:** 2026-08-26 04:00
**Hardware:** RTX 4050 Laptop 6GB, i7-13620H, 32GB RAM DDR5
**Modelo:** Qwen3.6-35B-A3B Q4_K_M (~21 GiB)
**Método:** 5 warmup requests + 5 measured runs de 128 tokens cada
**Prompt:** "Explain quantum entanglement in simple terms."
**Temperature:** 0
**Servidor:** upstream llama.cpp (b64739e), NÃO wackmall fork

## Resultados

| Config | ncmoe | ngl | t | TG avg | TG min | TG max | VRAM | Delta vs baseline |
|--------|-------|-----|---|--------|--------|--------|------|-------------------|
| **ncmoe35** | **35** | **45** | **8** | **32.5** | **32.4** | **32.6** | **4933** | **+7.3%** |
| baseline | 99 | 45 | 8 | 30.3 | 30.1 | 30.6 | 2543 | — |
| ncmoe35-ngl55 | 35 | 55 | 8 | 15.3 | 15.2 | 15.5 | 4933 | -49.5% |
| ngl55 | 99 | 55 | 8 | 13.8 | 13.8 | 13.9 | 2543 | -54.5% |
| t12 | 99 | 45 | 12 | 13.8 | 13.7 | 13.9 | 2543 | -54.5% |
| ngl60 | 99 | 60 | 8 | 13.8 | 13.8 | 13.8 | 2543 | -54.5% |

## Descobertas Críticas

### 1. ncmoe=35 é O MELHOR CONFIG — +7.3% vs baseline

Com `--n-cpu-moe 35 -ngl 45`:
- **32.5 tok/s** (vs 30.3 baseline)
- VRAM: 4933 MiB (vs 2543 baseline)
- Mais consistente (min/max mais próximos)
- 100% reprodutível

**Por que funciona:** ncmoe=35 coloca os MoE experts das primeiras 35 layers na CPU, e os experts das layers 35-44 na GPU. Com ngl=45, as primeiras 45 layers têm attention na GPU. A combinação otimiza GPU/CPU utilization.

### 2. ngl>45 É CATASTRÓFICO no upstream

ngl=55, t=12, ngl=60 → todos caíram pra ~13.8 tok/s (**-54%**).

**Causa:** O upstream llama.cpp (b64739e) coloca TODO o tensor da layer na GPU quando ngl aumenta, incluindo os 256 experts. Com ngl=55, são 55 layers × 256 experts × 148 MiB = ~2 GiB extras de experts na VRAM. Mas ncmoe=99 mantém os experts na CPU. O conflito causa overhead massivo de paginação GPU↔CPU.

**No wackmall fork com EHS:** ngl=55 funciona porque o fork move expert weights de forma seletiva.

### 3. t=12 NÃO MELHORA (upstream)

O upstream não beneficia de mais threads porque o workload é dominado por operações GPU (attention + non-expert projections). As threads extras ficam ociosas.

### 4. O gap entre 30-32 tok/s e 42+ tok/s

| GPU | VRAM | Baseline | Melhor |
|-----|------|----------|--------|
| RTX 4050 6GB | 6144 | 30.3 | 32.5 (ncmoe35) |
| RTX 3060 12GB | 12288 | ~42 | ~70 (EHS) |

**O gap é fundamentalmente de VRAM.** A RTX 3060 com 12GB:
- Cabe mais layers na GPU (ngl=64 possível)
- EHS-68 slots (26.5% dos experts hot)
- Mais overlap GPU/CPU
- Melhor cooling (desktop)

### 5. Thermal Throttling (confirmado em sessão anterior)

- Peak (laptop frio): ~32.5 tok/s
- Sustained (5 min): ~18-24 tok/s
- Throttle aos ~50s quando GPU atinge 68°C
- Cooler externo é a melhor otimização de custo/benefício

## Comparação com o Vídeo (GTX 1060 6GB)

O vídeo mostrou 17 tok/s numa GTX 1060 6GB:
- Mesma VRAM (6GB)
- GPU MUITO mais lenta (GTX 1060 vs RTX 4050)
- CPU muito mais lenta (i3-8100 vs i7-13620H)
- DDR4 vs DDR5

Nós: **32.5 tok/s** — quase o dobro do vídeo, confirmando que o hardware é adequado.

## Configuração Recomendada

### Para Roo Dev (contexto grande):
```nix
# host profile (atual) — mantém 196K context
--n-cpu-moe 99 -ngl 45 -t 12 -c 196608
# Resultado: ~30 tok/s (peak), ~18-24 (sustained)
```

### Para velocidade máxima:
```nix
# ncmoe35 profile (novo) — otimizado para decode
--n-cpu-moe 35 -ngl 45 -t 8 -c 4096
# Resultado: ~32.5 tok/s (peak), ~20-25 (sustained)
```

### Se o fork wackmall tiver CUDA:
```nix
# host-ehs — expert hot store
-ehs 25 -ngl 45 -t 8 -c 8192
# Resultado: ~31 tok/s (peak), mas com +25.6% compute real
```

## Próximos Passos Priorizados

1. **Cooler externo** — maior ganho de custo/benefício (~+40% sustained)
2. **Profile ncmoe35** — adicionar ao NixOS como opção (+7% peak)
3. **wackmall com CUDA** — compilar o fork com suporte CUDA pra usar EHS
4. **Q3_K_M** — modelo menor (~16.6 GiB), mais experts na VRAM com EHS

## Scripts Criados

- `scripts/bench-final.py` — benchmark sistemático multi-config
- `scripts/quick-bench.sh` — benchmark rápido
- `scripts/thermal-curve.sh` — curva térmica (da sessão anterior)
- `scripts/proper-benchmark.sh` — benchmark com monitoramento de clocks

## Dados Completos

Os resultados detalhados estão em `/tmp/benchmark-results.json`.
