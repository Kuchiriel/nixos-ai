# Benchmark Infrastructure Audit — 2026-09-01

## A) DIAGNÓSTICO DO ESTADO ATUAL

### O que existe

O monorepo possui **7 forks do llama.cpp** e **5+ scripts de benchmark**, mas
**nenhum deles suporta Bonsai Ternary** (Q2_0 ternary é formato exclusivo do PrismML).

### Forks disponíveis

| Fork | Localização | Compilado? | CUDA? | Suporta Q2_0 ternary? |
|------|-------------|-----------|-------|----------------------|
| upstream llama.cpp | `llama.cpp/`, `upstream-llama.cpp/` | Via Nix | ✅ | ❌ |
| PrismML (pre-built) | `prism-bin/llama-prism-b10660-e311ed3/` | ✅ Binário | ✅ | ✅ |
| PrismML (source) | `prism-llama.cpp/` | ❌ | — | Sim (fonte) |
| ik_llama.cpp | `ik_llama.cpp/` | ❌ | — | ❌ |
| wackmall | `llama-wackmall/` | ❌ | — | ❌ |
| moe-cache | `moe-cache-llama.cpp/` | ❌ | — | ❌ |

**Problema imediato:** O PrismML binary (`llama-server`, `llama-bench`) precisa de
`libcudart.so.12` que não está no LD_LIBRARY_PATH. O Nix store tem o library
(`/nix/store/.../lib/libcudart.so.12`) mas o binário PrismML não foi construído
via Nix, então não herda as dependências automaticamente.

### Modelos disponíveis

| Modelo | Tamanho | Localização | Formato |
|--------|---------|-------------|---------|
| Qwen3.6-35B-A3B Q4_K_M | 21 GB | Nix store | GGUF padrão |
| Ternary-Bonsai-8B Q2_0 | 2.1 GB | `~/projects/models/` | GGUF ternary |
| mmproj-BF16 (Qwen) | 861 MB | Nix store | GGUF vision |
| bge-reranker-v2-m3 Q4_K_M | 438 MB | Nix store | GGUF reranker |
| nomic-embed-text-v2-moe Q8_0 | 512 MB | Nix store | GGUF embedding |

**Bonsai 8B Q2_0:** Modelo válido (header GGUF confirmado). 2.1 GB — cabe
inteiro na VRAM (6 GB) com espaço para KV cache. Potencialmente 40-80+ tok/s
se o PrismML binary funcionar.

### Scripts de benchmark existentes

| Script | O que mede | Fork usado | Limitações |
|--------|-----------|-----------|------------|
| `benchmark-official.py` | Peak + sustained, thermal control, order bias | upstream | Só Qwen, hardcoded paths |
| `bench-final.py` | TG/PP throughput | upstream | Sem thermal, hardcoded |
| `bench-one.sh` | Single config | upstream | Muito simples |
| `quick-bench.sh` | A/B comparison | upstream | Sem sustained |
| `proper-benchmark.sh` | 10-run com clocks | wackmall | Fork diferente |
| `systematic-benchmark.sh` | Multi-config sweep | wackmall | Fork diferente |
| `mlock-benchmark.sh` | --mlock impact | wackmall | Fork diferente |
| `a-b-compare.sh` | A/B simples | upstream | Muito simples |

**Problema:** Cada script usa um fork diferente (upstream ou wackmall). Nenhum
usa PrismML. Nenhum suporta Bonsai. Nenhum compara forks lado a lado.

### Benchmarks anteriores (docs/benchmarks/results/)

Há 8 runs de 2026-08-26 com `benchmark-official.py`. O mais completo é
`20260826-controlled` que testou order bias e thermal control.

Resultados relevantes (Qwen3.6-35B-A3B, upstream):
- baseline (ncmoe=99): 30.4 tok/s median
- ncmoe35: 32.2 tok/s median
- ehs25: 23.3 tok/s median

## B) LISTA DOS BENCHMARKS EXISTENTES

### Infraestrutura de medição

1. **`benchmark-official.py`** — O mais robusto:
   - Peak vs sustained distinction
   - Thermal control (GPU temp threshold)
   - Order bias testing (reversed config order)
   - Hardware telemetry (VRAM, GPU temp, SM clock, power)
   - Cooldown between configs
   - Statistical analysis (median, mean, stdev, P10, P90)
   - Salva dados brutos em `docs/benchmarks/results/<timestamp>/`

2. **Coleta de métricas** (não automatizada):
   - `nvidia-smi` para VRAM/temp/clocks (usado em proper-benchmark.sh)
   - `/proc/stat` para CPU (usado em systematic-benchmark.sh)
   - `curl /health` e `curl /v1/chat/completions` para tok/s

### Ferramentas PrismML

3. **`prism-bin/llama-bench`** — Benchmark tool do PrismML (não funciona sem CUDA libs)
4. **`prism-bin/llama-server`** — Server do PrismML (idem)

### Forks com benchmarks embutidos

5. **`ik_llama.cpp/scripts/`** — compare-llama-bench.py, tool_bench.py
6. **Todos os forks** — `tools/llama-bench` (benchmark tool C++)
7. **Todos os forks** — `scripts/server-bench.py`

## C) LACUNAS QUE IMPEDEM COMPARAÇÃO CIENTÍFICA

### Críticas (impedem comparação)

| # | Lacuna | Impacto | Esforço para resolver |
|---|--------|---------|----------------------|
| 1 | **PrismML binary não roda** — precisa de libcudart.so.12 no LD_LIBRARY_PATH | Bonsai não pode ser testado | Baixo (env wrapper) |
| 2 | **Nenhum script suporta Bonsai** — todos hardcoded para Qwen 21GB | Comparação impossível | Médio (parameterize) |
| 3 | **Nenhum script compara forks** — cada script usa 1 fork | Não sabemos qual fork é melhor | Médio |
| 4 | **Sem medidor de prefill vs decode separado** — só tok/s total | Não sabemos onde está o gargalo | Baixo (LLM já reporta) |

### Importantes (afetam qualidade da comparação)

| # | Lacuna | Impacto | Esforço |
|---|--------|---------|---------|
| 5 | **Sem comparação de VRAM entre modelos** — Bonsai 2GB vs Qwen 21GB | Não comparável em resource usage | Baixo |
| 6 | **Sem teste de capacity** — quantos requests simultâneos cabem | Não sabemos throughput real | Médio |
| 7 | **Sem teste de tool calling** — só text completion | Não reflete uso real (agent loop) | Alto |
| 8 | **Sem teste de long context** — só 4K ctx | Não testa cenário real (32K) | Médio |

### Menores (melhorias desejáveis)

| # | Lacuna | Impacto |
|---|--------|---------|
| 9 | Scripts usam paths hardcoded do Nix store | Não portável |
| 10 | Sem HTML dashboard para comparar runs | Visualização manual |
| 11 | Sem automação de "run all forks + models" | Trabalho manual |

## D) ALTERAÇÕES NECESSÁRIAS (se implementadas)

**Nenhuma alteração de código foi feita nesta sessão.** Apenas auditoria.

Se implementadas, as alterações prioritárias seriam:

1. **Wrapper para PrismML** — Script que define LD_LIBRARY_PATH e executa os binários
2. **Parameterização do benchmark-official.py** — Aceitar modelo e binário como args
3. **Comparador de forks** — Script que roda o mesmo benchmark em N forks e compara

## E) COMANDOS PARA EXECUTAR TESTES

### Testar PrismML binary (quando LLM estiver disponível)

```bash
# Encontrar CUDA libs
CUDA_LIB=$(find /nix/store -name "libcudart.so.12" -path "*/lib/*" | head -1)

# Testar PrismML server com Bonsai
cd ~/projects/prism-bin/llama-prism-b10660-e311ed3
LD_LIBRARY_PATH="$CUDA_LIB:$(pwd)" ./llama-server \
  -m ~/projects/models/Ternary-Bonsai-8B-Q2_0.gguf \
  --host 127.0.0.1 --port 8090 \
  -c 4096 -t 8 -ngl 99 \
  --jinja

# Testar PrismML bench
LD_LIBRARY_PATH="$CUDA_LIB:$(pwd)" ./llama-bench \
  -m ~/projects/models/Ternary-Bonsai-8B-Q2_0.gguf \
  -ngl 99 -t 8
```

### Rodar benchmark existente (com Qwen)

```bash
cd ~/projects/nixos-ai
nix develop --command python3 scripts/benchmark-official.py --config baseline
```

### Comparação manual Bonsai vs Qwen (quando PrismML funcionar)

```bash
# Bonsai (via PrismML)
cd ~/projects/prism-bin/llama-prism-b10660-e311ed3
LD_LIBRARY_PATH="$CUDA_LIB:$(pwd)" ./llama-server \
  -m ~/projects/models/Ternary-Bonsai-8B-Q2_0.gguf \
  --host 127.0.0.1 --port 8090 -c 4096 -ngl 99

# Qwen (via upstream Nix)
nix run nixpkgs#llama-cpp -- --server \
  -m /nix/store/...-Qwen3.6-35B-A3B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8080 -c 4096 -ngl 45 --n-cpu-moe 35

# Mesmo prompt, medir tok/s manualmente:
for i in 1 2 3; do
  curl -s http://127.0.0.1:PORT/v1/chat/completions \
    -d '{"model":"test","messages":[{"role":"user","content":"Explain quantum entanglement."}],"max_tokens":100}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Run {$i}: {d[\"usage\"][\"completion_tokens\"]} tokens')"
done
```

## F) RECOMENDAÇÃO DO PRÓXIMO EXPERIMENTO

### Prioridade 1: Fazer PrismML binary funcionar

O gargalo imediato é que o PrismML binary não roda porque precisa de CUDA libs.
Isso é um fix de 5 minutos:

```bash
# Criar wrapper script
cat > ~/projects/prism-bin/run-prism.sh << 'EOF'
#!/bin/bash
CUDA_LIB=$(find /nix/store -name "libcudart.so.12" -path "*/lib/*" | head -1)
export LD_LIBRARY_PATH="$CUDA_LIB:$(dirname "$0")/llama-prism-b10660-e311ed3"
exec "$(dirname "$0")/llama-prism-b10660-e311ed3/$@"
EOF
chmod +x ~/projects/prism-bin/run-prism.sh
```

### Prioridade 2: Benchmark Bonsai 8B Q2_0

Com PrismML funcionando, o primeiro benchmark deve ser:
- Modelo: Bonsai 8B Q2_0 (2.1 GB)
- Flags: `-ngl 99 -c 4096 -t 8`
- Métricas: tok/s, VRAM, temp, prefill vs decode
- Comparar com Qwen 4B (mesma faixa de tamanho)

### Prioridade 3: Comparação justa Bonsai vs Qwen

| Métrica | Bonsai 8B Q2_0 | Qwen3-4B Q4_K_M | Qwen3.6-35B-A3B Q4_K_M |
|---------|---------------|-----------------|------------------------|
| Tamanho | 2.1 GB | 2.5 GB | 21 GB |
| VRAM necessária | ~2.5 GB | ~3 GB | ~21 GB |
| Cabe no RTX 4050? | ✅ inteiro | ✅ inteiro | ❌ (75% na CPU) |
| Formato | Ternary Q2_0 | Padrão Q4 | Padrão Q4 |
| Fork necessário | PrismML | Qualquer | Qualquer |
| Parâmetros ativos/token | ~8B | ~4B | ~3B |

**A ironia:** Bonsai 8B tem 8B parâmetros mas Q2_0 ternary. Qwen 4B tem 4B
parâmetros mas Q4_K_M. O Bonsai pode ser mais lento por ter mais parâmetros
ativos, OU mais rápido por caber inteiro na VRAM. Só o benchmark resolve.

### O que NÃO fazer agora

- Não alterar agent_loop, nightwatch, harness
- Não alterar configurações do Hyper-V/VM
- Não declarar que Bonsai é melhor sem benchmark
- Não mexer no NixOS para favorecer um fork
