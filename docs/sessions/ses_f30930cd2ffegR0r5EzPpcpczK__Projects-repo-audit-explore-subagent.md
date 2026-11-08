# Projects repo audit (@explore subagent)

- **sessão:** `ses_f30930cd2ffegR0r5EzPpcpczK`
- **quando:** 2026-09-23 18:00 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 6 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Auditoria de ~/projects/ (monorepo, NÃO modificar nada):
1. Leia PRIMEIRO /home/nixos/projects/docs/architecture/SYSTEM-MAP.md e /home/nixos/projects/AGENTS.md (mapa e convenções).
2. Para cada subdiretório de ~/projects/, classifique: repo git próprio? último commit (git log -1 --format=%ci\ %s)? é produto vendável, experimento, upstream-track-only, ou arquivo morto?
3. Liste candidatos a PRODUTO (código funcional com dono/usuário potencial): path + linguagem + 1 linha do que faz.
4. Note docs desatualizados vs disco (o AGENTS.md pai diz que o mapa está desatualizado — confirme 3 exemplos).
Volte relatório compacto em PT-BR: tabela subdir→classe→estado, candidatos a produto, e docs divergentes.

---

## · ?

Auditoria `~/projects/` — somente leitura, nada modificado. Base: `docs/architecture/SYSTEM-MAP.md` (2026-09-15) + `AGENTS.md` pai + disco em 2026-09-23.

## 1. Tabela subdir → classe → estado

Root: UM repo `applio-lab` (`github.com/Kuchiriel/applio-lab.git`, `main`, último `2026-09-22 adcf38d fix: trim por cap`). 11 repos próprios com `.git` + 19 gitlinks + resto versionado pelo root.

| subdir | repo próprio? | último commit | classe | estado |
|---|---|---|---|---|
| `karaok/` | sim, SEM remote | `2026-09-22 4c9c559 feat: páginas cast/host` | produto | ATIVO, `??` no root (não trackeado) |
| `nixos-ai/` | sim `Kuchiriel/nixos-ai` | `2026-09-22 6c7860d moe-30B validado` | produto/infra MAIN | ATIVO |
| `applio-lab/` | não — É o remote do ROOT (503 arq.) | via ROOT `2026-09-22 adcf38d` | produto | ATIVO (`caps/`, `Applio/` untracked) |
| `guia-renamer-pro/` | sim `Kuchiriel/guia-renamer` | `2026-09-18 a9c7db0 docs: AGENTS.md` | produto vendável | ATIVO |
| `OTServer_UPGRADE/` | sim `Kuchiriel/otserver-upgrade` | `2026-09-18 694db27 chore: AGENTS.md symlink` | produto/investigação | ATIVO, 3,2 GB |
| `llama.cpp/` | sim `ggml-org/llama.cpp` | `2026-09-22 4ceb171 vulkan Intel Xe` | upstream-track-only | tracking |
| `ik_llama.cpp/` | sim `ikawrakow/ik_llama.cpp` | `2026-09-22 c5b5773 iqk fp32 aarch64` | upstream-track-only | tracking |
| `llama-wackmall/` | sim `miltos22/wackMall-merge` | `2026-08-10 6cacc5e` | upstream-track-only | parado |
| `prism-llama.cpp/` | sim `PrismML-Eng/llama.cpp` | `2026-09-21 bdc23b5 cuda PTQ1_0` | upstream-track-only | tracking |
| `nixpkgs/` | sim `m3ta.dev/m3tam3re/nixpkgs` | `2026-08-22 23dcbfe rewrite talk script` | upstream-track-only | tracking |
| `canary-official/` | sim `opentibiabr/canary` | `2026-08-15 1789d5f docs agents #4089` | upstream-track-only | referência |
| `prism-bin/` | não (85 arq. no root) | via ROOT | binário histórico | 798 MB (`555M dir + 243M tar.gz`), com `run-prism.sh` |
| `harness-research/` | não (9 gitlinks: `agent-context/caveman/ironclaw/kokoro-onnx/faster-whisper/...`) | via ROOT + `AGENTS.md` próprio 2026-09-18 | experimento | ATIVO, fora de todo mapa |
| `red-teaming/` | sim, SEM remote | `2026-09-18 9f18359 .gitignore+AGENTS` | experimento | EXPERIMENTAL |
| `Corretor/` | sim, SEM remote (gitlink no root) | `2026-09-05 0f77805 nightwatch merge` | experimento/arquivo | parado (`corretor.py/.c` + testes) |
| `mudream-bot/` | não (21 arq. root) | via ROOT | produto potencial | PAUSED (SvelteKit) |
| `price-bot/` | não (5 arq. root) | via ROOT | experimento | PAUSED (Node `trading-bot 0.3.0`) |
| `MuDreamNotifier/` | não (48 arq. root) | via ROOT | produto potencial | HISTORICAL (Windows, `dist/`, licenças) |
| `Wurm Ultimate/` | não (45 arq. root) | via ROOT | experimento | SEMI-ATIVO (macros Python) |
| `AI_SYSTEM/` | não (1248 arq. root) | via ROOT | arquivo morto | referência apenas |
| `Samaritan/` | não (12 arq. root) | via ROOT | arquivo morto | HTML estático |
| `LLM/` | não (7 arq. root) | via ROOT | arquivo morto | scripts research |
| `homebrew-engine/` | não (6 arq. root) | via ROOT | arquivo morto | só PDFs cerveja |
| `docs/` | não (21 arq. root) | via ROOT | infra docs | ATIVO |
| `plans/` | não (9 arq. root) | via ROOT | docs | ATIVO (+`??` blueprints) |
| `models/`, `shared/`, `songs/`, `output/cache` | não, vazios | — | arquivo morto/artefato | VAZIOS (0 bytes) |
| `trabalho/` (só `nota.txt`), `projects/`, `~/projects/`, `.freebuff/`, `.roo/`, `.pytest_cache/` | não | via ROOT / `??` | artefato | lixo/quoting-error, fora do mapa |

## 2. Candidatos a PRODUTO (código funcional + dono/usuário)

- `karaok/` — Python — karaokê AI Demucs + faster-whisper + scoring UltraStar, TUI + host/cast `:8099`.
- `nixos-ai/` — Nix + Python — NixOS + JARVIS (router `:8080`, RAG, voz, 1105 testes).
- `guia-renamer-pro/` — Python PySide — renomeia guias TISS/SUS com OCR, SaaS Supabase/Yampi.
- `applio-lab/` — Python — pipeline audiobook LOTM (`lotm-pipeline.py`, `caps/`) + RVC/Kaggle.
- `OTServer_UPGRADE/` — C++/Lua/Python — forensics protocolo Tibia + canary (`canary/`, `forensics/`, `docs/`).
- `mudream-bot/` — SvelteKit/JS — bot web MU (`vite build`, `playwright`).
- `MuDreamNotifier/` — Python Windows — notificador MU com `license_generator.py`, `dist/`.
- `price-bot/` — Node.js — trading bot crypto (`index.js`, `axios/truffle`).
- `Wurm Ultimate/` — Python — macros Wurm (`core/macros/gui/run.sh`).
- `Corretor/` — Python+C — spell checker (`corretor.py/.c`, `test_corretor.py`).
- `red-teaming/` — Python — `shield.py/vault.py/encdec.py` + testes.

## 3. Docs divergentes (confirmado no disco)

1. **`prism-bin/`**: `AGENTS.md` diz ACTIVE consumido pelo wrapper; `SYSTEM-MAP §1/§5` diz vazio/quase, só contêiner, HISTORICAL. Disco: 798 MB trackeados (85 arq. `ls-files`), `llama-prism-b10660-e311ed3/` + `prism-cuda.tar.gz` — SYSTEM-MAP errado.
2. **`OTServer_UPGRADE/`**: `SYSTEM-MAP` diz inteiro untracked 2,7 GB; `AGENTS.md` diz repo próprio `git init local` IMP-007. Disco: repo próprio COM remote `Kuchiriel/otserver-upgrade`, 3,2 GB, `2026-09-18` — SYSTEM-MAP desatualizado, AGENTS parcial (já pushado, não só local).
3. **`karaok/` + fantasmas**: `SYSTEM-MAP` omite `karaok/` totalmente; `AGENTS.md` lista como NEW. Disco: repo próprio ativo `2026-09-22`, invisível p/ root (`??`). Inversão em `docs/`: SYSTEM-MAP diz vazio, disco tem 21 arq. (`architecture/audits/improvements`). Novos `harness-research/` (9 gitlinks), `trabalho/`, `songs/`, `output/`, `projects/`, `~/` em nenhum mapa. Convenção falsa no `AGENTS.md`: "Each subdirectory is an independent project" — 18 dirs são só paths do root (`AI_SYSTEM 1248`, `applio-lab 503` arq.).

---

