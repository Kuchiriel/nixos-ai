# Resource Calculation — REPL Optimization

> Baseado no hardware real e configuração models.nix

## Hardware

| Componente | Capacidade |
|-----------|------------|
| CPU | i7-13620H (10C/20T, 5.0 GHz boost) |
| RAM | 32 GB DDR5 |
| GPU | RTX 4050 6 GB |
| VRAM | 6141 MiB |

## Model Config (host profile)

| Parâmetro | Valor |
|-----------|-------|
| Model | Qwen3.6-35B-A3B Q4_K_M |
| Context | 32768 tokens (32K) |
| Batch | 1024 |
| Ubatch | 1024 |
| GPU Layers | 45 |
| Threads | 12 |
| KV Cache | q4_0 (f16 would be 2x) |
| ncmoe | 36 |

## VRAM Budget

| Componente | Tamanho |
|-----------|---------|
| Modelo (Q4_K_M) | ~2400 MiB |
| KV Cache (q4_0, 32K) | ~1024 MiB |
| Compute Buffer | ~1000 MiB |
| Overhead | ~200 MiB |
| **Total** | **~4624 MiB** |
| **Disponível** | **~1517 MiB** |

## Context Window Budget

| Componente | Tokens |
|-----------|--------|
| Total context | 32768 |
| System prompt (Roo Dev) | ~15000-20000 |
| Available for conversation | ~12768-17768 |
| Output reserve (20%) | ~6554 |
| **Effective available** | **~6214-11214** |

## REPL Optimal Settings

### Chunk Sizing

| Configuração | Valor | Razão |
|-------------|-------|-------|
| Max messages in history | 20 | Evita growth ilimitado |
| Compact threshold | 70% of context | ~22938 tokens |
| Compact target | 60% of threshold | ~13763 tokens |
| Max tool output | 5000 chars | ~1250 tokens |
| Max file read | 200 lines | ~500 tokens |

### Session Management

| Configuração | Valor | Razão |
|-------------|-------|-------|
| Max turns per question | 30 | Flexível para tarefas complexas |
| Auto-compact | Yes | Prevents context overflow |
| Session persistence | Yes | Resume after condensing |
| Repo map | Yes | Ajuda o modelo a navegar |

### Reasoning Levels

| Level | Contexto | Uso |
|-------|----------|-----|
| low | Sem reasoning display | Tarefas simples |
| medium | Reasoning oculto | Default |
| high | Reasoning visível | Debug/complexo |

## Capacidade do REPL

### Sessão Curta (< 5 min)
- ~10-15 turns
- Contexto: ~25K tokens
- Tools: ~20 chamadas
- Output: ~5K tokens

### Sessão Média (5-30 min)
- ~30-50 turns
- Contexto: ~30K tokens (com compact)
- Tools: ~50-100 chamadas
- Output: ~10K tokens

### Sessão Longa (> 30 min)
- Turns ilimitados (com compact)
- Contexto: sempre ~30K (com compact)
- Tools: ilimitadas
- Output: ilimitado

### Limitações

1. **Context window**: 32K é modesto para coding agent
2. **Thermal throttling**: throughput degrada após ~40s
3. **Model capacity**: Qwen3.6-35B é bom mas não Excel
4. **No LSP**: sem type information
5. **No git auto-commit**: cada edit precisa de commit manual
