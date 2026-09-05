# ADR-002: Memory Layers — Camadas de Memória do JARVIS

## Status: Accepted

## Contexto

O ADR-001 (D7) declarou a existência de 4 camadas de memória sem detalhar
implementação, limites ou políticas de acesso. Este ADR formaliza essas decisões.

**Problema**: Um agente com janela de contexto de 32K tokens não pode manter
estado entre sessões sem um sistema de memória estruturado. Mixing de tipos de
memória (ex: usar episodic para facts semânticos) causa degradação de recuperação.

## Decisão

### D1: Separação Estrita por Tipo

```
┌─────────────────────────────────────────────────────────┐
│ Camada 1 — Working Memory                               │
│ Escopo: LLM context window (atual)                      │
│ Capacidade: ~26-28K tokens disponíveis                  │
│ Persistência: Nenhuma (perdida ao fim da sessão)        │
│ Acesso: Direto (está no prompt)                         │
│ Gerenciado por: context_budget.py                       │
└─────────────────────────────────────────────────────────┘
         │ ao fim de cada task
         ▼
┌─────────────────────────────────────────────────────────┐
│ Camada 2 — Episodic Memory                             │
│ Escopo: O que aconteceu (sequência de eventos)          │
│ Formato: JSONL append-only                              │
│ Localização: ~/.local/state/jarvis/                     │
│ Persistência: Por sessão → arquivo datado               │
│ Acesso: Via checkpoint.py (read/write)                  │
│ Gerenciado por: checkpoint.py, harness.py               │
│ Conteúdo: task, operação, erro, arquivos modificados    │
└─────────────────────────────────────────────────────────┘
         │ via `jarvis remember`
         ▼
┌─────────────────────────────────────────────────────────┐
│ Camada 3 — Semantic Memory                              │
│ Escopo: Fatos e conhecimento de longo prazo             │
│ Backend: Qdrant (port 6333)                             │
│ Persistência: Indefinida (até re-index)                 │
│ Acesso: hybrid search (dense + sparse BM25 + RRF)       │
│ Gerenciado por: memory.py, rag.py                       │
│ Conteúdo:                                               │
│   - jarvis remember/recall → fatos epistemológicos      │
│   - jarvis index → código do projeto (chunks)           │
│   - jarvis vault → documentação longa                   │
└─────────────────────────────────────────────────────────┘
         │ via AGENTS.md + manifest
         ▼
┌─────────────────────────────────────────────────────────┐
│ Camada 4 — Project Knowledge                            │
│ Escopo: Estrutura e regras do projeto                   │
│ Formato: Arquivos de texto (AGENTS.md, .roomodes, etc.) │
│ Localização: Repositório git                            │
│ Persistência: Via git (histórico completo)              │
│ Acesso: read_file direto (não via embedding)            │
│ Gerenciado por: workspace.py, agent.py                  │
│ Conteúdo: regras, convenções, mapa de módulos           │
└─────────────────────────────────────────────────────────┘
```

### D2: Políticas de Acesso por Camada

| Operação | Camada | Tool/API | Custo |
|----------|--------|----------|-------|
| Ler contexto atual | Working | (no prompt) | 0 tokens extras |
| Salvar estado de task | Episodic | `checkpoint.save()` | I/O local |
| Recuperar sessão anterior | Episodic | `checkpoint.restore()` | I/O local |
| Buscar fatos semânticos | Semantic | `jarvis recall <query>` | HTTP + embeddings |
| Buscar código | Semantic | `jarvis rag <query>` | HTTP + embeddings |
| Ler regras de projeto | Project | `read_file AGENTS.md` | I/O local |

### D3: Política Anti-Ritual

> "Do NOT run RAG/recall/lessons blindly on every prompt." — BUFFY §9

Critério para acessar cada camada:

| Camada | Acesse quando... | Não acesse quando... |
|--------|-----------------|---------------------|
| Episodic | Continuando task após crash/restart | Iniciando task nova com contexto claro |
| Semantic/RAG | Query tem ambiguidade sobre código/fatos | A resposta está no contexto atual |
| Semantic/recall | Tarefa depende de lição aprendida anterior | A instrução é explícita no prompt |
| Project | Convenção do projeto não está clara | AGENTS.md já foi lido nesta sessão |

### D4: Limites de Tamanho

| Camada | Limite recomendado | Ação quando excede |
|--------|-------------------|--------------------|
| Working | 22.938 tokens (70% de 32K) | Compactação via generate_recovery_summary() |
| Episodic (sessão) | 500 tokens por entry | Truncar com resumo |
| Semantic (recall) | 5 chunks top-k padrão | Reranker filtra para top-3 |
| Handoff doc | 200-500 tokens | Forçar estruturado — sem narrativa |

### D5: Hierarquia de Confiança

```
Project Knowledge  >  Semantic Memory  >  Episodic  >  Working
(regras explícitas)   (fatos históricos)  (eventos)   (outputs atuais)
```

Se `AGENTS.md` contradiz um fato em `recall`, AGENTS.md prevalece.
Se um fact em `recall` contradiz uma hipótese working, o fact prevalece.

## Consequências

**Positivas:**
- Agente mantém continuidade entre sessões sem perder contexto crítico
- Working memory nunca estoura (context_budget controla)
- Fatos acumulam com qualidade crescente (episodic → semantic)

**Negativas / Trade-offs:**
- Requer disciplina para não "smuggle" working state para episodic
- Qdrant é single point of failure para semantic + RAG
- Checkpoint.json pode acumular state stale (per-project namespacing mitiga)

## Implementação

| Módulo | Responsabilidade |
|--------|-----------------|
| `core/context_budget.py` | Working memory — budget e compactação |
| `nightwatch/checkpoint.py` | Episodic — save/restore por task |
| `core/memory.py` | Semantic — remember/recall |
| `core/rag.py` | Semantic — hybrid search de código |
| `core/workspace.py` | Project — discovery e manifest |

## Referências

- ADR-001 D7 — Decisão original de estratificar memória
- OpenDev Paper (arxiv 2603.05344) — Adaptive context compaction
- BUFFY §17 — Persona Handover via RAG relay

---
**Ver também:** [[ADR-001-agent-platform]] | [[context-engineering]]
[[agent-harness]] | [[rag-improvements]] | [[system-overview]]
