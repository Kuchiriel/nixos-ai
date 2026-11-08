# Catálogo de eventos e ordem de carga (@general subagent)

- **sessão:** `ses_eeefe90e2ffeu24vUheULvbrWW`
- **quando:** 2026-10-06 11:37 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 147 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

OBJETIVO: produzir o CATÁLOGO DE EVENTOS/HOOKS do servidor + a ORDEM DE CARGA dos módulos Lua, para eliminar uma classe inteira de bug (duplo registro, ordem indefinida, estado duplicado).

PASSO 1: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/10-eventos.md`.
PASSO 2: investigue. PASSO 3: reescreva com relatorio + artefatos.

## Bug classe que isto elimina (já aconteceu)
`data-sandbox/lib/sandbox/eco.lua:45` — `Eco` é tabela **global** e é `dofile`ado de DOIS arquivos → **duas tabelas independentes** → `cut.lua:555` e `terraform.lua:261` apagam o estado uma da outra. Mesmo padrão em `Grove` (3 instâncias). E `baking.lua:25`/`pottery.lua:15` fazem `dofile` do forno em escopo de arquivo → instância congelada no boot → functionality impossível.

Então: qualquer agente que use `dofile`, require dinâmico, ou estado global sem singleton explícito vai reintroduzir isso. Quero a referência que mostra COMO fazer certo.

## Investigação
1. **Todos os eventos disponíveis.** Fontes: `src/game/game.cpp` / `game.hpp` (tipos de evento), `src/game/scheduler/` (`Event`, `EventHandler`, `Scheduler`), e o lado Lua: `data/libs/event.lua`, `data/libs/eventdispatcher.lua`. Liste CADA evento: nome, assinatura, quando dispara, `arquivo:linha` do `addEvent`/`scheduleEvent` no C++ e do dispatch em Lua.
2. **Hook de ScriptEvent.** Os talkactions, creaturescripts, spellscripts, misc (login/logout/death/etc), GlobalEvent, `GlobalEventScheduler`. Como cada tipo se registra e como o servidor escolhe qual handler roda quando há MAIS DE UM (prioridade? primeiro registrado? ordem de load?). **Esta é a pergunta que mais importa.**
3. **A mecânica de carregamento.** `data/libs/loader.lua` (ou equivalente): como ele acha os arquivos? Qual a ordem alfabética de load de `data-sandbox/scripts/`? `addEventCallback` empilha ou substitui? O que acontece se dois módulos registram o MESMO callback no mesmo evento?
4. **Diagnóstico de estado duplicado.** Escreva (ou descreva) como provar, em runtime, que duas referências não são a mesma tabela: compare `rawequal()`/endereço. Documente os pontos do codebase onde isso já acontece (eco, Grove, forno, e procure outros `dofile` em `data-sandbox/`).
5. **Auditoria de `dofile`/require dinâmico.** Liste TODOS os `dofile`, `require`, `loadfile` em `data-sandbox/` e `data/` com `arquivo:linha`, e diga para cada: cria estado compartilhado em risco? Use singleton? É seguro?

## Entregáveis
### A) `plans/audit-05-10/REF-EVENTOS.md`
Todos os eventos com assinatura + semântica de "quem ganha quando há dois handlers".

### B) `plans/audit-05-10/REF-EVENTOS.md` seção "PADRÕES CORRETOS"
O HOW-TO que resolve a classe do bug do Eco: como declarar estado singleton, como registrar callback sem colidir, como fazer ordem determinística. Com código copiado de onde já está certo (não invente — cite um exemplo bom real do repo).

### C) No relatório: tabela de `dofile`/estado compartilhado
| arquivo:linha | padrão | risco | correção |

### D) `plans/audit-05-10/tools/auditar-estado-duplicado.lua`
Um script Lua standalone que um agente possa rodar (em modo read-only, ou usando os próprios arquivos) para detectar se dois `dofile` do mesmo módulo criam tabelas divergentes. Documente como usar.

REGRAS:
- Só leitura/grep. **NÃO modifique nada. NÃO build. NÃO rode o server. NÃO toque em docker.**
- Pode rodar a suite de testes se for read-only (já se sabe como: `nix-shell -p lua --run "lua data-sandbox/tests/run_tests.lua"`), mas **cuidado: ela é não-determinística** (falha 2 de 3 runs por roll sem semente em `forno.lua:247`). Se rodar, rode 3x e reporte.
- Cite `arquivo:linha` sempre.

Mensagem final: 10 linhas — quantos eventos, e diga a resposta da pergunta-chave: "quando dois handlers registram o mesmo evento, quem roda?".

---

## · ?

I'll start by marking the file as in progress, then investigate.

---

## · ?

Now writing the tool (deliverable D):

---

## · ?

Now the main report (deliverable C):

---

## · ?

Entregue. Resposta final:

**Eventos: 94 assinaturas distintas** — 45 `EventCallback` (`callbacks_definitions.hpp:20-73`, tabela completa em REF-EVENTOS §2.2), 12 `CreatureEvent`, 7 `GlobalEvent`, 8 `MoveEvent`, `TalkAction.onSay`, `Action.onUse`, `Module.onRecvbyte`, `addEvent` + 18 slots XML legados.

**Pergunta-chave — quando dois handlers registram o mesmo evento, quem roda?**
`EventCallback`: **os dois rodam, empilhados num `std::vector`** (`events_callbacks.hpp:125`) em **ordem de registro** — e a ordem de registro é a ordem de `readdir`, porque `scripts.cpp:105` itera `recursive_directory_iterator` **sem sort** (medido: `actions, creaturescripts, lib, movements, spells, globalevents…`). Ou seja, **indefinida e diferente em cada máquina e a cada `/reload`** (`game_reload.cpp:186` zera tudo e relê). Nome repetido → o 2º é rejeitado com erro. Todo o resto (`CreatureEvent`/`GlobalEvent`/`TalkAction`/`Action`/`MoveEvent`/`Module`) é `std::map` por chave: **o 2º é silenciosamente descartado e a ordem é alfabética pela chave**.

**Achados que importam mais:** `eco.lua` e `forno.lua` foram consertados, mas `foragepool.lua:23-33` e `populacao.lua:54-58` **têm o comentário "SINGLETON" e estão errados** (`local M = {}` antes do global; `local M = M or SandboxPopulacao` é no-op). `grove.lua:35,39` não tem singleton nenhum → 4 ilhas de estado (plantar ≠ crescer). `terraform.lua:82` tem 2 sítios, um deles dentro de função (`cut.lua:232`) → bug do Eco ainda vivo. E os 8 `require("sandbox.X")` são **código morto**: não há `package.path` em lugar nenhum do core.

Entregáveis: `plans/audit-05-10/10-eventos.md`, `plans/audit-05-10/REF-EVENTOS.md` (§8 PADRÕES CORRETOS, com o HOW-TO e a armadilha do `local M = M or G`), `plans/audit-05-10/tools/auditar-estado-duplicado.lua` (read-only: copia `lib/` pro `$TMPDIR`, faz 2 `dofile`, `rawequal` + sentinel por sub-tabela; exit 1 = risco). Suíte 3×: **381 OK / 0 FALHA** — a não-determinismo de `forno.lua:247` não reproduziu. Nada modificado no repo.

---

