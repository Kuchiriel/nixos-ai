# Numeros reais de economia (@general subagent)

- **sessão:** `ses_ee9d4b180ffenTcG1MINvWHohX`
- **quando:** 2026-10-07 11:41 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 123 (exportadas: 4)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

OBJETIVO: produzir o NÚMERO REAL da economia e do balanceamento do sandbox — quanto tempo cada ação leva, quanto rende, quanto custa. Hoje é tudo feeling; isso trava tuning e cria desequilíbrio invisível.

PASSO 1: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/12-economia.md`.
PASSO 2: investigue (leitura/grep + matemática). PASSO 3: reescreva com relatorio + artefato.

## Contexto
Módulos com números hard-coded espalhados em `/home/nixos/projects/canary-official/data-sandbox/lib/sandbox/`:
`yield.lua`, `skill.lua`, `mining.lua`, `ores.lua`, `metals.lua`, `forno.lua`, `materiais.lua`, `recipes.lua`, `quality.lua`, `economia.lua`, `market.lua`, `harvest.lua`, `fishing.lua`, `fishes.lua`, `seeds.lua`, `growth.lua`, `butcher.lua`, `fauna.lua`, `growth_data.lua`, `realdata.lua`, `dataset.lua`, `decay.lua`.

`rateSkill` (skill advance) **nunca foi medido com player real**. Sem números, não dá pra dizer se um skill é rápido ou lento.

JÁ SABIDO (use como pista, re-verifique se puder): fundição/aço/imp estão **inacessíveis** porque `Fornos.criarPile` estava sem caller (diz ter sido arrumado) e o forno não passa de 900 °C. `Eco` tinha estado duplicado (diz ter sido arrumado).

## Investigação
1. **Yield por recurso.** Para cada recurso: quanto rende por ação, cooldown, e onde está o número (`arquivo:linha`). Cubra mineração, madeira, pesca, farming, caça, cozinha.
2. **Cadeia de valor.** Matéria-prima → produto, via `metals.lua`, `recipes.lua`, `forno.lua`. Quais produtos são possíveis hoje e quais seguem inacessíveis. **Faça a aritmética**: minutos de jogo para produzir 1 unidade de cada produto, do primeiro passo ao produto final, incluindo skill necessária.
3. **Progressão de skill.** `skill.lua`: fórmula de `rateSkill`, tempo para +1 nível, curva, teto. `growth_data.lua` bate com `realdata.lua`/`dataset.lua`?
4. **Market.** `market.lua`: como `precoLiquido` forma preço, spread, e se há fonte de inflação/déflação. `economia.lua`: o que controla.
5. **QL e decay.** `quality.lua`: distribuição de tiers, quanto QL afeta valor. `decay.lua`: duração por QL.
6. **Desequendimentos.** Números que se contradizem entre módulos; recurso que é espontaneamente mais rentável que outro com esforço equivalente. APRESENTE A CONTA.

## Entregáveis
### A) `plans/audit-05-10/REF-BALANCEAMENTO.md`
Tabela por cadeia: `recurso -> produto -> tempo total (min) -> skill -> arquivo:linha do número`. Mais o item mais rentável e o mais inacessível, com a conta aberta.

### B) `plans/audit-05-10/REF-BALANCEAMENTO.json`
Dados estruturados (yield, cooldowns, receitas, tempo de produção). **Gerado por parsing** dos módulos, não digitado à mão. Script em `plans/audit-05-10/tools/`.

### C) No relatório: "5 AJUSTES DE MAIOR IMPACTO"
Onde mexer para o jogo parar de ser trivial de grindar. Cada um com: valor atual, valor sugerido, justificativa pela aritmética.

REGRAS:
- Só leitura/grep + aritmética. **NÃO modifique nada. NÃO build. NÃO rode o server. NÃO toque em docker.**
- **NÃO invente números.** Todo número precisa de `arquivo:linha` de origem, OU marcado explicitamente como "ESTIMADO (derivado de X)".
- Número divergente em dois lugares = ACHADO, reporte o conflito.
- Foco estático. Pode rodar a suite Lua read-only se precisar confirmar, mas não é obrigatório.

Mensagem final: 10 linhas — cadeia mais barata e mais cara em tempo de jogo, e os 5 ajustes propostos.

---

## · ?

I'll start by marking the work in progress, then investigate the sandbox modules.

---

## · ?

Existing REF-BALANCEAMENTO artifacts found from a prior run (report itself was never written). I'll verify the numbers independently against source, then write the report.

---

## · ?

Relatório pronto. `12-economia.md` (719 linhas) + artefatos `REF-BALANCEAMENTO.md/.json` (102 KB, 34 blocos, 396 fontes `arquivo:linha`, gerados por parsing via `tools/gen_ref_balanceamento.py`). Read-only respeitado: nada no datapack foi tocado.

**Mais barata:** lenha willow com maul 3208 — **1.64 min/árvore** (1.47 golpes × 10 stamina ÷ 9 regen), 3 unidades = 0.55 min/un. Oak é52% mais caro para o mesmo.
**Mais cara:** aço 55105 — **17.3 min**, dos quais **12 são relógio** (pilha de carvão = 5 min de espera + 8 ticks de calor); a espada sai a 28.9 min (15.9 de jogo + 13 de relógio). O gargalo não é habilidade: a veia 16135 tem 0 cópias no mapa, então o minério vem da pedra comum a 15%/ciclo.

Os 5 ajustes:

1. **Remover `skill = 100` do primeiro login** (`sandbox_init.lua:101-115`). Hoje:100% de sucesso na dif. 2 e QL média 85 — acima do CAP 70 da curva. É o que trava os outros quatro.
2. **`Yield.SCALE` 2.0 → 5.0** e dar power 1.30 à strong pick. `n ≥ 2` exige power ≥ 1.50; a mais forte do jogo tem 1.30, então o yield é sempre 1 na mineração. Efeito: 3.95 → 1.98 min/ore.
3. **Mover o `0.15` de `mining.lua:243` para `Ores.balance` e semear veias no mapa.** Espada: 28.9 → 8.6 min de jogo, e os 25 ciclos por veia viram limite de recurso.
4. **`pile_ticks` 5 → 2** (`forno.lua:60`). Corta 3 dos 13 min de relógio da espada. `carvao_por_pile` não serve: as pilhas amadurecem em paralelo, então só muda madeira, não tempo.
5. **Usar o `local b` morto em `skill.lua:133`.** Hoje QL 50 e QL 100 na mão dão o roll idêntico — o `imping` inteiro é custo sem retorno.

Dois bloqueadores antes do 4: a pá não está no kit inicial e `charcoal.lua:16-18` rejeita a lenha que o kit dá (5295/5297/3684 vs 55001-55009) — hoje o carvão é literalmente inalcançável pelo caminho normal.

---

