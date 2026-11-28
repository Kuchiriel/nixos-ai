# Auditoria scripts/archive e mortos — 2026-11-28 (herald-termux-vision)

## Medição
- `scripts/archive`: **29 arquivos** (inventário em `SCRIPTS-ARCHIVE-DEAD-AUDIT-2026-11-28.json`).
- Heurística fora de archive: **60 scripts** com `refs_non_docs==0` (amostra; precisa revisão antes de mover).

## Achados
- Archive já concentra legado/duplicatas (`*duplicate*`, `*legacy*`, bench legacy 2026-09-25).
- Candidatos fora de archive com zero refs não-doc são **heurísticos**: podem ser chamados por systemd, cron, comando humano, ou fora do repo. Não mover sem prova.

## Consolidação proposta (sem delete)
1. Manter `scripts/archive/` como canônico de legado; não desarquivar sem motivo.
2. Para cada candidato zero-ref: confirmar chamada externa (systemd/cron/README/fluxo humano), depois mover para `scripts/archive/<ano>/` com nota no README do archive.
3. Duplicatas nomeadas `*duplicate*` já no archive: manter, só limpar se houver prova de substituto canônico.
