# LOOP v3 — caça a problemas e melhorias com respaldo de literatura

> Complementa o LOOP-v2 (harness/modelo). Este varre **todos os repos**,
> e para cada problema achado: pesquisa arXiv + padrão de mercado + SOTA
> antes de decidir. "Eu não decido essas coisas" — a literatura decide.
> Ler este arquivo = entrar no modo. Um ciclo por vez, método fechado.

## ⛔ Pré-condição de TODA sessão (leia antes de qualquer ciclo)

- **Modelo em treino?** Se sim (checar handoff/memória): NADA de bench,
  restart de serviço, troca de binário/flags/modelos, rebuild, briga de
  GPU/CPU. Trabalho permitido: docs, testes de unidade, refactor seguro,
  pesquisa, arquivamento, `manifest.json`, consolidate pós-revisão.
- **Nunca apague dado** → `core.safe_archive.archive_then_delete()`,
  destino `archive/<assunto>-AAAA-MM-DD/`, dry_run primeiro.
- Decisão SEMPRE ancorada em pesquisa (arXiv 2602.11988: contexto
  inflado piora; 2511.12884: tamanho ideal de contexto). Registra a
  citação no commit/registro.

## Rotação (1 repo por ciclo; comece pelo mais ativo)

1. `nixos-ai` (JARVIS) → 2. `karaok` → 3. `guia-renamer-pro` →
4. `docs/` do monorepo → 5. `applio-lab`/`OTServer_UPGRADE` (só leitura
   de estado, são de outra sessão) → volta pro 1.

## Método por ciclo (nesta ordem, sem pular)

1. **Caçar** (30 min máx, sem LLM): no repo do ciclo, procure:
   - entropia: scripts órfãos, doc drift (comando que não existe),
     `TODO/FIXME/XXX` antigos, código morto, duplicação
   - lacuna de teste: módulo central sem teste; teste que testa mock
   - armadilha conhecida: grep `.agents/memoria-do-projeto.md`
   - segurança: segredo em arquivo, `eval`, permissão larga
   - Ferramentas: `rg -n "TODO|FIXME"` · `git log --since="30 days ago"
     --stat` (o que mudou sem teste junto) · `wc -l` de docs (>400
     linhas = candidato a adelgaçar)
2. **Escolher 1 problema** — o de maior dano × menor risco de mexer.
   Registrar os demais como achados (uma linha cada) no
   `docs/auditoria/LOOP-v3-<data>.md` — não jogue fora a caça.
3. **Pesquisar** (o coração do loop; nunca pule):
   - web: "problema + best practice 2026" e "problema + SOTA"
   - arXiv: nome do sintoma (ex.: "flaky tests", "tech debt
     repayment", "doc rot") via `jarvis rag` coleção `books` (queries
     EM INGLÊS — embedding é English-centric)
   - padrão de mercado: como 2-3 projetos grandes resolvem
   - **Baixar a referência**: `~/Books/papers/arxiv-<id>.md` ou
     `web-<slug>.md` + linha no `~/Books/papers/INDEX.md` com o que ela
     estabelece. Indexar: `jarvis rag index ~/Books/papers` (com
     `JARVIS_EXTRA_READ_ROOTS` se vier do MCP).
4. **Decidir com a pesquisa na mão**: aplicar só se a evidência apontar
   claramente E o risco for reversível (git + teste). Em dúvida entre
   duas opções: registrar as duas com citações, aplicar a conservadora.
5. **Aplicar**: mudança pequena, teste junto, commit path-limited
   PT-BR com a citação no corpo ("conforme arXiv 2511.12884…").
   Rodar a suíte do repo ANTES do commit (`manifest.json` → test_cmd).
6. **Fechar o ciclo**: `remember` (categoria + citação), uma linha no
   arquivo de auditoria do dia, handoff se descobrir algo grande.

## Regras (inegociáveis)

- **1 problema por ciclo.** Caça larga, mudança estreita.
- Ciclo sem mudança aplicada ainda é válido se produziu registro +
  referência baixada. Commit vazio: nunca.
- Sem pesquisa = sem decisão. "Acho que" não entra em commit.
- Repo de outra sessão (applio-lab, OTServer): só registrar, não mexer.
- Se um teste quebrar por causa da sua mudança: a mudança está errada
  ou incompleta — nunca "consertar" o teste para passar.
- Fila bloqueada por treino (tier fast, cmoe 41v35): não puxe pra cá.

## Ciclo de evolução do HARNESS (tipo especial — quando o dono mandar)

Escada de atribuição (ordem do dono 25/09, base arXiv 2607.28802):
1. **bonsai** (fraco) primeiro. Falhou? Anotar (aresta, lado).
2. **qwen** (médio) na MESMA bateria SE stuck/ambíguo.
3. **moe** (forte) SÓ se a atribuição ainda estiver em dúvida — e só
   com RAM livre (19GB; OOM já matou chromium uma vez).
4. Verificar integridade do input ANTES de culpar o modelo: truncamento
   rtk-lite (TOOL_OUTPUT_MAX_CHARS=8000), compactação de contexto, tool
   que corta. "Disponível mas não seguido" ≠ "removido pelo harness".
5. Grader validado offline antes de medir (certa passa / errada rejeita).
6. Registrar em docs/benchmarks/MODEL-HARNESS-MATRIX.md com binário +
   first_pass separado de world_ok. Gates vivem em
   scripts/harness-challenges.json (tier "gate", campo "edge" obrigatório).

## Fila que este loop herda (25/09)

1. `consolidate.py`: escrever `apply()` (marca `superseded_by`, nunca
   deleta) + verificar que recall filtra superseded + teste + revisar
   as 43 dup/6 supersede por amostra ANTES do apply real.
2. Docs >400 linhas nos repos ativos (mesma receita do karaok).
3. `manifest.json` nos repos secundários (harness-research, OTServer).
4. Depois do treino liberar: medir tier fast (upstream), cmoe 41v35,
   **MoE na bateria de gates G1-G5** (confirmar G3 model-side).
5. Gates mais duros: G3-variantes (instrução no MEIO, multi-hop),
   ptbr-gate, e marcadores slow/integration nos e2e não-marcados.

## Frontmatter
Tags: #status/active #type/process #project/nixos-ai
