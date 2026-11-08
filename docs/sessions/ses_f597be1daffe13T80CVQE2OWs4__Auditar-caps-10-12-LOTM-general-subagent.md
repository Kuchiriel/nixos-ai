# Auditar caps 10-12 LOTM (@general subagent)

- **sessão:** `ses_f597be1daffe13T80CVQE2OWs4`
- **quando:** 2026-09-15 19:21 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 16 (exportadas: 6)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Você é auditor forense do projeto LOTM-voz em /home/nixos/projects/applio-lab.
SÓ LEITURA nos vivos (NUNCA edite LOTM-MAPA-VOZES.md, SESSAO-*.md, elenco-dubladores.md, casting-vol2.json, lotm-voices.json, presets/, caps/cap*.json, ~/Audio/). Escreva APENAS arquivos novos.

Leia primeiro: applio-lab/AGENTS.md, LOTM-MAPA-VOZES.md (elenco), MISSAO-CHATGPT-CAPS2-12.md (método), caps/cap01-blocking.json (modelo).

Tarefa: auditar caps/cap10.json, cap11.json, cap12.json.
Para cada capítulo, para CADA segmento UNKNOWN, KLEIN suspeito, NARRADOR suspeito: decida o falante usando (1) texto literal + verbo de fala + contexto de diálogo, (2) anchors-v2/epN-anchors-v2.json (spans EN×PT), (3) wiki lordofthemysteries.fandom.com/wiki/Episode_N (Adapted Chapters + resumos), (4) regras do parser em lotm-audiobook.py (speaker_of/cmd_parse) — reporte onde o parser errou e por quê.
Heurísticas validadas: pensamento 1ª pessoa=Klein; Klein=Zhou Mingrui; lore citada não condena; citação “...” lida=NARRADOR; SFX (Pá!/Toc!/etc)=SFX não fala. Cap12 tem DUNN(2) — Dunn=Gabriel Noya, capitão formal, briefings/comandos; valide cada Dunn contra a regra de ouro (lore não condena; condena 1ª pessoa alheia/ritual alheio/voz feminina).

Entregue por capítulo: caps/capNN-audit.md (tabela seg|atual|veredito|falante-final|evidência + seção Correções em formato --set i=FALANTE + Hipóteses + Exceções do parser) e caps/capNN-blocking.json (blocos físicos com segs, local, posição do Klein, SFX, clima — modelo cap01-blocking.json).
Quando terminar, responda com: capítulos auditados, total de segmentos, UNKNOWN resolvidos, correções propostas, hipóteses pendentes. Seja conciso e baseado em evidência.

---

## · ?

Auditoria forense cap10-12 — levantando mapas, método e modelo.

---

## · ?

Modelo e capítulos carregados — agora vou extrair as regras do parser e as âncoras.

---

## · ?

Evidência reunida (wiki ep1, anchors ep1, parser). Agora escrevo os 6 arquivos novos.

---

## · ?

Corrigindo o parâmetro da ferramenta e gravando os arquivos.

---

## · ?

Auditoria concluída. 6 arquivos novos em `caps/`; nenhum vivo tocado.

- **Capítulos auditados:** 10, 11, 12
- **Total de segmentos:** 270 (86 + 94 + 90)
- **UNKNOWN resolvidos:** 59/59 (19 + 21 + 19)
- **Correções propostas:** 87 `--set` (27 + 27 + 33)
- **Hipóteses pendentes:** 6 (2 por capítulo: atribuição líder×comum cap10; voz INSPETOR/MOUNTBATTEN; conferência seg51 cap11; voz MELISSA; voz do COCHEIRO cap12; seg63 "Uma oportunidade!")

Achados principais, por evidência:
- **Cap10:** 5 falas do Dunn (olhos-cinzentos: 22, 37, 41, 44–45, 69, 71, 75), 2 do Leonard (59, 80, 82 — a frase-título "a norma é..." é dele), 1 do Mountbatten (64). Parser errou seg2 (KLEIN→NARRADOR: "Sou eu" era citação do Mountbatten).
- **Cap11:** 12 falas da Melissa, resto Klein. Parser errou seg92 (KLEIN→MELISSA: "Deixe-me" é clítico dela — voz feminina condena; mesma classe de erro do seg2-cap10).
- **Cap12:** erro crítico duplo — segs 25 e 38 marcados KLEIN são **Dunn** ("Eu suponho", "eu havia conjecturado" = 1ª pessoa alheia, que condena); seg23 marcado DUNN é **Klein** (sujeito explícito). SFX: 6, 7, 58 → SFX ("Toc"); 72 "Clop!" → SFX mas "clop" falta no léxico. Causa-raiz dominante: nome-verbo em parágrafo narrativo sem travessão nunca é testado (8 segs só no cap12).
- **Âncoras:** só ep1 se aplica (caps 1–14; spans Dunn t1473/1770–1771, Klein, Leonard); ep10/11/12 são arco tardio (Azik/Sharon/Lanevus) — registrado nos audits.
- **Wiki ep1:** confirma Dunn arrasta p/ sonhos (lê-se o cap12-D como sonho de sondagem), Daly = "a especialista", cinza-névoa esconde memórias.

Pendente do dono: vozes p/ INSPETOR, MOUNTBATTEN, MELISSA, COCHEIRO; adicionar "clop" ao `SFX_WORDS` + "retrucar/exalou" ao `VERBS` (sugestões nos audits, parser intocado).

---

