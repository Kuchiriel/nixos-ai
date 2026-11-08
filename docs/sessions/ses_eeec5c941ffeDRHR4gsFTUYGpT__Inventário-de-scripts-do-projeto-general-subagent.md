# Inventário de scripts do projeto (@general subagent)

- **sessão:** `ses_eeec5c941ffeDRHR4gsFTUYGpT`
- **quando:** 2026-10-06 12:39 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 18 (exportadas: 7)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

READ-ONLY. Não edite, não mova, não delete, NÃO EXECUTE nada (só leia código). No monorepo /home/nixos/projects (foco: canary-official/tools/, canary-official/scripts/, canary-official/dataset/, canary-official/data-sandbox/tools/, otclient/scripts/, nixos-ai/scripts/):

1. Liste TODOS os scripts (.sh/.py/.lua utilitário, não de gameplay) com linhas, mtime e propósito em 1 linha (pelo cabeçalho/comentários).
2. Detecte: duplicados (mesma função, ex: bench_sequencial.sh que tem comentário falso sobre portas), mortos (referenciam paths/ferramentas que não existem), conflitantes (dois scripts que escrevem no mesmo destino, ex: geradores de skills_cpp), e scripts modificados nas últimas 6h por outro agente (ZONA DE CONFLITO).
3. Marque especialmente: scripts que apagam/sobrescrevem dados (rm -rf, OVERWRITE, DROP) — esses são PERIGOSOS e precisam de confirmação antes de qualquer uso futuro.
4. Devolva: tabela path|linhas|mtime|propósito|status(ok/duplicado/morto/conflito-ativo/perigoso) + PROPOSTA de consolidação SEM executar. Terse.

---

## · ?

Levantamento somente-leitura dos scripts utilitários — catalogando sem executar nada.

---

## · ?

Inventário inicial parcial — refinando buscas nos diretórios grandes.

---

## · ?

Diretórios `scripts/` não existem — mapeando locais reais (`tools/`, `dataset/`) e lendo cabeçalhos.

---

## · ?

Núcleo do sandbox mapeado — expandindo para i18n e ferramentas de dados.

---

## · ?

Orquestradores e geradores mapeados — fechando com i18n, reskin e harness.

---

## · ?

READ-ONLY cumprido: nenhum `bash`/`edit`/`write`. `canary-official/scripts/` e `otclient/scripts/` **não existem** (verificado via `read` do diretório) — escopo real abaixo. `mtime` = `n/d`: ferramenta de leitura não expõe `stat`; ZONA 6h **indeterminável** sem executar — proposta de comando no fim. `linhas` = total do rodapé do `read` quando disponível.

## Tabela `path|linhas|mtime|propósito|status`

**`canary-official/tools/` (núcleo)**

| path | linhas | mtime | propósito | status |
|---|---|---|---|---|
| `tools/sbx` | 88 | n/d | dispatcher único `listar/traduzir/.../skills/guard` | ok |
| `tools/guard_servidor.sh` | 407 | n/d | bloqueia nativo+container 7171-75, detecta boot vs travado + artefato velho | ok |
| `tools/i18n/bench_sequencial.sh` | 79 | n/d | roda 1 GGUF/vez em `:8110` + `benchmark_modelos.py`, `pkill` só ad-hoc | ok-duplicado* |
| `tools/i18n/benchmark_modelos.py` | 193 | n/d | qual GGUF traduz melhor (QA+hunspell+vazamento EN) | ok |
| `tools/i18n/traduzir.py` | 754 | n/d | loop tradução `.dat`→dicionário 1639 entradas + QA/âncora pt.lua | ok |
| `tools/i18n/traduzir_campos.py` | ~? | n/d | traduz campos do manifesto, motor=`traduzir.py` | duplicado |
| `tools/i18n/julgar.py` | 123 | n/d | juiz LLM: perda/invenção na tradução | ok |
| `tools/i18n/corrigir.py` | ~? | n/d | override manual = feedback do jogo | ok |
| `tools/i18n/fila.py` | 167 | n/d | fila enriquecimento em etapas verificáveis, só escreve `dataset/` | duplicado |
| `tools/i18n/loop_enriquecer.py` | 388 | n/d | loop noturno repetir+julgar (sucessor da `fila.py` 12min) | duplicado |
| `tools/i18n/i18n_manifest.py` | ~? | n/d | declara campos traduzíveis (attr/element/dat) | ok |
| `tools/i18n/extrair_glossario.py` | ~? | n/d | glossário PT-BR oficial de `otclient pt.lua` | ok |
| `tools/i18n/extrair_aparencias.py` | ~? | n/d | extrai nome+desc do `appearances.dat` | ok |
| `tools/i18n/gerar_lexico_criaturas.py` | ~? | n/d | léxico estático traduzir\|manter criaturas | ok |
| `tools/i18n/verificar_classificacao.py` | ~? | n/d | falha se IA errou classificação | ok |
| `tools/i18n/ptbr_dict.py` | ~? | n/d | hunspell como set p/ QA em lote | ok |
| `tools/sandbox-codegen/gerar_skills_cpp.py` | 185 | n/d | gera `src/sandbox_skills.inc` do Lua, falha sem PT-BR | conflito-ativo |
| `tools/sandbox-codegen/to_lua_ptbr.py` | 162 | n/d | `dataset/i18n/*.json`→`i18n_ptbr.lua` | ok |
| `tools/sandbox-codegen/patchar_dat_ptbr.py` | 320 | n/d | traduz campos 4/5 do `.dat`, backup+idempotente+dry-run | conflito-ativo/perigoso |
| `tools/sandbox-codegen/validar_lua_sandbox.py` | 299 | n/d | portão: id existe no core + `onUse` 6 args + sintaxe | ok |
| `tools/sandbox-codegen/codegen.py` | 214 | n/d | gera Lua via harness local (bonsai/moe por dificuldade), nunca commita | ok |
| `tools/dump_towns.py` | 130 | n/d | extrai towns do `.otbm` espelhando `iomap.cpp` | ok |
| `tools/check_lua_api_quality.py` | 120 | n/d | qualidade `lua_api.json` vs baseline | duplicado |
| `tools/check_lua_api_binding_docs.py` | ~? | n/d | docs de bindings Lua (irmão do acima) | duplicado |
| `tools/test_recompile.py` | 536 | n/d | testa `recompile.sh` com fixtures ELF, nunca compila Canary | ok |
| `tools/test_shared_cache_identity.py` | ~? | n/d | identidade do cache compartilhado | ok |
| `tools/canary_audit/cli.py`+`runner.py` | 272+ | n/d | auditoria com exit codes p/ CI | ok |
| `tools/*.ps1` (3x) | — | n/d | `configure_shared_*`, `setup_vscode_lua_api` — Windows-only | morto* |

\* `bench_sequencial.sh`: cabeçalho **procede** no lido — `PORT=8110` default, `pkill -f "llama-server.*--port $PORT"` (não toca systemd `:8080/81/82/83`), refs `SB=ik_llama.cpp/build/bin/llama-server` + `MODELS=/home/nixos/models` + `/tmp/opencode` — **suspeito-morto** se esses paths não existirem (AGENTS diz `models/` vazio, GGUF via `models.nix`); `benchmark_modelos.py:38-40` fixa `/nix/store/...hunspell` com hash — quebra após GC. `*.ps1` mortos no NixOS.

**`canary-official/data-sandbox/tools/`**

| path | linhas | mtime | propósito | status |
|---|---|---|---|---|
| `loop.sh` | 227 | n/d | loop âncoras `.loop/anchors.json`, STAGE+VERIFY pelo log | duplicado |
| `sandboxtest.sh` | 96 | n/d | cadeia camadas 1+2+3 (`selftest`), usa `nix-shell -p lua` | ok/morto* |
| `game-action.sh` | 99 | n/d | envia `!cmd` no chat e prova pelo log; sessão `/tmp/game-*` | duplicado |
| `game-input.sh` | 66 | n/d | foco/mouse/tecla Hyprland (`hyprctl`, `wtype`) | ok/morto* |
| `probe-chat.sh` | 49 | n/d | sobe client, loga, tenta `!scanitens`, `pkill -x otclient` | duplicado/perigoso |
| `visual-check.sh` | 213 | n/d | screenshot+OCR (`grim/tesseract`) ciclo completo | conflito-ativo |
| `check_lua_syntax.py` | 79 | n/d | todo `.lua` parseia (fecha furo do regex de `gen_*`) | ok |
| `gen_dataset.py` | 197 | n/d | valida dataset (nunca gera valor, buraco declarado) | ok |
| `gen_criaturas.py` | 129 | n/d | stubs `monster/*.lua` do dataset, `--apply` escreve | perigoso |
| `gen_realdata.py` | 200 | n/d | `yield_real.json`→`realdata.lua`, `--check` p/ CI | ok |
| `loop-actions/` | 0 | n/d | dir vazio mas `loop.sh` espera `acoes/<id>.sh` | morto |
| `reskin/batch_tools.py` | 118 | n/d | injeta donor PNG no sheet, backup+roundtrip | perigoso |
| `reskin/gen_night.py` | 228 | n/d | Flux overnight + auto-inject + ledger, `<0.80` p/ conferir | perigoso |
| `reskin/auto_match.py` | ~? | n/d | vanilla→CLIP donor→inject→ledger | duplicado/perigoso |
| `reskin/sprsheet.py` | ~? | n/d | decode/encode `.bmp.lzma`, `open(wb)` escreve sheet | perigoso |
| `reskin/dashboard.py/hash_registry.py/reprocess.py/review_montage.py/match_clip.py/spr_extract.py/topixel.py/rme_categories.py` | ~? | n/d | triagem, hash `antes`, reprocess, montage, SigLIP match, extract `.spr`, pixelize, categorias RME | ok |

\* `sandboxtest.sh:28` exige `nix-shell -p lua` + `data-sandbox/tests/run_tests.lua`; `game-*.sh/probe/visual` exigem Hyprland+`grim/wtype/tesseract/hyprctl` + `docker compose ...sandbox.yml` + `OT/run.sh`.

**`canary-official/dataset/{tools,maps,wurmpedia}/`**

| path | linhas | mtime | propósito | status |
|---|---|---|---|---|
| `dataset/tools/gera_skills_ui.py` | 326 | n/d | FONTE ÚNICA skills (storages+extras+`sandbox_skills.json`+otui), `--aplicar` escreve 4 destinos e **patcha `gerar_skills_cpp.py:291-6`** | conflito-ativo/perigoso |
| `dataset/tools/gera_crafting_ui.py` | 73 | n/d | tabela RECEITAS→`crafting_recipes.json` | ok |
| `dataset/tools/patch_dat_sandbox.py` | 88 | n/d | itens novos 55103-55233 no `.dat` (sobrevive reboot, ex-`/tmp`) | conflito-ativo/perigoso |
| `dataset/tools/datedit.py` | 93 | n/d | parse/serialize `appearances.dat` (reconstrução 03/10) | ok |
| `dataset/tools/extrai_icones_skills.py/download_wurmpedia.py/extract_*` | ~? | n/d | ícones, fetch wurmpedia, categorias RME | ok |
| `dataset/maps/gerar_mapa.py` | 330 | n/d | mapa sandbox de JSONs validados, determinístico | ok |
| `dataset/maps/gerar_otbm.py/gerar_yield_real.py/extrair_doodads.py/extrair_quebraveis.py/validar_otbm.py/common.py/check_*.py/verificar_yield.py` | ~? | n/d | pipeline mapa: otbm, yield, doodads, quebraveis, validação, checks bioma/densidade/seam/terreno | ok |
| `dataset/wurmpedia/fetch_mechanics.py/fetch.py/fetch_index.py/parse.py/measure_fields.py` | 119+ | n/d | baixa Wurmpedia p/ `raw/` imutável + manifest, parse/mede | ok |

Conflito-ativo confirmado por `grep`: `gera_skills_ui.py` ↔ `gerar_skills_cpp.py` escrevem a mesma tabela (um ainda edita o outro); `patchar_dat_ptbr.py` ↔ `patch_dat_sandbox.py` (+`datedit.py`) escrevem o mesmo `appearances.dat`; `sprsheet.py:141 open(wb)` + `reskin/*.py open(w)` (ledger/manifest/decisions) sobrescrevem sem confirmação.

**`otclient/tools/`** (`scripts/` não existe)

| path | linhas | mtime | propósito | status |
|---|---|---|---|---|
| `tools/visual-check.sh` | 191 | n/d | prova bloco `0xA1` (skills 137) via `otclient-autotest.lua` + marcador `/tmp/opencode/otc-autotest` | conflito-ativo |
| `tools/gen_lang_template.sh` | 15 | n/d | template `locale={...}` varrendo `tr()` | duplicado |
| `tools/gen_needed_translations.sh` | 7 | n/d | lista `neededTranslations` varrendo `tr()` (mesmo `find/grep`) | duplicado |
| `tools/emscripten-web-serve.py` | 220 | n/d | serve WASM com COOP/COEP/CORP | ok |
| `tools/make_snapshot.sh` | 252 | n/d | zip win32, `git://edubart`, `i486-mingw32`, `rm -rf build.*`, `find -exec rm -rf` | morto/perigoso |
| `tools/lua-binding-generator/` | — | n/d | gerador bindings (não lido a fundo) | ok |

**`nixos-ai/scripts/`** (top-level; `archive/` = legado)

| path | linhas | mtime | propósito | status |
|---|---|---|---|---|
| `jarvis-cli.sh` | 355 | n/d | wrapper `jarvis <tool>` (read/write/shell/rag/vault/...) | ok |
| `nix-validate.sh` | 286 | n/d | validação Nix em camadas, fail-closed | ok |
| `safe-nixos-apply.sh` | 117 | n/d | único caminho p/ `nixos-rebuild` (build/test/switch+rollback) | ok |
| `loop-runner.sh` | 200 | n/d | executor LOOP-v2 (preflight+ harness+probes, nunca push/rebuild) | duplicado |
| `overnight-loop.sh` | 75 | n/d | mede→arquiva→MoE patcha→gate `git reset --hard`, nunca push | duplicado/perigoso |
| `overnight-harness-loop.py` | ~? | n/d | loop melhoria harness 30/09 | duplicado |
| `overnight-agent-24-09.sh/overnight-harness-24-09.sh` | ~? | n/d | runners datados 24/09 | duplicado |
| `bench-llm.sh` | 79 | n/d | bench padrão (warmup+3 reps, server efêmero `:8095`, TSV+JSONL) | duplicado |
| `bench-final.py/eval-model.py/eval-judge.py/grade-harbor.py/harbor-lite.sh` | ~? | n/d | família bench/eval/grader Harbor | duplicado |
| `harness-suite.py/ux-suite.py/ux-autonomy.py/ux_driver.py/ux_world.py/ux-repl-session.py` | 386+ | n/d | baterias E2E `jarvis dev` + mundo verificável | duplicado |
| `gguf_audit.py/ncmoe-sweep.py/vram-split-sweep.py/moe-profiler.py/mlock-benchmark.sh/thermal-curve.sh/ctx-usage.sh` | ~? | n/d | auditoria GGUF, sweeps split/ncmoe, profiler, curvas | duplicado |
| `pipeline.py/mission-kit.py/ab-prompt.py/decomp.py/self-study.py/loop-close.py/session-primer.py/migrate-tools-en.py/read_chatgpt.py/fetch-resume.py/corpus_inventory.py/ingest_books.py/reindex_code.py` | ~? | n/d | estrategista/executor, kits, A/B prompt, decomposição, auto-estudo, primer, migração PT→EN, chatgpt, resume, corpus | ok |
| `sync-vault.sh/monitor-nightwatch.sh/night-anchor.sh/roo-nightwatch-setup.sh/setup-hackmd.sh/jarvis-gaming-mode.sh/charger-watch.sh/rvc-env.sh/rvc-spike-bootstrap.sh/voice-selftest.sh` | ~? | n/d | vault, nightwatch, hackmd, gaming, charger, rvc, voz | ok |
| `archive/*-duplicate.sh/bench-legacy/*` | ~? | n/d | nomes já dizem `duplicate`/legado 25/09 | duplicado/morto |
| `archive/clean-project.sh` | ~? | n/d | `find ... -exec rm -rf __pycache__/pytest/hypothesis` | perigoso |
| `archive/fix-qdrant.sh` | ~? | n/d | `rm -rf "$STORAGE"` | perigoso |
| `ux-autonomy.py:169` `shutil.rmtree` / `ux-suite.py:109` `os.remove` | — | n/d | apagam sandbox/outputs | perigoso |

## Perigosos (confirmação obrigatória antes de qualquer uso)

`gera_skills_ui.py --aplicar` (4 destinos + patcha gerador) · `patch_dat_sandbox.py` + `patchar_dat_ptbr.py` (`.dat` binário) · `gen_criaturas.py --apply` · `reskin/{batch_tools,gen_night,auto_match,sprsheet}` (sheets/ledger/manifest) · `probe-chat.sh:11 pkill -x otclient` · `bench_sequencial.sh:41 pkill -f llama-server` · `overnight-loop.sh: git reset --hard` · `nixos-ai/archive/{fix-qdrant,clean-project}.sh`, `ux-autonomy.py`, `ux-suite.py`, `otclient/make_snapshot.sh` (`rm -rf`).

## Proposta de consolidação (SEM executar)

1. Skills: `gera_skills_ui.py` vira única fonte; `gerar_skills_cpp.py` vira renderer puro (remover auto-patch `:291-6`, ler JSON em vez de regex em `storages.lua`); registrar em `tools/sbx`. 2. `.dat`: unificar `patchar_dat_ptbr.py`+`patch_dat_sandbox.py` sobre `datedit.py` com `--dry-run`+backup+verificação pós-escrita. 3. Visual: renomear `otclient/tools/visual-check.sh`→`visual-check-0xA1.sh` vs `data-sandbox/tools/visual-check.sh` (OCR genérico) ou fundir via flag. 4. i18n: `sbx` já despacha; arquivar `fila.py` (superseded por `loop_enriquecer.py`) e fundir `check_lua_api_*.py` + `gen_lang_template`/`gen_needed_translations`. 5. Bench/harness: `bench-llm.sh` padrão + `harbor-lite.sh`; mover resto p/ `archive/` (já iniciado). 6. Mortos: remover `make_snapshot.sh` mingw/`*.ps1`/`.loop` legado ou marcar `DEAD` no cabeçalho.
7. Zona 6h (quando autorizado, ainda não executado): `stat -c '%y %n' <files> | sort` + `git log --since='6 hours ago' --name-status -- <dirs>` + `git status --short`; tratar como conflito-ativo: `gerar_skills_cpp.py` (cita "outro agente" 03-04/10), `gera_skills_ui.py` (05/10), `patch_dat_sandbox.py` (03/10 noite), `datedit.py` (reconstrução pós-reboot).

---

