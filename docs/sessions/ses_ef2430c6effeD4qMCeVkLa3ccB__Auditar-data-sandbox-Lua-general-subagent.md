# Auditar data-sandbox Lua (@general subagent)

- **sessão:** `ses_ef2430c6effeD4qMCeVkLa3ccB`
- **quando:** 2026-10-05 20:24 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 90 (exportadas: 37)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Audite o sandbox de gameplay em Lua do servidor: `/home/nixos/projects/canary-official/data-sandbox/` (195 arquivos .lua). E a fronteira com `data/` (656 .lua, upstream).

PASSO 1 OBRIGATORIO: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/03-sandbox-lua.md`.
PASSO 2: investigue. PASSO 3: reescreva com o relatorio.

CONTEXTO IMPORTANTE: existe uma suite de testes em `data-sandbox/tests/run_tests.lua` (~66K) que roda 44 checks. Descubra COMO ela roda (leia o cabecalho e o runner) e EXECUTE se possivel. Se nao souber como executar sem risco, diga como e NAO quebre nada.

FOCAS:

1. **Estado da suite de testes.** Execute. Quantos passam, quantos falham, quais falham e por que. Ha teste que depende do mundo rodando (e portanto nunca executa)? Qual e a cobertura REAL (qual % de `lib/sandbox/` e' tocado por teste)? Reporte numeros, nao adjetivos.

2. **Codigo quebrado / stub / nunca chamado.** Cruze `lib/sandbox/*.lua` (41 arquivos: skill, growth, market, economy, quality, journal, titles, terraform, mining, foraging, species, grove, fauna, eco, storages, harvest, decays...) com quem realmente chama. Ache: (a) modulo definido mas NUNCA `require`d por nada; (b) funcao exportada mas nunca chamada; (c) `TODO`/`FIXME`/`XXX`/`HACK`; (d) codigo comentado em bloco grande; (e) `return nil` em caminho que deveria ter valor. Isso mede "feature scaffolding sem gameplay".

3. **Qualidade e robustez.** `pcall` engolindo erro? `error()` sem contexto? Falta de validacao de input (jogador mandando valor negativo/NaN/huge em `rateSkill`, storage, market)? Loop sem limite? Acesso a storage sem checar se existe? Race entre dois jogadores no mesmo recurso (ex.: dois claim do mesmo minerio no mesmo tick)?

4. **Escalabilidade.** Como o estado e' guardado: `storage`, `global`, tabela em memoria? Se 500 jogadores mexerem, onde ha `O(n)` dentro de `O(n)`? Ache laco aninhado sobre tabela grande, e `table.insert` em laco. Isso importa: o jogo precisa crescer.

5. **Integridade com `data/`.** `data-sandbox` foi feito pra rodar junto do upstream. Ha conflito de hook? Dois handlers no mesmo evento? Ordem de execucao indefinida? `data-sandbox/scripts/creaturescripts/customs/` — quantos estao realmente plugados no `data/scripts/`?

6. **Oportunidades de gameplay de baixo custo.** Dado o que JA existe (skills com progressao, QL com desgaste, market com matching de oferta/desejo, eco, journal, titulos, terraform, casas/cercas), quais 5 features seriam ALTO valor de flavor e BAIXO custo de implementar, reaproveitando modulo existente? Seja especifico (qual arquivo, qual funcao).

REGRAS:
- NAO modifique nada. NAO rode o servidor. NAO toque em docker/container. Se rodar testes, so em modo leitura/dry-run e descreva exatamente o comando.
- Numeros, nao adjetivos.
- Cite `arquivo:linha`.

FORMATO (PT-BR, markdown):
- VEREDITO: tabela de severidade.
- ESTADO DOS TESTES: output real, contagem, falhas.
- CODIGO MORTO: tabela de arquivo -> o que e -> evidencia de que nunca e' usado.
- ACHADOS DE ROBUSTEZ/ESCALA (com `arquivo:linha`).
- FEATURES BARATAS (top 5, com arquivo e funcao a estender).
- VERIFICADO-OK.
- LIMITACOES.

Mensagem final: 15 linhas, numeros dos testes + top achados.

---

## · ?

I'll start with the mandatory first step.

---

## · ?

`EM_ANDAMENTO` written. Now investigating.

---

## · ?

Safe to run: only touches `/tmp/sandbox-test` (line 25-27). Running.

---

## · ?

Suite runs: **342 OK, 3 FALHA**. Capturing full output for analysis.

---

## · ?

Now investigating the 3 failures in `body.lua`.

---

## · ?

Found something significant. Let me verify.

---

## · ?

Major finding in storage keys. Now cross-referencing dead code systematically.

---

## · ?

11 storage key collisions. Let me verify the live impact.

---

## · ?

6 modules with zero callers, including `market.lua`'s only links. Verifying.

---

## · ?

Let me build an exact `require` graph instead of prose matching.

---

## · ?

My dofile regex is too loose. Let me check the actual module loading idiom.

---

## · ?

`harvest.lua` may be comment-only referenced. Verifying definitively.

---

## · ?

12 modules dead (958 KB). Now scanning for markers and robustness issues.

---

## · ?

Now the persistence layer and scalability. Let me check the shared ledger pattern and races.

---

## · ?

Found a multi-instance risk. Let me quantify and check unused locals.

---

## · ?

This looks like a serious multi-instance bug. Verifying with `smelt.lua`.

---

## · ?

Confirmed: `baking.lua`/`pottery.lua` hold frozen furnace state. Now checking `eco.lua` clobber and the `data/` boundary.

---

## · ?

`Eco` is a **global** with per-instance state. Checking who actually calls it.

---

## · ?

Now the `data/` boundary and hook conflicts.

---

## · ?

`data/` is **not loaded at all** (`dataPackDirectory = "data-sandbox"`). Let me verify the boundary.

---

## · ?

`data-sandbox/global.lua` is missing. Verifying whether the datapack can boot.

---

## · ?

The load chain resolves. Now computing the real action/talkaction overlap.

---

## · ?

Now scalability and test coverage numbers.

---

## · ?

Found something serious in `sandbox_init.lua`. Reading it.

---

## · ?

This is the headline bug. Verifying the interaction with `Body.get`.

---

## · ?

Final checks: CI wiring and input validation.

---

## · ?

Last verification batch before writing.

---

## · ?

The alias-based scan has false positives. Redoing alias-aware.

---

## · ?

Verifying the charcoal reachability chain — this looks game-breaking.

---

## · ?

Investigation complete. Writing the report.

---

## · ?

A live server is writing into the repo. Let me verify and re-validate my cited line numbers.

---

## · ?

Concurrent edit detected — storage keys are being moved right now. Re-running the collision analysis.

---

## · ?

The parallel fix breaks hardcoded test keys. Re-running the suite for current numbers.

---

## · ?

The concurrent fix crashes the suite. Getting the full current state.

---

## · ?

Updating the report with the current on-disk reality.

---

## · ?

Relatório em `/home/nixos/projects/plans/audit-05-10/03-sandbox-lua.md` (496 linhas).

**TESTES** — `nix-shell -p lua --run "lua data-sandbox/tests/run_tests.lua"` (Lua 5.2.4; só escreve em `/tmp/sandbox-test`, linhas 25-27). **342 OK / 3 FALHA** de 345 checks (o "44" do pedido é a numeração de features do LOOP.md, não checks). Cobertura **21/44 módulos = 47,7 %**, **13,7 %** por peso; **116/345 asserts são grep de texto-fonte**. 0 testes precisam do mundo. **0 execução em CI** (`reusable-tests-lua.yml` roda `tests/lua/`, não o sandbox). **Durante a auditoria, `storages.lua` foi alterado por outra sessão (17:43)** — moveu `S.corpo` para 51170+, o que conserta 10 das 11 colisões de storage **e quebra a suite**: agora são **13 falhas + crash** em `run_tests.lua:359` (chaves hard-coded `51050` vs `51170`).

**TOP ACHADOS**
1. **P0** `Fornos.criarPile` (`forno.lua:239`) sem caller → `piles{}` vazio → carvão 55210 inobtível → forno nunca passa de 900 °C → `podeFundir` (exige 1200) sempre falso → **fundição/aço/imp inalcançáveis** (`smelt.lua:69`).
2. **P0** `Eco` é **global** (`eco.lua:45`) e `dofile`ado de 2 arquivos → 2 tabelas independentes → `cut.lua:555` e `terraform.lua:261` **apagam o estado um do outro**. Mesmo padrão em `Grove` (3 instâncias).
3. **P0/P1** `baking.lua:25` e `pottery.lua:15` fazem `dofile` do forno em escopo de arquivo → instância congelada no boot → **assar e cerâmica impossíveis**, e `Fornos.consumir` grava o snapshot velho apagando o tick.
4. **P1** `saveState()` reescreve o arquivo inteiro por mutação e `fornos[k]` nunca é podado — confirmado empiricamente: `.forno_state.lua` reescrito a cada 60 s por um servidor rodando, como `root`, **dentro do repo e fora do `.gitignore`**.
5. **CÓDIGO MORTO** 15/44 módulos (**1 022 KB, 18 137 linhas, 72 funções**), incl. `market.lua` (12 funcs), `harvest.lua` (8 testes verdes, nunca carregado), `i18n_ptbr.lua` (930 KB), `titulos.lua` + `S.aplicarTitulo` (títulos nunca chegam ao cliente). **41/185 funções exportadas** sem caller. Marcadores: 1 TODO, 0 FIXME/XXX/HACK.
6. **OK** `data/`: **0 colisão** de Action id, de `addEventCallback` e de `GlobalEvent`; 2/2 customs vivos; 0 laços aninhados. Features baratas: plugar `harvest`, `market`, `i18n`, `titulos`, e o `criarPile`.

---

