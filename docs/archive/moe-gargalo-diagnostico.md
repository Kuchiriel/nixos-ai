# Diagnóstico do Gargalo MoE — Decode Path

## Hardware
- GPU: RTX 4050 (6GB VRAM)
- CPU: i7-13620H (6P+8E cores)
- RAM: 32GB DDR5

## Modelo
- Qwen3.6-35B-A3B Q4_K_M
- 48 layers, 64 experts/layer, 3 active per token

## Configuração Atual
```
-ngl 45 -ncmoe 99 -sm layer -t 6 -c 4096
```

## Gargalo Identificado: CPU-Bound Expert Computation

### Evidência

| Dado | Valor | Interpretação |
|------|-------|---------------|
| GPU utilization | 44-46% | GPU idle ~55% do tempo |
| TG t=4 | 30.02 | Menos threads = mais lento |
| TG t=6 | 30.83 | Baseline |
| TG t=8 | 31.28 | +6% vs t=6 |
| TG t=12 | 14.75 | E-cores prejudicam |

### Por que o GPU fica idle

Com `-ncmoe 99`, o pipeline por camada é:

```
1. GPU: Attention (Q, K, V, RoPE, SDPA)
2. GPU: Router (gate_inp × hidden → softmax → top-k)
3. GPU: Expert Selection (ids)
4. CPU: MUL_MAT_ID (3 experts × [n_embd, n_ff_exp] × [n_ff_exp, n_embd])
5. GPU: Aguarda resultado do CPU
6. GPU: Next layer
```

O step 4 é o gargalo. O CPU precisa:
- Ler pesos de 3 experts da RAM (mmap)
- Computar 3 matmuls
- Escrever resultado
- Sincronizar com GPU

Enquanto o CPU faz isso, o GPU fica idle.

### Não é PCIe

Com `-ncmoe 99`:
- Expert weights ficam em CPU RAM (mmap'd)
- Não há transferência H2D para experts
- O resultado do MUL_MAT_ID é escrito em buffer CPU
- GPU lê o resultado via buffer compartilhado ou DMA

O bottleneck é **CPU compute**, não **bandwidth**.

### Thread Analysis

| Threads | TG (t/s) | Observação |
|---------|----------|------------|
| 4 | 30.02 | Under-utiliza cores P |
| 6 | 30.83 | Baseline (6 P-cores) |
| 8 | 31.28 | Marginal (+1.3%) |
| 10 | 14.88 | E-cores lentos arrastam |
| 12 | 14.75 | Mais E-cores = pior |

**Conclusão:** 6-8 threads é o sweet spot. E-cores são prejudiciais para MoE compute.

## Soluções Possíveis

### 1. Expert Hot Store (PR #26563) — RECOMENDADO

**O que faz:** Cacheia experts mais quentes na VRAM do GPU.

**Mecanismo:**
- Heatmap rastreia frequência de ativação por expert
- Top-S experts copiados pra VRAM
- GPU computa cached experts diretamente
- Só cold experts passam pelo CPU

**Resultado medido (Qwen3.6-35B-A3B):**
- Q2_M: 33→57 tok/s (1.72x)
- Q5_K_P: 17→36 tok/s (2.07x)

**Nosso hardware:**
- 6GB VRAM total
- ~3GB usados por attention + KV cache
- ~3GB disponíveis para expert cache
- ~25% dos experts (48/192 layers × 64 experts)

**Estimativa:** 1.3-1.5x improvement (mais conservador que PR porque temos menos VRAM)

### 2. Otimização de Threads — JÁ FEITO

- t=8 dá +6% vs t=6
- Limitado por diminishing returns
- E-cores são prejudiciais

### 3. Poll Tuning — JÁ TESTADO

- poll=50 já é ótimo
- poll=0/25 piora performance

### 4. KV Cache — JÁ OTIMIZADO

- q4_0 para K e V
- Flash attention habilitado

## Recomendação

A otimização mais impactante é **implementar o expert hot store** do PR #26563. Isso moveria os experts mais quentes pra GPU, eliminando o bottleneck CPU e potencialmente dobrou a performance.

Para implementar:
1. Clonar o branch do PR #26563
2. Compilar com `-ehs` flag
3. Testar com diferentes budgets de VRAM
4. Medir cache hit rate

Alternativa: Upgrade para GPU com mais VRAM (RTX 4060 8GB ou RTX 3060 12GB) permitiria colocar mais experts na GPU naturalmente.

## Referências

- PR #26563: Expert caching (miltos22)
- RFC #24528: MoE expert cache discussion
- Discussion #27149: Expert-Aware SSD Streaming
- Blog: HuggingFace MoE offload guide
