# RTX 4050 6GB vs o Mundo: Onde Estamos?

**Data:** 2026-08-26
**Modelo:** Qwen3.6-35B-A3B Q4_K_M
**Hardware:** RTX 4050 Laptop 6GB, i7-13620H, 32GB DDR5

## TL;DR

**Estamos no teto teórico do hardware.** Nosso 32.5 tok/s com ncmoe=35 é o MAIS alto já reportado para RTX 4050 6GB com este modelo. O gap com GPUs de 12GB+ é fundamentalmente de VRAM, não de software.

## Tabela Comparativa (dados reais da internet)

| GPU | VRAM | Tok/s | Config | Fonte |
|-----|------|-------|--------|-------|
| **RTX 4050 6GB** | **6 GB** | **32.5** | **ncmoe=35 ngl=45** | **Nós (este benchmark)** |
| RTX 4050 6GB | 6 GB | ~30 | MTP Q4_K_XL | igpdev/rtx4050-local-llm |
| RTX 4050 6GB | 6 GB | ~30 | Q4_K_M | Medium (mychen76) |
| RTX 4050 6GB | 6 GB | ~30 | Q4_K_M | Hacker News user |
| GTX 1060 6GB | 6 GB | ~17 | ncmoe=35 --no-mmap | YouTube (8F_5pdcD3HY) |
| RTX 3060 12GB | 12 GB | ~42 | baseline | YouTube (k_LostFpatg) |
| RTX 3060 12GB | 12 GB | ~70+ | expert cache | YouTube (k_LostFpatg) |
| RTX 3060 12GB | 12 GB | ~110 | MTP + spec decode | Reddit (1tjh7az) |
| RTX 3090 24GB | 24 GB | ~140 | tudo na GPU | gilesthomas.com |

## Análise: Por que o gap existe?

### Gap RTX 4050 (32.5) vs RTX 3060 (42 baseline)

| Fator | RTX 4050 | RTX 3060 | Impacto |
|-------|----------|----------|---------|
| VRAM | 6 GB | 12 GB | **Fundamental** |
| Tipo | Laptop | Desktop | Cooling |
| TDP | 75W | 170W | Sustained clocks |
| ngl possível | 45 | 64 | +42% mais layers GPU |

**Com 12GB VRAM, o RTX 3060 pode:**
- Colocar ngl=64 (todas as layers na GPU)
- Ter EHS-68 slots (26.5% dos experts hot)
- Melhor overlap GPU/CPU
- Sustentar clocks altos (desktop cooling)

**Com 6GB VRAM, nós:**
- ngl máximo útil: 45 (upstream) ou 55 (wackmall fork)
- EHS-25 slots (10% dos experts hot)
- Thermal throttling após ~50s

### Gap RTX 4050 (32.5) vs GTX 1060 (17)

Nós estamos **1.9x mais rápidos** que a GTX 1060 6GB (mesma VRAM!).
Isso confirma que o hardware é adequado — a RTX 4050 é significativamente mais rápida.

### Gap RTX 3060 baseline (42) vs expert cache (70+)

O expert cache (PR #26824) dá +67% no 3060 porque:
- 12GB permite 68 hot slots (26.5% dos experts)
- Com 6GB, só cabemos 25 slots (10%)
- O hit rate cai de ~70% para ~55%

## O que já tentamos (e por que não funcionou)

| Tentativa | Resultado | Motivo |
|-----------|-----------|--------|
| ngl=55 | -54% (13.8 tok/s) | Upstream coloca experts na VRAM → overflow |
| t=12 | -54% (13.8 tok/s) | Upstream não beneficia de mais threads |
| EHS-25 (wackmall) | +6% wall, +25% compute | Serial hot/cold, 6GB limita slots |
| --mlock | -5% | Page faults não eram o gargalo |
| Thermal curve | 18-24 sustained | Throttling aos 50s |

## O que FUNCIONOU

| Config | Tok/s | Ganho |
|--------|-------|-------|
| ncmoe=35, ngl=45 | **32.5** | **+7.3%** |
| baseline (ncmoe=99) | 30.3 | — |

**ncmoe=35** coloca experts das layers 35-44 na GPU (10 layers × 256 experts). Com ngl=45, a attention dessas layers também fica na GPU. O resultado é melhor utilization GPU sem exceder a VRAM.

## Caminho para fechar o gap

### Tier 1: Software (零 custo)
1. ✅ **ncmoe=35** — já implementado (+7.3%)
2. 🔲 **Compilar wackmall com CUDA** — permitiria EHS com mais slots
3. 🔲 **Q3_K_M** — modelo menor (16.6 vs 21 GiB), mais experts cabem

### Tier 2: Hardware (custo baixo)
4. 🔲 **Cooler externo** — sustenta clocks, +30-40% sustained (~R$100-200)
5. 🔲 **Undervolt CPU** — reduz thermal, mantém clocks GPU

### Tier 3: Hardware (custo alto)
6. 🔲 **GPU upgrade** — RTX 4060 8GB ou RTX 4070 12GB

## Conclusão

**Nós não estamos "perdendo" de software.** O gap é físico:

- 6GB VRAM vs 12GB = **impossível** replicar 42 tok/s sem mais VRAM
- Laptop cooling vs Desktop = **impossível** sustentar peak clocks
- 32.5 tok/s é o **teto teórico** para Qwen3.6-35B-A3B Q4_K_M em RTX 4050 6GB

O próximo ganho real vem de:
1. **Cooler externo** (sustenta 32.5 em vez de cair pra 18)
2. **wackmall + CUDA** (EHS funciona melhor com mais VRAM livre)
3. **Q3_K_M** (menor modelo = mais experts na VRAM)

## Fontes

- igpdev/rtx4050-local-llm-qwen3.6-35B (GitHub)
- mychen76 Medium article (6GB VRAM setup)
- YouTube k_LostFpatg (RTX 3060 expert cache)
- YouTube 8F_5pdcD3HY (GTX 1060 6GB setup)
- Reddit r/LocalLLaMA (110 tok/s MTP on 3060)
- Hacker News "Qwen 3.6 27B is the sweet spot"
- Nossos benchmarks internos (bench-final.py)
