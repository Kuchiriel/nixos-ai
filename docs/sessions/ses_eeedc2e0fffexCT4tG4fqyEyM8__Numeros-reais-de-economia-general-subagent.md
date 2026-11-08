# Numeros reais de economia (@general subagent)

- **sessão:** `ses_eeedc2e0fffexCT4tG4fqyEyM8`
- **quando:** 2026-10-06 12:15 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 201 (exportadas: 1)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

OBJETIVO: produzir o NÚMERO REAL da economia e do balanceamento do sandbox — quanto tempo cada ação leva, quanto rende, quanto custa. Hoje é tudo feeling; isso trava tuning e cria 균형 invisível.

PASSO 1: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/12-economia.md`.
PASSO 2: investigue. PASSO 3: reescreva com relatorio + artefato.

## Por que
Vários módulos existem e têm números hard-coded espalhados: `yield.lua`, `skill.lua`, `mining.lua`, `ores.lua`, `metals.lua`, `forno.lua`, `materiais.lua`, `recipes.lua`, `quality.lua`, `economia.lua`, `market.lua`, `quality`. `rateSkill` (skill advance) **nunca foi medido com player real**. Sem isso não dá pra dizer se um skill é rápido ou lento.

## Investigação
1. **Yield por recurso.** Para cada recurso coletável/crafteável: quanto rende por ação, quanto tempo de cooldown, e onde está o número (`arquivo:linha`). Cubra: mineração (`mining.lua`, `ores.lua`), madeira (`harvest.lua`? `trees`), pesca (`fishing.lua`, `fishes.lua`), farming (`seeds.lua`, `growth.lua`), caça (`butcher.lua`, `fauna.lua`), cozinha (`forno.lua`, receitas).
2. **Cadeia de valor.** Matéria-prima → produto. `metals.lua`, `smelt`, `recipes.lua`. Quais produtos são possíveis hoje, e **quais são inacessíveis** (sabe-se que fundição/aço/imp estão travados). Custo em tempo de cada item finished, do primeiro gpio até o produto final. Quanto tempo, em minutos de jogo, para um personagem produzir 1 unidade?
3. **Progressão de skill.** `skill.lua`: fórmula de `rateSkill`, quanto tempo para subir 1 nível, curva, e o teto. Os valores em `growth_data.lua` batem com `realdata.lua`/`dataset.lua`?
4. **Market/economia.** `market.lua`: como o preço é formado (`precoLiquido`), spread, e se há fonte de-tested de inflação/déflação. `economia.lua`: o que ele controla.
5. **QL.** `quality.lua`: distribuição de tiers, quanto QL afeta o valor real? `decay.lua`: quanto dura um item por QL?
6. **Inconsistências de balanceamento.** Ache números que se contradizem entre módulos. Exemplo do tipo: um recurso é exoticamente rentável comparado a outro同等 effort. FAÇA A ARITMÉTICA e apresente.

## Entregáveis
### A) `plans/audit-05-10/REF-BALANCEAMENTO.md`
Tabela por cadeia: `recurso base -> produto -> tempo total (min) -> skill necessária -> onde está o número`. Mais o item mais rentável e o mais inacessível, com a conta.

### B) `plans/audit-05-10/REF-BALANCEAMENTO.json`
Dados estruturados: yield, cooldowns, receitas, tempo de produção. Gerado por parsing dos módulos (script em `plans/audit-05-10/tools/`), não digitado à mão.

### C) No relatório: "5 AJUSTES DE BALANCEAMENTO DE MAIOR IMPACTO"
Onde mexer para o jogo parar de ser trivially grindy / trivially punível. Cada um com: valor atual, valor sugerido, e por quê. Seja concreto e defensável pela aritmética do catálogo.

REGRAS:
- Só leitura/grep + matemática. **NÃO modifique nada. NÃO build. NÃO rode o server. NÃO toque em docker.**
- NÃO invente números. Todo número no relatório precisa de `arquivo:linha` de onde veio, OU ser explicitamente marcado como "ESTIMADO (derivado de X)".
- Se um número estiver em mais de um lugar e divergirem, isso é ACHADO — reporte o conflito.
- Pode rodar a suite Lua read-only se precisar confirmar comportamento, mas o foco é ESTÁTICO.

Mensagem final: 10 linhas — qual a cadeia mais barata e a mais cara em tempo de jogo, e quais os 5 ajustes propostos.

---

