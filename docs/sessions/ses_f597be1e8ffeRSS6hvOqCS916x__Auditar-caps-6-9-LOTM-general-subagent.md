# Auditar caps 6-9 LOTM (@general subagent)

- **sessão:** `ses_f597be1e8ffeRSS6hvOqCS916x`
- **quando:** 2026-09-15 19:21 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 35 (exportadas: 9)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Você é auditor forense do projeto LOTM-voz em /home/nixos/projects/applio-lab.
SÓ LEITURA nos vivos (NUNCA edite LOTM-MAPA-VOZES.md, SESSAO-*.md, elenco-dubladores.md, casting-vol2.json, lotm-voices.json, presets/, caps/cap*.json, ~/Audio/). Escreva APENAS arquivos novos.

Leia primeiro: applio-lab/AGENTS.md, LOTM-MAPA-VOZES.md (elenco), MISSAO-CHATGPT-CAPS2-12.md (método), caps/cap01-blocking.json (modelo).

Tarefa: auditar caps/cap06.json, cap07.json, cap08.json, cap09.json.
Para cada capítulo, para CADA segmento UNKNOWN, KLEIN suspeito, NARRADOR suspeito: decida o falante usando (1) texto literal + verbo de fala + contexto de diálogo, (2) anchors-v2/epN-anchors-v2.json (spans EN×PT), (3) wiki lordofthemysteries.fandom.com/wiki/Episode_N (Adapted Chapters + resumos), (4) regras do parser em lotm-audiobook.py (speaker_of/cmd_parse) — reporte onde o parser errou e por quê.
Heurísticas validadas: pensamento 1ª pessoa=Klein; Klein=Zhou Mingrui; lore citada não condena; citação “...” lida=NARRADOR; SFX (Pá!/Toc!/etc)=SFX não fala. Cap08 tem Alger(5) e Audrey(3) — atenção redobrada a diálogos do Clube do Tarô.

Entregue por capítulo: caps/capNN-audit.md (tabela seg|atual|veredito|falante-final|evidência + seção Correções em formato --set i=FALANTE + Hipóteses + Exceções do parser) e caps/capNN-blocking.json (blocos físicos com segs, local, posição do Klein, SFX, clima — modelo cap01-blocking.json).
Quando terminar, responda com: capítulos auditados, total de segmentos, UNKNOWN resolvidos, correções propostas, hipóteses pendentes. Seja conciso e baseado em evidência.

---

## · ?

Auditoria forense caps 6-9 — lendo método e elenco para começar.

---

## · ?

Quatro capítulos carregados — buscando âncoras e referências cruzadas.

---

## · ?

Ep1 cobre novel caps 1-13 — contexto confirmado. Agora auditando segmentos suspeitos.

---

## · ?

Mapeamento de vozes e padrões de erro identificados — verificando regra SFX do parser antes de redigir.

---

## · ?

Evidência completa — redigindo os 8 arquivos de entrega.

---

## · ?

Arquivos foram para o repo errado + outro agente cobre caps 2-5/10-12 — corrigindo rota e checando o padrão dele.

---

## · ?

Padrão do outro agente compatível (rótulos descritivos). Corrigindo meu blocking e seguindo.

---

## · ?

Auditoria concluída. Nenhum vivo tocado (git: só `??` novos em caps/).

**Capítulos auditados:** 6, 7, 8, 9 → `caps/capNN-audit.md` + `caps/capNN-blocking.json` (8 arquivos novos).

**Total de segmentos:** 420 (79 + 104 + 145 + 92).

**UNKNOWN resolvidos:** 78/78 (13 + 28 + 22 + 15). Zero resíduo.

**Correções propostas (`--set`):** 107
- cap06: 16 (13 UNKNOWN→ALGER/AUDREY/KLEIN + 3 KLEIN falsos→AUDREY/ALGER segs 61,62,68)
- cap07: 32 (28 UNKNOWN + 4 KLEIN falsos→AUDREY segs 20,28,42,62)
- cap08: 35 (22 UNKNOWN→7 rótulos novos + 8 falante errado + 5 SFX: Shuasss/Pá/Crac/Honk/Bum)
- cap09: 24 (15 UNKNOWN + 74 NARRADOR→KLEIN + 78,81 KLEIN→NARRADOR + 5 SFX + 14 NARRADOR→KLEIN gemido)

**Erros sistemáticos do parser (reportados nos audits):** falso-1p dentro de citação de outro (E1 caps 6-8); aspas retas do diário→UNKNOWN em massa (cap09-E1); `vizinho` atropela sujeito explícito ("O homem...", "disse Annie" segs cap08-15,32,77,79); SFX saiu NARRADOR (parse antigo; parser atual já acerta exceto "Ffffffff!"→KLEIN, que é assopro); continuação minúscula não fundiu (cap07-E3, cap09-E3).

**Hipóteses pendentes:** cap07-seg29=AUDREY (moderada); falas do Fool→futuro split TOLO; 7 rótulos novos sem voz (CAPITAO, HOMEM-LOIRO, ANNIE, CONDE-HALL, AGUESID, GEORGE-III, MULTIDAO — fallback UNKNOWN); diário=voz Klein-original futura; segs cap09-2/3 duplicatas EN (limpeza no reparse); grafias p/ léxico (Khoy/Koi/Coi, Feysac/Feisag, Hornacis/Ornaces, Transcendente/Transcendental/Além-Mundo).

Nota: outro agente cobre caps 2-5/10-12 no mesmo formato — sem conflito. Fandom bloqueou fetch (403, sem Tavily); wiki usada via search + anchors-v2/ep1.

---

