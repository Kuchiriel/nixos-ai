# Síntese: re-hidratação de contexto + coordenação multi-agente (2026-11-02)

> Pesquisa que fundamenta o redesenho da camada de coordenação do nixos-ai.
> PDFs + notas em `~/Books/papers/arxiv-<id>.{pdf,md}` (indexados no RAG `books`).
> **Contexto é recurso finito** (Anthropic, set/2025): o menor conjunto possível
> de tokens de alto sinal. Por isso: AGENTS.md = regra+ponteiro (sem estado);
> estado vive no tool `rehydrate` (1 chamada) e nas skills (corpo on-demand).

## 1. O problema observado (o que o dono_denunciou)

"Os agentes usam muito o RAG pra **registrar**, mas ficam tropeçando no mesmo
problema porque não usam o RAG pra **resgatar e reidratar**."

Diagnóstico no código do projeto:
- `memory.js` (plugin) só injeta memória em `experimental.session.compacting` —
  o comentário do próprio plugin diz: *"NOT implemented: session.created/idle
  auto-recall — this version has no verified context-injection API"*.
  **Falso no opencode v1.18.34**: existe `experimental.chat.system.transform`
  (`output.system: string[]`) e `experimental.chat.messages.transform` —
  ver `packages/plugin/src/index.ts` (tag v1.18.34).
- O resgate depende de o agente **lembrar** de chamar `recall`/`rag_search`
  (mandato no AGENTS.md) → depende de disciplina, não do harness.
  A literatura mediu exatamente esse tipo de falha (seção 3).

## 2. Achados que mudam o design (com números)

| # | Achado | Fonte | Números |
|---|--------|-------|---------|
| 1 | Memória de agente **nunca** deve ser sobrescrita por resumo: reversível vence irreversível | 2607.08032 | reversível 0.95 vs 0.33–0.56 de recall de fatos |
| 2 | Compactação **destrói regras**: 5 compactações derrubam a aderência a regras de segurança de 53% → 10% | 2608.22752 | 53%→10%; TypeCompact 2–4× pior; recall 96% |
| 3 | **Query-conditioning** é o divisor de compactadores bons/ruins; seleção determinística sem model call | 2609.40118 | ReCAP +19.8/+41.2 pts, −95% latência |
| 4 | Retrieval por **tipo/feature** vence similaridade textual (embedding 0.90–0.91 não discrimina) | 2609.28771 | TypeRetrieve 100% recall@50 vs 73%; +8 pts só trocando o espaço de retrieval |
| 5 | **Contexto longo faz mal mesmo com retrieval perfeita**: queda de 13.9%–85% | 2510.05381 | 13.9%–85% |
| 6 | **AGENTS.md gerado por LLM**: +20–23% de custo e **ganho zero**; *overviews* de repositório não ajudam | 2602.11988 (ETH) | p=87%/37% (sem efeito), +2.45/+3.92 passos, +20%/+23% custo |
| 7 | **AGENTS.md mínimo e escrito à mão** *reduz* custo: −28.64% runtime, −16.58% tokens de saída | 2601.20404 | 10 repos, 124 PRs |
| 8 | **Context Rot**: prompt focado (~300 tokens) > prompt completo, em 18 LLMs | Chroma, 2025 | gap persiste com thinking mode |
| 9 | **Lost in the Middle**: curva em U; evidência no meio → >20% de queda, pior que closed-book | 2307.03172 (TACL'24) | GPT-3.5 56.1% vs 88.3% oracle |
| 10 | **Skills**: o gargalo é *discovery/selection*, não o corpo. Progressive disclosure economiza 81.7%; eager-loading 100 skills **crasha 100%** dos rollouts; auto-seleção do modelo ativa a skill em >91% das tasks | 2609.35692, 2609.32274 | 81.7%, 100%, >91% |
| 11 | **Skill = memória procedural**: carregar só `name+description` (~100 tokens); SKILL.md <5000 tokens/<500 linhas | opencode docs/skills, Survey 202605.1276 | 100 tokens; <5k tokens |
| 12 | **Skills vulneráveis**: 26.1% de 31.132 skills amostradas vulneráveis, 5.2% provavelmente maliciosas | SkillSpector (NVIDIA) | 26.1% / 5.2% |
| 13 | **ACE**: contexto é playbook que evolui por **delta**, não por rewrite (+10.6% agente, −86.9% latência, sem labels) | 2510.04618 (ICLR'26) | +10.6%/+8.6%; −86.9%; 53.9s→9.5s |
| 14 | Anthropic: compaction preserva **decisões, bugs não resolvidos e arquivos recém-acessados**; *just-in-time* = ponteiro leve + carga em runtime | anthropic.com/engineering/effective-context-engineering-for-ai-agents | — |

## 3. Por que os agentes "tripam no mesmo problema"

Síntese mecanística (não é falta de registro — é falta de **gatilho** e de
**hierarquia de tipo**):
1. **Sem gatilho automático**: o resgate depende de o agente lembrar (achado 1 do
   plugin). → *rehydrate* como 1ª tool call + injeção mínima no system prompt.
2. **Compactação apaga o tipo certo de memória**: regras/ownership são
   resumidas como logs (achado 2: 53%→10%). → *Knowledge Triage*: guardas
   pinadas exatas no topo, HANDOFF atômico, episodic/log resumível.
3. **Retrieval por similaridade não discrimina**: dois "problemas iguais" com
   palavras diferentes não se encontram (achado 4). → filtrar por feature/estado
   (repo, lane, tipo de erro) além de texto.
4. **Contexto inflado degrada mesmo com retrieval perfeito** (achados 5–9).
   → injeção de ~6 linhas, não estado no system prompt.

## 4. Decisões (implementadas em 02/11)

- **R1 — tool `jarvis_rehydrate` (P0)**: uma chamada devolve
  (a) topo da fila (blackboard), (b) HANDOFF mais recente (atômico, *não
  resumido*), (c) top-k memórias + lições filtradas pelo pedido, (d) hits RAG
  (code/docs) com fonte, (e) roster/lanes vivos (quem é o dono do quê).
  Reversível: devolve o original, nunca um resumo do original.
- **R2 — Knowledge Triage no compaction (P0)**: no hook de compactação, as
  guardas de coordenação (claim, ownership, API de entrega) são pinadas
  **exatas**; o HANDOFF entra como chunk atômico; logs/episódico seguem
  resumíveis.
- **R3 — system prompt mínimo, sem estado (P1)**: só identidade + regra
  "rehydrate antes de agir" + regra de coordenação + ponteiro para a skill.
  AGENTS.md = manual e enxuto; repo overview vai para a skill (on-demand).
- **R4 — skill = memória procedural com budget de discovery (P1)**:
  `description` específica (≤1024 chars) é o que o modelo vê; corpo <5k
  tokens; scripts/references separados.
- **R5 — ativação por ganho medido, não por relevância (P1)**: paired run
  com/sem (skill, rehydrate) e gate estatístico antes de aceitar mudança.
- **R6 — fila/HANDOFF como deltas (P2)**: patch incremental a partir do
  feedback de execução (erro/retry → lição → skill), nunca rewrite monolítico.

## 5. Como medir se melhorou (protocolo, não achismo)

- **M1 (tool)**: `rehydrate` devolve o fato certo? Dataset de verdade =
  `docs/pains/PAINS.md` + incidentes reais (p.ex. "não subscrever mensagem sem
  Enter"); métrica = recall@k do bloco correto na 1ª chamada.
- **M2 (harness)**: paired run — mesma tarefa com/sem a injeção do system
  prompt; métrica = o agente chamou `rehydrate` antes de agir? (proxy:
  ordem das tool calls no `opencode.db`).
- **M3 (custo)**: tokens do system prompt injetado + tokens da chamada
  `rehydrate` vs. o custo de `recall`+`rag_search` manuais (3 chamadas).
- **M4 (regressão)**: a suite continua verde; a skill nova não pode custar
  mais do que some (ETH: +20% de custo sem ganho = não merger).

## 6. Resultado da medição (02/11, executado)

Paired run real (`scripts/measure-rehydrate-ab.py`, diretório SEM AGENTS.md
para o delta ser atribuível só à injeção; tokens = totais da sessão na
tabela `session` do `opencode.db`):

| modelo | A (com injeção) | B (sem injeção) | custo da regra |
|---|---|---|---|
| nemotron-3.5-lightning (kilocode/free) | cita `jarvis_rehydrate` + contrato correto (`--note`, `claim`) | não cita; inventa `jarvis_jarvis_recall` | **+1.172 tok** (+1,8%) |
| jarvis-mtp-lora 4B (default local) | **chama** a tool (1 call), 12 turnos | não chama, 3 turnos | +5.328 tok (+34%) |

**M2/M3 provados**: a injeção muda o comportamento nos dois modelos. No
modelo forte o custo é +1,2k tokens (abaixo do limiar do ETH: +20% de custo
sem ganho). No 4B o custo é maior em % (o prompt dele é 4x menor), mas
absoluto é pequeno (5,3k) e o comportamento correto.

**M1 (tool)**: recall@4 = 4/4 — 4 pedidos de erro recorrente real
(`SchemaError` do bash, `oldString` não encontrado, entrega sem travar o
typing, 400 de contexto do provider) trouxeram o bloco certo na 1ª chamada
(2,0–2,6s por resgate).

**M4 (regressão)**: suite 1836 passed / 1 falha preexistente
(`test_legacy_index::test_parity_with_synthetic_index`).

Falhas reais encontradas pela medição (e corrigidas):

1. **Template quebrado** — injetar a regra como 2º bloco criava um 2º
   *system message* e o template do modelo abortava (`System message must be
   at the beginning`). O system prompt é **1 bloco só** (medido: 20.073
   chars) → a regra é **mesclada** no último bloco (mescla > push).
2. **Loop de tool call** — o 4B chamava o resgate 20–24 vezes (293k tokens
   de input, 15 min de timeout). Correções: orçamento de resgates completos
   por janela (3) + memo do mesmo pedido (2ª chamada do mesmo pedido = ponteiro
   curto) + footer "uma chamada só" na regra.
3. **Imitação de formato (o mais sutil)** — as 8 primeiras linhas do HANDOFF
   são o template do opencode (`## Objective / ## Important Details / ## Next
   Move`) e o 4B o **imitava**: 91 turnos escrevendo no mesmo formato
   (176k tokens). O resgate devolve o HANDOFF como **8 linhas + path do
   original** (o original continua lá — R1: reversível) e o turno do 4B
   caiu de 91 → **12** (176k → 62k tokens cumulativos; 20,8k → tokens reais
   da sessão). **Retrieval que imita o formato de saída do modelo induz loop
   em modelo pequeno** — o conteúdo do RAG precisa ser distinto do formato
   que o agente usa para falar.
4. **Doubled exposed name** — opencode prefixes every MCP tool with the
   server key (`<server-key>_<tool>`), and our server key was `jarvis` while
   the tools were already named `jarvis_*` → `jarvis_jarvis_rehydrate`. Fixed
   by registering the tools with canonical names (the registry in
   `runtime/registry.py` already defined them): the exposed name is now
   `jarvis_rehydrate`, exactly as the docs and the injected rule claim.
5. **Guarda de root-delete inerte** — o regex do plugin não casava `rm -rf /`
   (exigia duas palavras antes do slash) e não pegava `-fr`/`-Rf`/`/*`.
   Corrigido e travado por teste (o plugin não tinha NENHUM teste).

## 7. Referências (arquivos locais)

`~/Books/papers/arxiv-2607.08032.{pdf,md}` · `2608.22752` · `2609.40118` ·
`2609.28771` · `2602.06052` · `2510.04618` · `2602.11988` · `2601.20404` ·
`2307.03172` · `2510.05381` · `2609.35692` · `2609.32274` · `2609.36043` ·
`2609.30123` (todos indexados na coleção `books` do RAG).
Web: anthropic.com/engineering/effective-context-engineering-for-ai-agents ·
opencode.ai/docs/skills · research.trychroma.com/context-rot ·
agent2agent.info (A2A v1.0) · anthropic.com/research (multi-agent).
