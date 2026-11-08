# Inventário de docs do projeto (@general subagent)

- **sessão:** `ses_eeec5c968ffeg5mD8BD5VBCc87`
- **quando:** 2026-10-06 12:39 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 11 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

READ-ONLY. Não edite, não mova, não delete NADA. No monorepo /home/nixos/projects (foco: canary-official/, otclient/, plans/, docs/, nixos-ai/docs/):

1. Liste TODOS os arquivos .md (por repo/pasta, com linhas e mtime). 
2. Detecte: duplicatas de conteúdo (mesmo assunto em 2+ arquivos), docs com números/paths comprovadamente errados (ex: SYSTEM-MAP.md que erra inventário, contagens de testes desatualizadas, portas erradas), docs órfãos (ninguém linka), e docs ativamente escritos por outro agente AGORA (mtime nas últimas 6h — marque como ZONA DE CONFLITO, não tocar).
3. Para docs/agent-notes/handoffs em ~/.local/state/jarvis/ e docs/HANDOFF*, só liste nomes+datas.
4. Devolva: tabela pasta|arquivo|linhas|mtime|status(ok/duplicado-de-X/desatualizado/conflito-ativo) + ao final uma PROPOSTA de consolidação (o que mergear, o que arquivar, o que atualizar) SEM executar. Terse, sem enrolação.

---

## · ?

Inventário read-only dos .md — levantando lista, datas e links.

---

## · ?

Lista base pronta — agora checando conteúdo, links e conflitos recentes.

---

## · ?

Quase lá — verificando órfãos, duplicatas e datas dos handoffs.

---

## · ?

READ-ONLY cumprido — nada editado/movido/deletado. `date UTC 2026-10-06 12:39`. Corte conflito-ativo: `>06:39 hoje`.

## 1. Tabela foco `pasta|arquivo|linhas|mtime|status`

### `canary-official/` (núcleo; upstream `docs/` OK omitido — 37 arqs 2026-08-24 intocados)
```
canary-official|AGENTS.md|46|2026-10-01|ok
canary-official|README.md|152|2026-10-01|ok
canary-official|docker/DOCKER.md|381|2026-10-01|ok
canary-official|docker/SANDBOX-RUNBOOK.md|176|2026-10-01|ok
canary-official|docs/building/build-sem-vcpkg.md|172|2026-10-03|desatualizado+orfao (conflita nix-shell vs AGENTS raiz; 5 building orfaos)
canary-official|docs/sandbox/api-pitfalls-canary-otclient.md|337|2026-10-02|ok (canonico, linkado por HANDOFFs)
canary-official|docs/prompts/overnight-local-ai.md|162|2026-10-03|desatualizado (receita nix-shell proibido)
canary-official|docs/README.md|298|2026-10-01|desatualizado (diz 4 guides, tem 8; omite 5 dirs — prova 06-docs-dados §4)
canary-official|data-sandbox/DATASET-README.md|105|2026-10-01|ok
canary-official|data-sandbox/README.md|43|2026-10-01|ok
canary-official|data-sandbox/docs/LOOP.md|390|2026-10-06 09:00|CONFLITO-ATIVO (outro agente escrevendo agora; tb duplicado-de-HANDOFFs+#wurm-docs)
canary-official|data-sandbox/docs/HANDOFF-2026-10-02.md|114|2026-10-02|desatualizado (superseded; prefixo canary-official/ duplicado; orfao p/ 06 §docs-orfaos)
canary-official|data-sandbox/docs/HANDOFF-2026-10-03.md|105|2026-10-03|desatualizado (superseded; “177 OK” vs real 366 + flaky 2/3)
canary-official|data-sandbox/docs/HANDOFF-2026-10-04.md|84|2026-10-04|desatualizado (superseded; orfao)
canary-official|data-sandbox/docs/HANDOFF-2026-10-05.md|68|2026-10-05|desatualizado (LEIA PRIMEIRO aponta vault/PENDENTES-SESSAO-0510.md INEXISTENTE — 06 #3)
canary-official|data-sandbox/docs/AUDITORIA-2026-10-03.md|78|2026-10-03|desatualizado CRITICO (itemtypes 552xx nao existem, max 55018; 269 vs 366 testes; skills 51001-20 movida p/51100+)
canary-official|data-sandbox/docs/CLIENTE-NAO-ENTRA-0xA1…md|248|2026-10-05|ok (canonico login; manter)
canary-official|data-sandbox/docs/CLIENT-sprites…|179|2026-10-04|orfao (06 lista)
canary-official|data-sandbox/docs/CONFIG-raiz-vs-docker.md|143|2026-10-04|desatualizado+orfao (zones.xml inexistente; mounts 6 vs 11)
canary-official|data-sandbox/docs/COORDENACAO.md|90|2026-10-03|desatualizado (server DERRUBADO vs Up 4h; mounts errados)
canary-official|data-sandbox/docs/LOGIN-estado-04-10.md|224|2026-10-04|desatualizado (superseded p/ LOOP#68 PASS 05/10)+orfao
canary-official|data-sandbox/docs/LOGIN-raiz-primeiro-pacote.md|134|2026-10-04|duplicado-de-LOGIN-estado/CLIENTE-NAO-ENTRA
canary-official|data-sandbox/docs/BLOCKER-tile-setground-lua.md|69|2026-10-03|ok
canary-official|data-sandbox/docs/{colheita,mineracao,pesca,corpo,cozinha,forno,terraform,QL,corpo…}-wurm.md|~73-176|2026-10-02/03|duplicado-de-LOOP.md#itens (conteudo espelhado) + paths tools/*.lua errados (real: scripts/actions/)
canary-official|data-sandbox/docs/{MAPA,ROADMAP,SESSAO-input,UI-RESKIN,auditoria-mundo}…|43-133|2026-10-02/04|desatualizado (auditoria-mundo: 119 refs vs 26; taiga/tundra vs boreal/polar) / orfao
canary-official|data-sandbox/docs/HOUSES-fencing…|128|2026-10-03|orfao
canary-official|dataset/wurm/MECANICAS-MAPA.md|176|2026-10-03|duplicado-de-wurm-docs+sandbox
canary-official|dataset/maps/README.md|62|2026-10-05|ok (verificado 06 §5)
canary-official|dataset/stubs/{SPEC-mine,skill-ql,smelt,thirst,PREENCHER}|73-135|2026-10-02|orfao (4 SPECs) + duplicado-de-MECANICAS
canary-official|dataset/auditoria/relatorios/1..6|7-170|2026-10-03|orfao (6/6, 06 §docs-orfaos)
canary-official|dataset/tibia/windows-gap.md|76|2026-10-02|orfao
```
### `otclient/` (+ `-upstream`/`-mehah*` = espelhos)
```
otclient|AGENTS.md|34|2026-10-01|ok
otclient|DOC-OTCLIENT-04-10.md|137|2026-10-04|desatualizado (§6 janelas: causa real achada 05/10 inventory.lua:539+skills.lua:1286, doc ainda em hipotese)
otclient|HANDOFF-IMAGEM-UI.md|337|2026-10-05|ok-parcial (inventario blackfun/imagens canonico; §6 obsoleto mesmo motivo; §151 imgs: 150/151 sao 3os = nao mexer)
otclient|LOGIN-DIAGNOSTICO.md|108|2026-10-01|desatualizado-OBSOLETO (BLOQUEADO 01/10 vs ENTROU 05/10 LOOP#68)
otclient|docs/cyclopedia-skills-ui.md|100|2026-10-03|ok (causa SkillNameLabel confirmada) mas orfao (0 refs)
otclient|docs/{otml-variables,client-assets-auto-install,string-encoding}…|~100-306|2026-10-01|ok (otml/client-assets linkados pelo AGENTS gate)
otclient|docs/building/* (7 arqs)|59-103|2026-10-01|duplicado-de-otclient-upstream/docs/building/* (byte-identicos)
otclient|experimentos-otui/INVENTARIO-ASSETS.md|85|2026-10-05|ok | otui-merge2/_VEREDITO_v2.md|43|2026-10-05|ok
otclient-upstream/*, otclient-mehah/*, -clean/*|—|2026-08-31/10-01|duplicado-de-otclient (README/CHANGELOG/building/string-encoding; upstream = referencia, mehah = comparar-e-arquivar)
```
### `plans/`
```
plans|AGENTS.md|14|2026-09-18|ok
plans|anti-entropy-plan.md|75|2026-09-12|ok | relatorio-contradicoes-docs.md|153|2026-09-12|ok (guia-renamer; historico)
plans|relatorio-unico-muse-spark.md|153|2026-09-11|orfao/historico | nixpkgs-*|291/781|2026-08-22|orfao/historico
plans|audit-05-10/00-SINTESE.md|240|2026-10-05|ok (CANONICO auditoria; aponta 22 docs drift)
plans|audit-05-10/01-server-cpp.md|506|2026-10-05|ok | 02-seguranca|341|2026-10-05|ok | 03-sandbox-lua|497|2026-10-05|ok | 04-client|714|2026-10-05|ok | 05-infra|536|2026-10-05|ok | 06-docs-dados|455|2026-10-05|ok (CANONICO drift/orfaos)
plans|audit-05-10/07-protocolo.md|179|2026-10-06 07:55|CONFLITO-ATIVO | 08-catalogo-item|298|08:16|CONFLITO-ATIVO | 09-api-lua|341|08:36|CONFLITO-ATIVO | 10-eventos|411|08:58|CONFLITO-ATIVO | 11-storage|712|09:14|CONFLITO-ATIVO | 12-economia|1|09:15|CONFLITO-ATIVO (vazio!)
plans|audit-05-10/REF-PROTOCOLO-1525.md|1002|07:54|CONFLITO-ATIVO + duplicado-de-07 | REF-PROTOCOLO-REGRA|557|07:54|CONFLITO-ATIVO+dup-07 | REF-ITEM-SPRITE|470|08:15|CONFLITO-ATIVO+dup-08 | REF-API-LUA-surface|2067|08:36|CONFLITO-ATIVO+dup-09 | REF-API-LUA|426|08:36|CONFLITO-ATIVO+dup-09 | REF-EVENTOS|707|08:58|CONFLITO-ATIVO+dup-10 | REF-STORAGE|614|09:12|CONFLITO-ATIVO+dup-11
```
### `docs/` (raiz)
```
docs|AGENTS.md|11|2026-09-18|ok (router)
docs|architecture/SYSTEM-MAP.md|116|2026-09-23|desatualizado COMPROVADO (erra 5/6 numeros §1: 1798 vs 2112; 18 vs 42 .git; 7 vs 19 gitlinks; docs/ vazio vs 26 arqs; ~/ existe vs arquivado; OTServer untracked vs .git 3.1GB; prism 798MB vs 1.5GB — 06 §1 + 00-SINTESE Fase3.15)
docs|architecture/SOURCES-OF-TRUTH|48|2026-09-15|ok | DEPENDENCY-GRAPH|75|2026-09-15|ok | CONTRATO-LAB-NIXOS|88|2026-09-15|ok
docs|audits/SECURITY|36|2026-09-15|ok | ENTROPY|72|2026-09-15|ok | DOCUMENTATION|58|2026-09-15|ok-desatualizado (pre-drift-10-05)
docs|improvements/INDEX.md|48|2026-09-23|desatualizado (contradicao interna: tabela 013 VALIDATING/014 DISCOVERED vs bloco contagem ambos DISCOVERED; contagens 1116/0 vs AGENTS 1105/0)
docs|improvements/001..015|~42-102|2026-09-15/23|ok (DONE/VALIDATING por doc; nao mexer sem dono p/ 012/014/015)
docs|COMFYUI/PRODUTOS/RELATORIO-MISSAO|—|2026-09-15/25|orfao (0-1 refs)
```
### `nixos-ai/docs/` (resumo; `archive/` = ja arquivado, ok)
```
nixos-ai/docs|HANDOFF-2026-09-25.md|138|2026-09-25|desatualizado (superseded) | HANDOFF-09-26-MANHA|11|2026-09-26|desatualizado | HANDOFF-09-29|31|2026-09-30|desatualizado | HANDOFF-10-03|81|2026-10-03|desatualizado (superseded) | HANDOFF-10-05|88|2026-10-05|ok (mais novo; canonico atual)
nixos-ai/docs|README/SISTEMA-ESTADO/TIERS-E-PAPEIS/LESSONS/SINTESE/REIDRATAR…|—|2026-09-25/10-01|ok (TIERS-E-PAPEIS + SISTEMA-ESTADO = fonte tiers/ports; resto historico)
nixos-ai/docs|architecture/SYSTEM-MAP.md|54|2026-09-18|desatualizado (HEADs 1d9e803/c9824ea stale; nome COLIDE com docs/architecture/SYSTEM-MAP)
nixos-ai/docs|audit/{CYCLE-4..9,~30 EXPERIMENTs 9-40 linhas}|—|2026-09-21|duplicado-entre-si + orfao (micro-experimentos; manter pasta, nao linkar 1:1)
nixos-ai/docs|benchmarks/*, audit/current+completed|—|2026-08/09|ok/historico (nao tocar)
```

## 2. Achados (dedup)
- **Duplicatas:** `otclient/docs/building/*` = `otclient-upstream/*` (manter upstream, otclient so diff real); `shared-build-cache.md` canary vs otclient; `HANDOFF-10-02/03/04/05` + `LOOP.md#1-80` + `*-wurm.md` = mesma materia 3x; `REF-*` = espelho de `07-11` (gerados na mesma sessao 07:54-09:15 hoje); `SYSTEM-MAP` x2 (raiz vs nixos-ai, renomear um); `nixpkgs-integration` vs `nixpkgs-to-nixos-ai-analysis`.
- **Desatualizados comprovados:** lista acima; piores: `docs/architecture/SYSTEM-MAP.md`, `AUDITORIA-2026-10-03.md:47-56`, `HANDOFF-2026-10-05.md:3` (link morto), `LOGIN-DIAGNOSTICO.md`, `INDEX.md` contagem, `AGENTS.md` Project Map (auto-declarado).
- **Orfaos (0 refs):** 06-docs-dados §docs-orfaos confirma 27/90: `data-sandbox/docs/` 10 (AUDITORIA, CLIENT-sprites, CONFIG, HANDOFF-02/03/04, HOUSES, LOGIN-estado, SESSAO-input, UI-RESKIN), `docs/building/` 5, `dataset/auditoria/relatorios/` 6, `dataset/stubs/SPEC-*` 4, `dataset/tibia/windows-gap`, `docs/maps/startup-loading`, `prompts/overnight-local-ai`; + `otclient/docs/cyclopedia-skills-ui`, `plans/audit-05-10/00-SINTESE` (ainda sem backlinks — linkar!), `nixos-ai HANDOFFs` antigos.
- **ZONA DE CONFLITO (nao tocar, agente ativo):** 14 arqs mtime 07:54-09:15 hoje: `plans/audit-05-10/{07,08,09,10,11,12,REF-PROTOCOLO-1525,REF-PROTOCOLO-REGRA,REF-ITEM-SPRITE,REF-API-LUA,REF-API-LUA-surface,REF-EVENTOS,REF-STORAGE}` + `canary-official/data-sandbox/docs/LOOP.md` (09:00).

## 3. `~/.local/state/jarvis/` + `docs/HANDOFF*` — so nomes+datas
- `docs/HANDOFF*` na raiz: **inexistente** (`no matches`). Handoffs vivem em `nixos-ai/docs/HANDOFF-2026-09-25,09-26-MANHA,09-29,10-03,10-05` e `canary-official/data-sandbox/docs/HANDOFF-2026-10-02,03,04,05` (datas na tabela §1).
- `~/.local/state/jarvis/vault/` .md (amostra pedido: handoffs/agent-notes/sessoes/canary/otclient): `canary-worldgen-sessao-2026-10-01.md 2026-10-01`, `canary-sandbox-api-pitfalls.md 2026-10-01`, `sandbox-mmorpg-arquitetura.md 2026-10-01`, `sandbox-mmorpg-handoff-2026-10-02.md 2026-10-02`, `sandbox-mmorpg-visao.md 2026-10-02`, `desktop-interaction-hyprland-2026-10-02.md 2026-10-02`, `otclient-input-licoes-2026-10-02.md 2026-10-02`, `sessao-23-09-mudream-lancamento.md 2026-09-23`, `sessao-24-09-consolidacao-pre-compact.md 2026-09-24`, `sessao-23-09-consolidado.md 2026-09-24`, + `agent-audit.jsonl`, `audit.jsonl` (dirs `agent-notes/`, `handoffs/` **nao existem**).

## 4. PROPOSTA (nao executar)
1. **Atualizar (1 edicao cirurgica cada, fora de conflito):** `docs/architecture/SYSTEM-MAP.md §1` (2112/42/19/docs-26-arqs/~/arquivado/OTServer-.git-3.1GB/prism-1.5GB/shared-ausente) + `docs/improvements/INDEX.md` contagem + `AGENTS.md` Project Map (apos SYSTEM-MAP) + `canary docs/README.md` (8 guides + 9 dirs) + `nixos-ai/docs/architecture/SYSTEM-MAP.md` renomear p/ `NIXOS-SYSTEM-MAP.md`.
2. **Mergear:** `REF-*` → apendice de `07-11` (deletar duplicata apos fim do conflito); `*-wurm.md` → manter como detalhe, LOOP.md vira so fila+links (tirar corpo duplicado); `LOGIN-DIAGNOSTICO.md` + `LOGIN-estado/raiz-pacote` → arquivar, canonico = `CLIENTE-NAO-ENTRA-0xA1` + `LOOP#68`; `HANDOFF-10-02/03/04` → pasta `data-sandbox/docs/superseded/` apos fixar `HANDOFF-10-05:3` (trocar PENDENTES por LOOP#64-83 ou criar o vault); `CYCLE-*/EXPERIMENT*` → manter pasta, 1 indice.
3. **Arquivar (mover, nao deletar):** `otclient-mehah*/` (diff vs upstream, depois arquivar 1), `dataset/auditoria/relatorios/1-6` → `dataset/auditoria/superseded/` (substituidos por REF-STORAGE/0xA1), `plans/nixpkgs-*,relatorio-unico,solar-mission` → `plans/superseded/`.
4. **Orfaos:** criar `data-sandbox/docs/INDEX.md` (COORDENACAO+LOOP nao indexam os 26) listando os 28 + status; linkar `00-SINTESE` e `06-docs-dados` a partir dos HANDOFFs/LOOP; nao deletar `blackfun/` untracked (3 versionados dependem — 00-SINTESE Fase0.5).
5. **Ordem:** esperar fim do conflito (14 arqs) → Fase0 gameplay (00-SINTESE §Fase0, 6 edicoes) → docs acima.

---

