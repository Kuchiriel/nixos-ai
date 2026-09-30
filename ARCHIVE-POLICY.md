# Política de arquivo — ÚNICA (29/09)

> Antes existiam 4 regras concorrentes (`scripts/archive/README.md`,
> `docs/archive/README.md`, `archive/README.md`, e uma implícita em
> `.gitignore`) com destination folders diferentes. Esta é a versão
> única. As outras ainda existem para reader local, mas a **fonte de
> verdade é esta**.

## A regra (não mudou — só parou de estar espalhada)

1. **NUNCA apagar.** Antes de mover: *verificar* o que é. Não
   versionado não é lixo (pode ser esquecimento real); "duplicata"
   raramente é duplicata (pode ser status de outro fork).
2. Destino é sempre um `archive/` correspondente, com data:
   `archive/<assunto>-AAAA-MM-DD/`.
3. Antes: `rg "<nome>"` confirmar 0 referência **fora da família**.
   *Esse passo salvou um erro hoje* — 1.400 linhas de "motores
   órfãos" tinham 3 wrappers invocando-os dentro do próprio archive.
4. **O conteúdo arquivado é versionado** (é o registro durável do
   veredito). Só evidência pesada (`.log`, `raw/`) e runs locais
   ficam fora do git — ver `.gitignore`.
5. **O veredito vai no commit** — arquivar sem registrar é entropia
   de novo. O README do `archive/<assunto>/` explica o *porquê*.
6. O `AGENTS.md`/`archive` guard: "não apagar" segue valendo
   (dados do usuário, coleções RAG, configs Nix).

## Onde fica o quê

| Tipo | Destino | Git? |
|---|---|---|
| script/benchmark superado | `scripts/archive/<assunto>-AAAA-MM-DD/` | sim |
| doc histórico, evidência | `docs/archive/{benchmarks,diagnostics,forensics,research,legacy-components}/` | sim |
| `_trash` (não indexar RAG) | `docs/archive/_trash/` | sim, com guarda de RAG |
| motor de runtime antigo | `archive/` (raiz, com `CONSOLIDATION-`) | sim |
| **evidência pesada / runs** | dentro do archive, em `*.log`/`raw/` | **não** (gitignored) |
| `.ragignore` | (não existe) — RAG exclui via padrão + `docs/archive/_trash` | — |

## Índice dos arquivos ativos

- `scripts/archive/tuning-engines-2026-09-29/` — família GA/grid/binary-search
  de tuning de flags; superada por `models.nix` (fonte única) +
  `scripts/bench-llm.sh` + sweeps dirigidos. *Não é lixo: a
  matemática é válida, a aplicação a flags declarativas é que saiu
  de moda.*
- `scripts/archive/bench-legacy-2026-09-25/` — 7 scripts bench
  pré-`bench-llm.sh`. Canônico: `scripts/bench-llm.sh`.
- `archive/` (raiz) — `core/` do antigo motor de agentes +
  `CONSOLIDATION-2026-09-03.md`. Substituído pelo kernel
  `modules/ai/jarvis/src/jarvis/`.

## Regra de "o que sai" (29/09)

Sai da raiz o que é **supersedido por desenho**, não o que está
velho. Exemplo que motivou: 4 motores de tuning genetic de flags
saíram porque `models.nix` é a fonte única das flags — erro de flag
é pego pelo registry validator na build, não por 3 gerações de GA.
Idade não é critério; obsolescência de premissa é.
