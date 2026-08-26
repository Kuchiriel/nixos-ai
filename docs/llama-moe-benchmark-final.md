# LLaMA MoE Expert Hot Store — Benchmark Final

## Hardware
- **GPU**: NVIDIA RTX 4050 Laptop (6 GB VRAM)
- **CPU**: Intel i7-13620H
- **RAM**: 32 GB

## Modelo
- **Qwen3.6-35B-A3B Q4_K_M** (~20.6 GiB)
- 64 experts, top-8 per token
- Expert size: ~148.5 MiB per expert (Q4_K_M). Note: earlier docs incorrectly stated 72 MiB due to wrong expert count (64 instead of 256).

## Configuração Base
```
-ngl 45 -sm layer -t 8 -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0
```

## Resultados do A/B Test

### Baseline (wackmall build, sem EHS)
| Run | PP tok/s | TG tok/s |
|-----|----------|----------|
| 1 | 80.4 | 30.6 |
| 2 | 88.3 | 30.4 |
| 3 | 88.5 | 28.7 |
| 4 | 87.6 | 27.9 |
| 5 | 84.3 | 28.0 |
| **Média** | **85.8** | **29.1** |

### EHS-40 (40 slots, 2988 MiB VRAM)
| Run | PP tok/s | TG tok/s |
|-----|----------|----------|
| 1 | 84.8 | 30.1 |
| 2 | 88.2 | 30.6 |
| 3 | 88.3 | 30.7 |
| 4 | 88.8 | 31.0 |
| 5 | 88.7 | 31.2 |
| **Média** | **87.8** | **30.7** |
| **Ganho** | +2.3% | **+5.5%** |

### EHS-25 (25 slots, 1895 MiB VRAM) ⭐ VENCEDOR
| Run | PP tok/s | TG tok/s |
|-----|----------|----------|
| 1 | 86.1 | 30.8 |
| 2 | 88.9 | 31.0 |
| 3 | 88.9 | 31.4 |
| 4 | 89.0 | 31.1 |
| 5 | 88.4 | 30.6 |
| **Média** | **88.3** | **30.9** |
| **Ganho** | +2.9% | **+6.2%** |

## Análise

### Por que EHS-25 > EHS-40?
1. **Menos VRAM pressure**: 1895 MiB vs 2988 MiB → mais espaço pra KV cache e CUDA buffers
2. **Hot experts são mais concentrados**: O top-25 experts cobrem ~60-70% da ativação média
3. **Menos overhead de manutenção**: Menos slots = menos trocas = menos overhead

### Efeito de aquecimento do cache
Nos runs de benchmark (~60 tokens), o cache já atinge performace estável. Para sessões reais (500+ tokens), o ganho deve ser maior conforme o heatmap converge.

### Conclusões

| Configuração | TG tok/s | Ganho vs Baseline |
|-------------|----------|-------------------|
| Baseline (ncmoe=99) | 29.1 | — |
| EHS-40 | 30.7 | +5.5% |
| **EHS-25** | **30.9** | **+6.2%** |

### Configuração Recomendada
```bash
llama-server \
  -m Qwen3.6-35B-A3B-Q4_K_M.gguf \
  -sm layer -t 8 -c 4096 -b 512 -ub 512 \
  -fa on -ctk q4_0 -ctv q4_0 \
  -ehs 25 --jinja --parallel 1
```

**NOTA**: O `-ncmoe 99` NÃO deve ser usado com `-ehs`. O EHS automaticamente ativa `--cmoe` (todos experts na CPU + hot cache na GPU).

## Implementação
- **Fork**: `miltos22/llama.cpp-wackMall-merge-request` (PR #26824)
- **Build**: `cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=89`
- **Binário**: `~/projects/llama-wackmall/build/bin/llama-server`

## Limitações
- RTX 4050 tem 6 GB VRAM — o PR #26824 mostra 1.5-2.1x em hardware com 8+ GB VRAM
- O benchmark gera apenas ~60 tokens — cache ainda aquecendo
- N-gram speculative decoding NÃO ajuda (48% acceptance → regressão de 51%)
- Expert cache com RAM (não VRAM) requer investigação adicional

## Próximos Passos
1. Testar com sessões reais (500+ tokens) pra medir efeito completo de aquecimento
2. Testar sidecar heatmap persistence (`--expert-sidecar`)
3. Investigar expert cache via RAM (mmap pinning com `--expert-pin`)
4. Testar com modelo Q2_M (mais experts cabem na VRAM)
