# Referencia da API Lua do server (@general subagent)

- **sessão:** `ses_eef105cc1ffeFhmkDq7h86qNFD`
- **quando:** 2026-10-06 11:18 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 122 (exportadas: 75)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

OBJETIVO: produzir a SUPERFÍCIE REAL da API Lua do servidor — a referência que agentes que escrevem gameplay Lua vão usar em vez de adivinhar/grep toda vez.

PASSO 1: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/09-api-lua.md`.
PASSO 2: investigue. PASSO 3: reescreva com relatorio + artefatos.

## Contexto
O servidor expõe C++ para Lua. Fonte: `/home/nixos/projects/canary-official/src/lua/`. Agentes escrevem gameplay em `data-sandbox/` (195 arquivos .lua, 18k linhas) e precisam saber o que existe.

Já existem `tools/check_lua_api_binding_docs.py` e `tools/check_lua_api_quality.py` — LEIA OS DOIS PRIMEIRO e diga se eles já cobrem parte disso (não invente do zero o que já está feito).

## Investigação
1. **Como a API é registrada.** `src/lua/lua_functions.cpp` (ou equivalente), `lua_functions_loader.cpp`, e o padrão de `register*` por módulo. Cada função C++ é registrada por qual `lua_State` e com que nome global?
2. **Superfície real.** Extraia a lista COMPLETA de funções C++ expostas. Grupo por domínio: Player, Creature, Item, Container, Game, Map, Position, Npc, Monster, Combat, Party, Guild, House, Condition, Scheduler/Variant, Config, Logger, Database, Speech, Lua(dor). Para cada: `nome, aridade (mín/máx), o que faz em 1 linha, arquivo:linha do registro`.
3. **O que NÃO está exposto.** Isto é tão importante quanto o que está. Documente os domínios onde o Lua precisa de "gato e esperteza" (hack) porque falta binding. Procure commented-out `register*`, e TODOs.
4. **Segurança.** Qual função Lua é perigosa de expor (spawn de item, teleport arbitrário, exec)? Quem tem acesso (`g_game.getPlayerByName` + `getAccountType`)? Isto alimenta o relatório de segurança anterior (que achou RCE via `load()`).
5. **Qualidade.** `check_lua_api_quality.py` já roda? O que ele reprova hoje? Liste os itens reprovados (se for rápido de rodar, rode; é read-only).

## Entregáveis
### A) `plans/audit-05-10/REF-API-LUA.md`
Referência navegável por domínio. Para os ~30 mais usadas, inclua **exemplo de uso real** copiado de `data/` ou `data-sandbox/` (não invente — copie código que existe e funciona).

### B) `plans/audit-05-10/REF-API-LUA.json`
```json
{ "Player.getHealth": {"aridade_min":0,"aridade_max":0,"desc":"...","reg":"src/lua/functions/...:123"} }
```
Gerado do código, não digitado à mão. Coloque o script gerador em `plans/audit-05-10/tools/`.

### C) No relatório: "GAPS QUE TRAVAM GAMEPLAY"
Os 10 binds que mais fariam falta para o sandbox funcionar, ordenados. Para cada: o que o gameplay quer fazer, o que falta, e quão difícil é (S/M/L).

REGRAS:
- Só leitura/grep. **NÃO modifique nada. NÃO build. NÃO rode o server. NÃO toque em docker.**
- Se rodar `check_lua_api_quality.py` for seguro e read-only, rode e reporte a saída real; se não for, diga por quê.
- Contagens e listas, não prosa. Números reais (ex.: "312 funções expostas").
- Cite `arquivo:linha`.

Mensagem final: 10 linhas — quantas funções expostas, quantos domínios, e os 3 gaps mais prejudiciais.

---

## · ?

I'll start by marking the work in progress, then investigate.

---

## · ?

Both tools read `docs/lua-api/lua_api.json` — a generated artifact. Let me check what already exists.

---

## · ?

Substantial infrastructure already exists. Let me read the loader and docgen, and run the quality check (read-only).

---

## · ?

Critical finding: 1242 methods, 52 classes, but **0 globals**. The docgen misses the entire global namespace. Let me confirm against the source.

---

## · ?

The docgen's global regex (line 1872) only matches **single-line** registrations. Let me measure the real gap.

---

## · ?

Only 9 occurrences total. Let me read the actual global registrations and the loader.

---

## · ?

Now I see the docgen gap. Let me verify the regex failure and enumerate all registration mechanisms.

---

## · ?

Confirmed the bug: docgen regexes expect `"` right after `(`, but the real signature is `f(L, "name", handler)`. Let me verify empirically and read the loader.

---

## · ?

Now let me examine the registration signatures and the docgen's arity inference.

---

## · ?

Now let me look at the loader init and how classes/tables are registered.

---

## · ?

Now let me examine the consumer side: data-sandbox Lua and what it has to work around.

---

## · ?

Let me check docblock coverage, since that determines description quality.

---

## · ?

Now I have enough understanding. Let me survey the getter call patterns to design arity inference.

---

## · ?

Let me write the generator script.

---

## · ?

Counts are inflated — the handler memo dict is polluting `api`. Let me fix.

---

## · ?

1361 bindings. Let me validate the numbers against raw greps and check the anomalies.

---

## · ?

Several gaps to close. Let me debug each.

---

## · ?

The registrations use **unqualified** handler names for same-file handlers. Let me fix and check the other gaps.

---

## · ?

Let me locate the remaining constants and the 3 unmatched registerMethod.

---

## · ?

Major discovery: `lua_enums.cpp` registers enum constants **dynamically** via magic_enum loops — not statically greppable. Let me examine.

---

## · ?

`lua_enums.cpp` is 1738 lines of enum constant registrations. Let me count them exactly.

---

## · ?

684 enum constants + 23 `enum_values<T>()` loops. Let me resolve the loops to exact counts by reading the enum headers.

---

## · ?

Let me make the enum counting robust.

---

## · ?

My value regex missed CamelCase enum values. Let me fix.

---

## · ?

**1266 enum constants** — a surface the docgen misses entirely. Let me fold enums + handler fixes into the generator.

---

## · ?

Now let me add the enum-constant extraction pass.

---

## · ?

I accidentally used a non-ASCII identifier. Let me fix.

---

## · ?

Now let me wire the enum pass into `main()`.

---

## · ?

Let me validate the remaining 2 unresolved handlers and spot-check arity accuracy.

---

## · ?

Two arity bugs. Let me check the missing names against source.

---

## · ?

**Key finding: `getPlayerByName` is NOT exposed to Lua.** Let me enumerate what Game actually offers.

---

## · ?

Arity is inverted for methods. Let me fix the inference.

---

## · ?

Now the varargs/sigcomment arity fix:

---

## · ?

Confirmed: **no creature lookup on `Game` at all**. Now the security surface. Let me check the Lua environment sandboxing and dangerous bindings.

---

## · ?

Critical: `luaL_openlibs(L)` at loader line 38. Let me verify the security surface.

---

## · ?

Now let me compute actual usage frequency from the Lua corpus.

---

## · ?

Let me verify the most-cited missing bindings with file:line evidence.

---

## · ?

Key nuance: many are **Lua polyfills** in `data/libs/functions/game.lua`, not missing bindings. Let me separate real gaps from shims.

---

## · ?

147 Lua polyfills exist. Let me compute the definitive gap list (neither C++ binding nor Lua polyfill).

---

## · ?

My bare-call regex is too noisy (Lua keywords, locals). Let me tighten it.

---

## · ?

The bare-call noise is Portuguese text inside string literals. Let me strip strings and re-verify the key finding.

---

## · ?

0 method gaps — clean. Now let me find the real **global** function gaps with strings stripped.

---

## · ?

Now the capability gaps. Let me hunt commented-out registrations and unbound C++ surface.

---

## · ?

No commented-out registrations. Let me probe specific gameplay capabilities that are absent.

---

## · ?

Let me examine the security-relevant bindings' guards.

---

## · ?

Let me check what the existing security audit already covers, to avoid duplicating.

---

## · ?

The prior report covers the `load()` RCE. My finding is new: unauthenticated `setAccountType`. Let me check the sandbox load path and the player-gated skillkit.

---

## · ?

I have what I need. Let me collect real usage examples from the corpus for the reference.

---

## · ?

Now let me generate the reference document. First, a domain summary from the generated JSON.

---

## · ?

Now let me write the reference document.

---

## · ?

Let me verify every arity claim I made in the reference against the generated JSON.

---

## · ?

Several arities in my draft are wrong. Let me debug and verify the "AUSENTE" ones against source.

---

## · ?

Found a real bug: I discounted index 1 as `self` for **table** methods, but `Game.createItem(a,b,c)` has no self. Let me fix.

---

## · ?

Let me verify `sendTextMessage` (7..7 looks suspicious).

---

## · ?

`sendTextMessage` is genuinely 2..8 but branches on `lua_gettop`. Let me teach the inference about top-count guards.

---

## · ?

Generator is now accurate (`registerAchievement` 6..6 ✓). Let me pull exact tables to avoid transcription errors.

---

## · ?

Now let me rewrite the reference with verified numbers.

---

## · ?

Let me verify the remaining arity claims against the JSON.

---

## · ?

Let me debug the systematic trailing-optional-arg miscount.

---

## · ?

Found it: the signature-comment parser overrides better code evidence. Let me reorder precedence so the code wins.

---

## · ?

Now fix the signature-comment bracket parser and reorder precedence in `main()`.

---

## · ?

Two regressions to fix — `addEvent` has a non-numeric first arg. Let me handle that.

---

## · ?

Now let me finalize the reference doc with the corrected numbers.

---

## · ?

Let me verify that index-8 claim precisely before asserting it.

---

## · ?

Confirmed: only `doTargetCombatHealth` has the gap (7→9,10); the other three are contiguous. Correcting.

---

## · ?

Now let me write the main report.

---

## · ?

I introduced some garbled non-Latin text. Let me fix and verify the `Condition.setOutfit` claim.

---

## · ?

`setOutfit` is a **multi-line** signature comment — my single-line parser truncated it. Let me get the true arity.

---

## · ?

Now let me correct `setOutfit` in the reference doc and verify no other garbled text remains.

---

## · ?

Let me align the JSON top level with the requested schema exactly.

---

## · ?

Let me verify idempotency and confirm I modified nothing in the canary repo.

---

## · ?

Let me re-verify the 0/1350 gap finding against the final JSON structure.

---

## · ?

Confirmed 0 gaps (1352 calls). Let me sync that number in both docs.

---

## · ?

All deliverables written and verified. `src/lua/` untouched, tools untouched, generator idempotent.

**Superfície real da API Lua — 2627 nomes em 19 domínios: 1361 bindings nomeados (1243 métodos, 40 classes, 34 globais, 30 metamethods, 12 tabelas, 2 constantes) + 1266 constantes de enum expandidas em runtime.**

Achado principal: `docs/lua-api/lua_api.json` reporta `"globals": []` porque o regex do docgen (`lua_api_doc_generator.cpp:1871`) exige a string logo após `(`, mas a assinatura real é `(L, "nome", handler)` — casa 0 vezes. O mesmo bug está em 3 outras regexes, e os 33 `lua_register` nem são procurados. **≈1300 dos 2627 nomes (50%) estão fora da doc oficial.** `check_lua_api_quality.py` roda e passa (exit 0), mas só barra regressão e é cego para tudo isso.

Os 3 gaps mais prejudiciais:
1. **`Game.getPlayers()` sem filtro + `Player:setAccountType()` sem gate** (`game_functions.cpp:282`, `player_functions.cpp:843`) — escalonamento para GOD por qualquer script do datapack, sem passar por `load()` nem por conta GOD. `getPlayerByName` (premissa da tarefa) **não existe**; o caminho real é `getOfflinePlayer()`.
2. **Sem filtro de players por área** — nenhum binding de "quem está no raio"; bosses têm de enumerar todos os online por evento. É o gap que escala mal, não os outros 9.
3. **`EventsScheduler` tem só 5 getters** — sem `addEvent`/`removeEvent`, e `addEvent` não tem nome, então timer perdido não é reencontrável.

Achados extras: off-by-one real em `doTargetCombatHealth` (índice 8 pulado, `global_functions.cpp:370-375`, as 3 irmãs são contíguas) e **0 commented-out bindings** — o servidor compensa com 147 polyfills Lua em `data/libs/`, e 0 de 1352 chamadas de método no corpus falham em resolver.

---

