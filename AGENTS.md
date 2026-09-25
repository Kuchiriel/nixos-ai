# AGENTS.md — contexto operacional do JARVIS (nixos-ai)

> Lido por todo agente ao iniciar. **Meta: <150 linhas / ~2000 tokens.**
> Regra da casa: aqui mora só o que **muda comportamento** e **não é
> inferível do código**. Histórico, medição e "por quê" vão para
> `docs/` e entram por link.
> Base: ETH Zurich (arXiv 2602.11988) mediu que arquivo de contexto
> inflado **custa +19-23% de custo** e perde sucesso; e o efeito
> *"too obedient"* (agente obedece instrução irrelevante e faz mais
> trabalho resolvendo menos). Por isso: sem árvore de diretórios, sem
> prosa de estilo, sem listas.

## PROIBIÇÕES (leia isto primeiro — maior raio de dano)

1. **NUNCA apague dado.** Zero `rm`, `delete_collection`, `drop_collection`
   em material que você não criou nos últimos minutos. Use
   `core.safe_archive.archive_then_delete()`: copia → **lê de volta** →
   confere contagem e hash → só então remove. Já houve Qdrant aceitar a
   escrita (HTTP 200) e não gravar; quem confiou no status perdeu 6 pontos.
   Comece sempre em `dry_run=True`. Aceite **IDs explícitos**, nunca
   filtro por substring (filtro casa com texto que *cita* o termo).
2. **Coleções de produção** — `code_index`, `memories`, `books`, `vault`
   e as por espaço (`pessoal_*`, `moe_*`, `qwen4b_*`). `memories` é a
   memória do agente. **Não escrever, não renomear, não remover.**
3. **Teste só toca `jarvis_test_*`**, sempre derivado:
   `dataclasses.replace(Config(), qdrant_collection_code="jarvis_test_x")`.
   O guard `tests/test_test_isolation.py` reprova o build se violar — ele
   existe porque alguém apagou 1263 pontos de `code_index` rodando teste.
4. **`./rebuild-host.sh` só com o dono autorizando** (ativa config e
   reinicia serviços). `nixos-rebuild` direto: nunca. `/nix/store`: nunca
   editar. Reiniciar LLM em sessão ativa: nunca.
5. **Nunca afirmar "está rodando"/"está no ar" sem verificar agora.**
   `pgrep` + log + evidência. Código commitado ≠ código no ar: processo
   de sessão longa carrega o `.py` antigo em memória — confira
   `ps -o lstart=` contra `git log --date`.
6. **Nunca medir com outro processo na máquina.** Sweep/bench recusa
   medir se houver outro `llama-server` vivo (contenção já custou uma
   investigação inteira de um "bimodal" inexistente).

## Comandos

```bash
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short
git add -A && git ls-files -o --exclude-standard   # flake só vê trackeado
./rebuild-host.sh        # HOST — só com o dono autorizando
nix flake check
```

## Boundaries

- **Sempre:** rodar testes antes de commitar; conferir `git ls-files` com
  arquivo novo criado na sessão; commit PT-BR com verbo (`feat:`/`fix:`/
  `chore:`/`docs:`); toda regra nova entra **depois** de um agente errar
  de verdade (cresce orgânico, não especulativo).
- **Perguntar:** mudar `configuration.nix` do host; flags do llama-server;
  dependências novas; mutar memória viva (`consolidate --apply`).
- **Nunca:** `nixos-rebuild` direto; editar `/nix/store`; `git add .` sem
  ver o que entra; auto-commit com `git add -A`.

## Regras que não dá pra inferir do código

- `modules/ai/models.nix` é a **única fonte de verdade** de modelos,
  perfis e flags. Perfis são consumidos por `services/llama-cpp.nix`.
  Sampling (temperature/top_p/top_k/...) também mora lá
  (`routing.models.<id>.sampling`, por modelo — Prism 0.5 NÃO vale p/ Qwen);
  Python lê via registry, nada hardcoded.
- **Modelos: nunca apagar, nunca baixar sem checar.** Inventário e regras em
  `docs/models/MODEL-SAFETY.md` (incidente 27B 25/09). Bonsai 8B mora no
  nix store (GC volta com rebuild), não em `~/models`. Checar VRAM 6GB
  antes de qualquer download.
- VRAM 6GB: **1 LLM por vez.** P/ modelo que não cabe, experts na GPU
  **atrapalham** (o fetch vem por PCIe, 6-7 GB/s, contra 41-83 GB/s da
  RAM). Denso que cabe na VRAM roda ~3,2× mais rápido.
- `-t` = **P-cores**. Esta CPU é híbrida (6P+4E) e o `lscpu` reporta "8".
  Medido: `-t 6` = 16,4 t/s · `-t 8` = 14,1 · `-t 10` = 10,4 · `-t 12` = 7,9.
- `ubatch` muda a decisão de offload do `ik_llama.cpp` (threshold
  `32 × total_experts/active_experts`); manter 512 alinhado com o service.
- Servidor de embeddings tem **max context de 512 tokens**: acima disso
  devolve 400/500. `providers/embedding.py` faz chunk + mean-pool.
- **Binário importa:** prism = ternário (e MoE); ik = MoE; stock carrega
  `Q2_0` como lixo silencioso. Ver `docs/models/BINARIES.md`.
- Hardware e medição desta máquina: `docs/auditoria/SO-LLM-E-ENTROPIA-*.md`.

## Índice (leia só quando a tarefa pedir)

| Documento | Quando consultar |
|---|---|
| `docs/SISTEMA-ESTADO-E-BENCHMARKS.md` | estado dos tiers, H1/H2/H3, histórico |
| `docs/architecture/SYSTEM-MAP.md` | mapa do sistema e camadas |
| `docs/models/BINARIES.md` | qual binário para qual modelo |
| `docs/auditoria/SO-LLM-E-ENTROPIA-2026-09-25.md` | SO, VRAM/RAM, PCIe, medições |
| `docs/PROMPT-AGENTE-EXTERNO.md` | prompt pronto para outro agente |
| **`docs/HANDOFF-2026-09-25.md`** | **estado da sessão 25/09 + próximo passo exato** |
| `scripts/LOOP-v2.md` | método do loop overnight |
| `scripts/overnight-24-09/` | evidência datada de benchs |
| `.agents/*.md` | detalhe por tema (carregue só se o gatilho casar) |

## Regras de agentes (gatilho → arquivo)

- `.agents/dados-e-memoria.md` — RAG, memória, vault, spaces, cifrado.
  Gatilhos: RAG, memória, vault, qdrant, collection, embedding, recall.
- `.agents/loop-e-bench.md` — overnight, harness, sweep, benchmark.
  Gatilhos: loop, harness, bench, sweep, cmoe, t/s, overnight.
- `.agents/memoria-do-projeto.md` — decisões e armadilhas já pagas.
  Gatilhos: já quebrou, antes de mexer, armadilha, por que.

## Frontmatter

Tags: #status/active #type/rules #project/nixos-ai
