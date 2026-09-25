# AUDITORIA — SO para LLM + entropia do monorepo (25/09)

Duas auditorias, tudo medido. **Nada foi mudado** — as recomendações que
involvem mudança esperam teu OK (regra da casa: config do host pede OK).

## PARTE 1 — O Linux está otimizado pra rodar LLM?

### Já está bom (não mexer)
| Item | Estado | Por quê está ok |
|---|---|---|
| CPU governor | `performance` | máximo para inferência CPU-bound (MoE com experts na CPU) |
| Frequência | 400MHz–4.7GHz, Turbo ligado (`no_turbo=0`) | escala completa |
| PCIe | **Gen4 x4** | máximo da 4050 laptop |
| GPU pstate | **P0** (performance) | não dorme entre chamadas |
| Clocks GPU | 3105 MHz SM / 8001 MHz mem | teto do card |
| IO scheduler NVMe | `none` | o melhor para NVMe (zero seek) |
| swappiness | 10 + **zram 15,5GB** | page cache agressivo, swap comprimido em RAM |
| governor boost | ok | — |

### Oportunidades reais (ordenadas por ganho/esforço)
1. **THP = `madvise`** → testar `always`. Em inferência CPU (nosso caso do
   MoE: experts na CPU) huge pages reduzem TLB miss. Ganho típico
   documentado: alguns % a 2 dígitos, **medir antes/depois** com
   `bench-llm.sh` (nunca no achismo).
2. **NVIDIA persistence mode = `Disabled`** → `nvidia-smi -pm 1` + tornar
   persistente no serviço. Evita re-init do driver a cada uso (latência de
   primeira chamada e churn de VRAM). Ganho pequeno por chamada, mas
   remove uma classe de erro ("server error" no primeiro uso).
3. **Serviços sem prioridade (CPUWeight/IOWeight = não setado)** →
   `llama-cpp-server` compete em igualdade com o resto do sistema. Como o
   MoE é manual e segura ~18GB, dá para fixar `CPUWeight=90` no serviço do
   router e `IOWeight` alto, para que o SO não roube CPU no meio da
   geração. Também avaliar `OOMPolicy=stop` (hoje `stop` no router: bom).
4. **Zram com 5GB usados** = pressão de memória real. O MoE + browser +
   loop de harness cabem mal em 32GB. Duas saídas: reduzir o que roda junto
   (parar o browser durante bench), ou dar ao serviço do LLM um
   `MemoryHigh` menor que o sistema para que ele seja a primeira vítima em
   vez do desktop.
5. **Kernel/sched**: nada evidente. `prefetch` de IRQS? Só medir se o
   throughput oscilar (o log do bench já mostra 41,2 t/s em rajada vs 30 t/s
   depois — vale investigar **thermal**, não config).

### O que a pesquisa manda medir antes de mexer
- Toda mudança de knob → `scripts/bench-llm.sh` antes e depois, **com o
  mesmo modelo/flags**, e registrar em `docs/benchmarks/`. Mudança sem
  veredito = entropia.
- Governor/THP/persistence afetam **todo** o sistema, não só o LLM: medir
  com e sem, e só manter se o ganho for real.

## PARTE 2 — Entropia (a bagunça)

### /tmp = **45GB** (o maior item, e é lixo)
| Caminho | Tamanho | O que é |
|---|---|---|
| `/tmp/kdpo-r32-log/dpo-r32` | **20GB** | run de treino DPO (24/09 02:10) — **nenhum processo segurando** |
| `/tmp/opencode/kaggle-out` | 7,8GB | saídas de Kaggle (rvc/applio) |
| `/tmp/kdpo3` | 5,4GB | outro run de treino/eval |
| `/tmp/pip-unpack-hnyu3ox_` | 3,9GB | temp de pip que não foi limpo |
| outros | ~8GB | logs/transcripts antigos |

Ação: `/tmp` é volátil por natureza; **esses 45GB não custam nada ao
sistema, mas entulham o disco e mascaram o que importa**. Pergunta real:
o DPO de 20GB tem valor (checkpoint) ou é resíduo? Decisão do dono.

### Nix store = 76GB, **1468 caminhos mortos** prontos pro GC
Maiores mortos: sources de 300–350MB (cópias de source repetidas).
`nix-collect-garbage` reclaim tipicamente 5–15GB sem risco (builds são
reconstruíveis). Ação: segura, maker de disco.

### Repos sujos = **10** com lixo não versionado
- `guia-renamer-pro`: 8 modificados + `supabase/migrations/prospeccao_status_whatsapp.sql` untracked
- `karaok`: 14 modificados + `archive/`, `docs/`, `src/karaok/mic.py` untracked (14 arquivos de trabalho real por comitar ou descartar — **decisão do dono**)
- `llama.cpp` **e** `ik_llama.cpp`: `FORK-STATUS.md` untracked nos dois (duplicata)
- forks (`llama-wackmall`, `prism-llama.cpp`, `llama.cpp`): 1 modificado cada (mudanças de build ours)
- `Corretor`, `OTServer_UPGRADE`, `red-teaming`, `mudream_notifier`: 1–3 modificados

Regra que já existe e funciona: commit path-limited, nunca `git add -A`
(por isso o agente do harness já sujou dois commits sozinhos hoje).

### Scripts = **9 variantes de bench** (duplicação)
`quick-bench.sh`, `proper-benchmark.sh`, `systematic-benchmark.sh`,
`bench-one.sh`, `a-b-compare.sh`, `bench-final.py`, `benchmark-official.py`,
`acceptance_bench.py` + `bench-llm.sh` (a canônica). As 8 primeiras são
arqueologia — mover para `scripts/archive/` deixa o inventário verdadeiro.

### Docs
166 arquivos, **nenhum com mais de 90 dias sem toque** → não há podre
cronológica. O risco é **duplicata sem owner** (ex.: MODEL-HARNESS-MATRIX vs
BENCHMARK-MATRIX vs INVENTORY-DRAFT). Índice único em `docs/README.md`
resolveria.

### Ordem sugerida (do maior ganho ao menor risco)
1. GC do Nix (seguro, ~5–15GB)
2. Decidir o destino do DPO de 20GB (só o dono decide)
3. `scripts/archive/` nos 8 benches legados
4. Commitar ou descartar o que está untracked (7 commits pequenos, nenhum
   destrutivo)
5. THP/persistence/CPUWeight — **só com medição antes/depois**

## Honestidade
Este relatório é um **diagnóstico**, não uma execução. Nada foi apagado,
nada foi reconfigurado. Os itens 1 e 5 mudam o sistema e precisam do teu OK
explícito — o resto é hygiene de repo e decisão do dono sobre o que é
descartável.
