# tuning-engines-2026-09-29 — família de tuning de flags do llama.cpp

**Nada aqui foi apagado.** Movido em 2026-09-29 com `git mv`
(histórico preservado). Veredito registrado no commit.

## O que é

Quatro motores de otimização de flags do `llama-server` + os três
wrappers que os invocavam:

| Arquivo | Linhas | Estratégia |
|---|---|---|
| `ga_engine.py` | 636 | Algoritmo genético (seleção/crossover/mutação), fitness = decode t/s |
| `grid_engine.py` | 339 | Grid search focado nos genes sensíveis |
| `fast_tune.py` | 437 | Busca binária direcional (extremos → meia → refina) |
| `llm_tune.py` | 469 | Tuning unificado em 3 fases, com resumo |
| `fast_tune.sh` / `llm-tune.sh` | 39 / 78 | Wrappers |
| `ga-benchmark-duplicate.sh` | 113 | Wrapper (já estava em `archive/`) |
| `grid-benchmark-duplicate.sh` | 51 | Wrapper (idem) |
| `run-tune-wrapper.sh` | 17 | Wrapper (idem) |

## Por que saiu da raiz

Verificação antes de mover (regra 3 do `archive/README.md`):

- **Referências fora da família: 0.** As únicas menções restantes
  estão em `scripts/INVENTORY-DRAFT.md` (inventário histórico).
- **Supersados por desenho, não por Replacement.** Desde que
  `modules/ai/models.nix` é a **fonte única** das flags
  (`AGENTS.md` §"Modelos: nunca apagar" + `llm-cpp.nix` consumindo o
  registry), otimizar flags por busca genética procura no espaço errado:
  a flag não se escolhe por fitness, se declara. Erro de flag é
  pego pelo registry validator na build, não por 3 gerações de GA.
- **Já existia canônico:** `scripts/bench-llm.sh` (medição) +
  `ncmoe-sweep.py` / `vram-split-sweep.py` / `mlock-benchmark.sh`
  (sweeps dirigidos, com cooldown térmico).

## Atenção — não é lixo, é técnica_obsoleta

A matemática de GA/grid/binary-search continua válida e
`_evict_peers` (29/09) é uma busca binária num único gene. O que
saiu de lá foi a aplicação a **flags declarativas**, não o método.
Se um dia o objetivo virar *hardware detection automático*
(`hwprofile.py`), os motores aqui são ponto de partida, não lixo.

Como ler de volta: `git log --oneline -- '*ga_engine.py'`
