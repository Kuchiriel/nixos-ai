# Mapear canary-official (@explore subagent)

- **sessão:** `ses_f087e3bb1ffeDBnITbQUqnoYD8`
- **quando:** 2026-10-01 12:47 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 5 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

No modo PLAN (somente leitura, NÃO edite nada, NÃO rode git pull/push), faça inventário de /home/nixos/projects/canary-official (upstream opentibiabr/canary).

Retorne:
1. remote -v, branch atual, git log --oneline -5, git status --short (apenas leitura), data do último commit.
2. Estrutura top-level relevante para MMORPG sandbox procedural + life skills: onde ficam data/, data-canary/, data-otservbr-global/, src/ (creatures, game, lua?), tools/, docs/, docker/, schema.sql, config.lua.dist.
3. Existe suporte a life skills / crafting / procedural? (grep rápido por "craft", "profession", "procedural" em data/ e src/ — só para dizer se existe ou não base).
4. Como é o build (CMakeLists, vcpkg.json, CMakePresets.json, recompile.sh, start.sh)? Resuma passos.
5. Liste docs/ mais úteis para custom server + custom client.
6. O que seria necessário para usar canary como motor de sandbox (pontos de extensão: Lua, events, source modules)?

Seja conciso. Não modifique nada.

---

## · ?

Inventário `canary-official` — modo PLAN, nada modificado:

**1. Git (somente leitura)**
- `remote -v`: `origin https://github.com/opentibiabr/canary.git (fetch/push)`
- Branch: `main`
- `log --oneline -5`: retorna só 1 linha → `1789d5f docs(agents): route build validation workflow (#4089)` (clone shallow / histórico truncado)
- `status --short`: limpo (vazio)
- Último commit: `1789d5f97f6f5473e61f3e819ee179d1f79c83c9 2026-08-15 00:56:10 -0300`

**2. Top-level p/ sandbox procedural + life skills**
```
config.lua.dist (688 linhas) | schema.sql (884 linhas, db_version 59)
data/               # CORE — não trocar: core.lua, global.lua, stages.lua, items/, XML/, modules/, events/, libs/, npclib/
data-canary/        # datapack minimal/custom: lib/, migrations/, monster/, npc/, raids/, scripts/{actions,creaturescripts,movements,spells}, world/
data-otservbr-global/ # datapack full Tibia-like: mesma árvore + startup/, world/ completo
src/
  creatures/{players,monsters,npcs,combat,interactions,appearance}
  game/{game.cpp, movement/, scheduling/, zones/zone.cpp, bank/, modal_window/}
  lua/{functions/core|creatures|events|items|map, callbacks/, scripts/luascript.cpp, modules/modules.cpp}
  items/, map/, io/, database/, config/, protobuf/, server/, security/, kv/
tools/{canary_audit, check_lua_api_*.py, link-audit}
docs/ | docker/{Dockerfile.x86/.arm/.dev, docker-compose.yml, up.sh, config.sh, data/01-02-test_account*.sql} | tests/
```
- Seleção de datapack via `config.lua.dist`: `dataPackDirectory="data-otservbr-global"` (ou `"data-canary"` p/ custom), `coreDirectory="data"`, `useAnyDatapackFolder=false`.

**3. Life skills / crafting / procedural?**
- `procedural`: **zero hits** em `data*/ src/` — sem base procedural.
- `craft`: só crafting Tibia-like, não sistema genérico. Ex.: `data-otservbr-global/scripts/quests/the_ancient_tombs/movements_craft_helmet.lua`, `startup/tables/writeable.lua`, NPCs que falam "craft" (Albinius, Emma, etc.), 1 hit em `src/game/game.cpp`. Sem `profession/crafting` como skill.
- `profession`: hits são `vocação` (sorcerer/druid/paladin/knight em `items_definitions.hpp`, `lua_enums.cpp`, `npc_handler.lua`) — não profissão de coleta.
- O que **existe como base reaproveitável**: `actions/tools/fishing.lua`, `skinning.lua`, `fire_bug.lua`, `objects/imbuement_shrine.lua`, `other/create_bread.lua`, sistema Forge (`src/enums/forge_conversion.hpp`), Imbuements (`src/creatures/players/imbuements/`), `weapon-proficiency.md`, `fishing/farming/mining` só como actions pontuais — dá para estender, mas não há skill-tree de life skills.

**4. Build**
- `CMakeLists.txt` + `CMakePresets.json` (presets: `base` hidden Ninja + `windows-release`, `linux-release` via `recompile.sh`) + `vcpkg.json` (~19 deps: asio, luajit, protobuf, pugixml, mariadb, spdlog, etc.) + `vcpkg-configuration.json` + `vcpkg-registry/`.
- `recompile.sh [VCPKG_PARENT=$HOME] [BUILD_TYPE=linux-release] [EXTRA_CMAKE]`: checa cmake/vcpkg → salva binário `.old` → `mkdir build && cmake --preset $BUILD_TYPE` (instala deps vcpkg com barra de progresso) → `cmake --build $BUILD_TYPE`. ARM64 seta `VCPKG_FORCE_SYSTEM_BINARIES=1`.
- `start.sh [BIN=./canary]`: cria `logs/`, copia `config.lua.dist→config.lua` + `./docker/config.sh` se faltar, `ulimit -c unlimited`, loop `"$BIN" | awk timestamp | tee logs/...`; `q` sai.
- Docker: `docker/Dockerfile.{x86,arm,dev}`, `docker-compose.yml`, `up.sh` / `up.ps1`, `DOCKER.md`, `quickstart/myaac/`.
- Docs build: `docs/building/{ubuntu-24.04,debian,windows-(cmake),wsl-*,local-validation.md}` — `AGENTS.md` exige ler `local-validation.md` antes de build autorizado + atualizar `CMakeLists + vcproj/canary.vcxproj` ao add/renomear fonte.

**5. docs/ mais úteis p/ custom server + client**
- `docs/operations.md` — deploy, monitoramento, backup, recovery, upgrades (dono de server).
- `docs/docker/quickstart-for-beginners.md` + `docker/DOCKER.md` — subir rápido com MyAAC.
- `docs/lua-api/{lua_api.md, lua_api.d.lua, lua_api.json}` — referência gerada (`generateLuaApiDocs=true`).
- `docs/systems/multiprotocol.md` + `client-15-25-compatibility-update.md` — compat. cliente (protocolo).
- `docs/systems/weapon-proficiency.md`, `maps/startup-loading-performance.md`, `architecture.md`, `config.ld.in`/`Doxyfile.in` — tuning de conteúdo.
- `data-canary/migrations/README.md`, `docs/release.md`.

**6. Usar canary como motor de sandbox — pontos de extensão**
- **Lua datapack (sem mexer C++)**: `data-canary/scripts/{actions,movements,creaturescripts,spells,lib}` + `data/modules/scripts/{gamestore,daily_reward,hirelings,taskboard,...}` + `data/events/scripts/` + `monster/*.lua` + `npc/*.lua` + `world/` (.otbm). É o caminho para life skills: novos `actions/tools/*.lua` (mining/woodcutting/cooking), `modal_window` p/ UI de crafting, `storages.lua` p/ progressão, `migrations/*.lua` p/ schema.
- **Events C++→Lua**: `src/lua/callbacks/`, `src/lua/functions/{core,creatures,events,items,map}/lua_functions_loader.cpp` — expor novas bindings; `tools/check_lua_api_*.py` valida.
- **Source modules**: `src/game/zones/` (zonas custom/protegidas), `src/game/scheduling/` (tasks/timers p/ respawn procedural, regen de recursos), `src/creatures/players/imbuements|forge` (modelo p/ crafting), `src/items/` (novos atributos em `item_attribute.hpp`), `src/map/` (geração de mapa — hoje OTBM estático, procedural teria que entrar aqui), `src/kv/` + `database/` + `schema.sql` (persistência de parcelas/inventário sandbox).
- Mínimo p/ sandbox: forkar `data-canary` como datapack próprio (`dataPackDirectory` custom), mapa próprio em `world/`, `config.lua` + `schema.sql` + MyAAC; procedural real exige C++ em `src/map/` + scheduler + bindings Lua novas.

---

