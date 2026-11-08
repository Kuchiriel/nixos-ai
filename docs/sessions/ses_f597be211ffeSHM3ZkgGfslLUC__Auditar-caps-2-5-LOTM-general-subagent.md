# Auditar caps 2-5 LOTM (@general subagent)

- **sessão:** `ses_f597be211ffeSHM3ZkgGfslLUC`
- **quando:** 2026-09-15 19:21 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 21 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Você é auditor forense do projeto LOTM-voz em /home/nixos/projects/applio-lab.
SÓ LEITURA nos vivos (NUNCA edite LOTM-MAPA-VOZES.md, SESSAO-*.md, elenco-dubladores.md, casting-vol2.json, lotm-voices.json, presets/, caps/cap*.json, ~/Audio/). Escreva APENAS arquivos novos.

Leia primeiro: applio-lab/AGENTS.md, LOTM-MAPA-VOZES.md (elenco), MISSAO-CHATGPT-CAPS2-12.md (método), caps/cap01-blocking.json (modelo).

Tarefa: auditar caps/cap02.json, cap03.json, cap04.json, cap05.json.
Para cada capítulo, para CADA segmento UNKNOWN, KLEIN suspeito, NARRADOR suspeito: decida o falante usando (1) texto literal + verbo de fala + contexto de diálogo, (2) anchors-v2/epN-anchors-v2.json (spans EN×PT), (3) wiki lordofthemysteries.fandom.com/wiki/Episode_N (Adapted Chapters + resumos), (4) regras do parser em lotm-audiobook.py (speaker_of/cmd_parse) — reporte onde o parser errou e por quê.
Heurísticas validadas: pensamento 1ª pessoa=Klein; Klein=Zhou Mingrui; lore citada não condena; citação “...” lida=NARRADOR; SFX (Pá!/Toc!/etc)=SFX não fala.

Entregue por capítulo: caps/capNN-audit.md (tabela seg|atual|veredito|falante-final|evidência + seção Correções em formato --set i=FALANTE + Hipóteses + Exceções do parser) e caps/capNN-blocking.json (blocos físicos com segs, local, posição do Klein, SFX, clima — modelo cap01-blocking.json).
Quando terminar, responda com: capítulos auditados, total de segmentos, UNKNOWN resolvidos, correções propostas, hipóteses pendentes. Seja conciso e baseado em evidência.

---

## · ?

Auditoria forense cap 02-05 — lendo briefing e modelo.

---

## · ?

Modelo e capítulos lidos — buscando parser, âncoras e wiki.

---

## · ?

Evidência reunida — escrevendo os 8 arquivos.

---

## · ?

Auditoria concluída. 8 arquivos novos em `caps/`; nada vivo tocado.

- **Capítulos auditados**: 02, 03, 04, 05
- **Total de segmentos**: 372 (81 + 74 + 107 + 110)
- **UNKNOWN resolvidos**: 44/44 (42 firmes + 2 hipóteses: 107/109 do uníssono na névoa)
- **Correções propostas (`--set`)**: 71 firmes
  - cap02: 14 (inclui 0,27→SFX; 25→NARRADOR; resto→KLEIN)
  - cap03: 11 (27,42,52,57,58,66,67→MELISSA; 10,35,50,60→KLEIN)
  - cap04: 19 (35-40→VENDEDOR; 57,59,60,70,75→WENDY; 86,90,106→TREINADORA; 56,61,82,89,91→KLEIN)
  - cap05: 27 (12,14,17,20,23,26,27,29,30,34,39→TREINADORA; 37,41,43→CARTOMANTE; 91,92,95→AUDREY; 8→NARRADOR; 15,19,21,25,42,44,49,75,80→KLEIN)
- **Hipóteses pendentes**: 10 (cap03: 45,46; cap04: 13,14,54,83; cap05: 46,47,107,109) — todas monólogo interno sem 1ª pessoa ou ordem do uníssono; confirmar c/ livro EN.

Exceções do parser (detalhe em cada audit): nome fora do NAMES (Wendy, papéis em minúsculas) é a falha mais cara (caps 4-5); verprecedência de vizinho sobre sujeito próprio (cap4-57, cap5-30); 1ª pessoa de OUTRO contamina pensamento-1p (cap3-52, cap4-90, cap5-14/20/39/95); VERBS sem infinitivo/gerúndio/imperfeito e sem "questionou/leu"; SFX_WORDS sem clinque/clangue; pergunta-dedução só splita intra-parágrafo.

---

