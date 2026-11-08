# Auditar storage e persistencia (@general subagent)

- **sessão:** `ses_eeeeabc23ffeRIdYT6b30jBt06`
- **quando:** 2026-10-06 11:59 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 152 (exportadas: 9)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

OBJETIVO: auditar a camada de ESTADO PERSISTENTE (storage) do sandbox — usada por TODOS os módulos de gameplay, e comprovadamente frágil.

PASSO 1: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/11-storage.md`.
PASSO 2: investigue. PASSO 3: reescreva com relatorio + artefatos.

## Por que isto importa agora
Um agente mudou `data-sandbox/lib/sandbox/storages.lua` movendo `S.corpo` para 51170+, o que **corrige 10 das 11 colisões de storage** — mas **quebrou a suite**: 13 falhas + crash em `run_tests.lua:359` (chaves hard-coded `51050` vs `51170`). Isso mostra que o schema de storage é:
- espalhado (IDs hard-coded dentro das funções)
- sem versionamento
- sem migração

## Investigação
1. **A API de storage.** `src/game/server.cpp|hpp` (`Storage`, `getCustomStorageValue`, `setCustomStorageValue`, `getStorageValue`), `src/game/player.cpp`, e `src/lua/functions/game/*storage*`. Quais tipos de dado, que chave, e onde fica gravado (tabela MySQL? arquivo?). `arquivo:linha`.
2. **Schema do sandbox.** `data-sandbox/lib/sandbox/storages.lua` (9.2K). Liste TODAS as chaves/IDs, com faixa. Cruze com TODAS as funções que leem/escrevem cada chave (`arquivo:linha`). Ache: chave usada mas nunca declarada; chave declarada mas nunca usada; **colisão de ID** (duas features na mesma chave).
3. **Ausência de versionamento/migração.** Existe algum esquema de `storageVersion`? Se o ID ou o layout mudar, o que acontece com o save antigo do jogador? O jogo quebra silenciosamente? Descreva o cenário real de risco com `arquivo:linha`.
4. **Chaves hard-coded no teste.** `data-sandbox/tests/run_tests.lua:359` e arredores: liste as chaves literais que estão acopladas ao schema. Este é o acoplamento que quebrou.
5. **Concorrência.** Dois jogadores/threads escrevendo o mesmo storage key ao mesmo tempo. O storage é read-modify-write? `get` seguido de `set` é atômico? Lost update possível?
6. **Arquivos de estado em disco.** Descobriram antes que `saveState()` reescreve arquivo inteiro e que `data-sandbox/lib/sandbox/*.lua` de runtime state ficam DENTRO do repo (`.forno_state.lua` reescrito a cada 60s como root, fora do `.gitignore`). Confirme o estado ATUAL (o dono disse que arrumou) e mapeie todos os arquivos de state.

## Entregáveis
### A) `plans/audit-05-10/REF-STORAGE.md`
- Tabela de TODAS as chaves: `chave, tipo, quem escreve (arquivo:linha), quem lê, colide?`
- Diagrama textual do fluxo get→mutação→set
- Lista de arquivos de state em disco e onde DEVERIAM estar

### B) `plans/audit-05-10/tools/gerar-schema-storage.py`
Script que **extrai por parsing** o schema e as chaves hard-coded, e **detecta colisão**. Rode e reporte o resultado real. Este é o artefato reutilizável — um agente futuro roda e não inventa chave.

### C) No relatório: "PROPOSTA DE VERSIONAMENTO"
Um esquema concreto de `storageVersion` + migração, pequeno o suficiente para caber num dia de trabalho. Inclua o que fazer com os IDs que mudaram (o caso 51050→51170).

REGRAS:
- Só leitura/grep. **NÃO modifique nada. NÃO build. NÃO rode o server. NÃO toque em docker.**
- Pode rodar a suite Lua (read-only, `nix-shell -p lua --run "lua data-sandbox/tests/run_tests.lua"`). Se rodar, rode e reporte a saída REAL, e diga se ainda está flaky.
- O script em `plans/audit-05-10/tools/` pode escrever lá — mas NADA nos repos.
- Números, `arquivo:linha`.

Mensagem final: 10 linhas — quantas chaves, quantas colisões, e o teste ainda falha?

---

## · ?

Suite passa (381 OK). Vou investigar o resto.

---

## · ?

Agora vou escrever a ferramenta de extração.

---

## · ?

O parser está pegando item-ids. Vou reescrever com resolução por uso.

---

## · ?

Agora atualizo a varredura de uso para resolver escrita por nome e uso dinâmico.

---

## · ?

Agora gero o artefato Markdown.

---

## · ?

Agora escrevo o relatório.

---

## · ?

Agora o relatório.

---

## · ?

Entregáveis prontos: `11-storage.md` (711 linhas), `REF-STORAGE.md` (613, gerado), `tools/gerar-schema-storage.py` (814, `--strict` exit 1).

**180 chaves** distintas (146 em `storages.lua`, 22 journal, 8 constantes locais, 4 `Skill.NOVAS`, 49 sobreposições de migração); 89 fora da faixa que o próprio arquivo declara (`storages.lua:9`).

**Colisões: 8 features vivas × vivas** (a real: `51035` `S.skill.gardening` × `S.guilda.idade`, `storages.lua:64`×`:183`) **+ 49 sobreposições de migração**, 6 delas copier-and-zerar — `51050` é hoje `ship_building`, `51052` `fletching`, `51054` `stone_cutting`, `51056` `thatching`, `51058` `meditating`, `51060` `channeling`, e `sandbox_init.lua:183-201` apaga a skill e escreve o valor no corpo.

**O teste NÃO falha mais: `381 OK, 0 FALHA`, 3 execuções idênticas, não flaky.** O crash em `run_tests.lua:359` não reproduz — os literais já estão em `51170+` (mtime 08:09 vs storages 08:51), alguém já atualizou. O acoplamento segue idêntico: 25 chaves literais em `run_tests.lua:302-819`, e `data-sandbox/tests/` é **untracked e não ignorado** — a única barreira do schema não tem git nem CI.

**Zero versionamento**: nenhum `storageVersion` no repo; a migração é o próprio jogo (flags one-shot gravadas na tabela que deveria validar, ordem entre blocos só num comentário). `.gitignore` NÃO foi arrumado — o único acréscimo desde 05/10 foi `/key.pem`; `.forno_state.lua` segue root, reescrito a 60 s, dentro do repo.

Achados extras: `knapping.lua:89` usa `SKILL_CARPINTARIA` (global **nil**) → skill `-0.01`; `cacador.lua:145` grava `"x:y"` em coluna `int32` → a regra "mova 10 tiles" nunca dispara; `S.guilda`/`S.mercado` (8 chaves) não têm读写 nenhum, e o comentário em `skill.lua:211-215` que as justifica é falso.

Nada foi modificado nos repos (210 arquivos dirty, igual ao início).

---

