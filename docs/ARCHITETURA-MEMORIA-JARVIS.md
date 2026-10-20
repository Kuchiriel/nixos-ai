# ARQUITETURA DE MEMÓRIA JARVIS v22 (Baseada em SOTA 2024)

## Estado da Arte (Papers 2023-2024)

### 1. MemGPT (2310.08560) - Paradigma Fundador
- **Virtual Context Management**: Contexto = RAM, Storage = Disco
- **Memory Hierarchy**: Main Context (RAM) + External Storage (Vector DB + Recall Tools)
- **Memory Operations**: `core_memory_append`, `core_memory_replace`, `archival_memory_insert`, `archival_memory_search`, `conversation_search`
- **Key Insight**: Context window = RAM, External storage = Disk. O LLM gerencia o movimento entre eles.

### 2. Letta / MemGPT v2 (2024)
- **Memory Canonicalization**: Cross-model drift prevention
- **Memory Consolidation**: "Flattens temporal shape" - comprime fatos do usuário ao longo do tempo
- **memorywire**: Formato vendor-neutral (MemTensor, mem0, Letta, Zep, MemTensor, Zep/Graphiti)
- **Tiered Memory**: Core (system prompt) + Archival (vector DB) + Recall (conversation search)

### 3. AgentMemBench (2404.17545)
- Benchmark unificado para avaliar memória de longo prazo
- Métricas: Recall accuracy over long conversations, consistency, temporal reasoning
- Tasks: Multi-session recall, temporal ordering, fact updates, contradiction detection

### 4. LatComm (2403.19627)
- Context compression via latent representations
- Compress context into latent vectors for efficient reuse
- Relevant for: compressing old conversations into latent vectors

### 4. memorywire (vendor-neutral format)
- Formato wire padrão para operações de memória entre agentes
- Suporta: mem0, Letta, Zep, Cognee, MemTensor, etc.

---

## ARQUITETURA PROPOSTA PARA JARVIS v23

### Princípios de Design
1. **Tiered Memory** (3 camadas) - Seguindo MemGPT/Letta
2. **Memory Consolidation Job** - Background job periódico
3. **Vendor-Neutral Wire Format** (memorywire-inspired)
4. **Tool-First Philosophy** - Dados só via tools, nunca hardcoded
4. **Observabilidade** - Logs estruturados para debugging

### Arquitetura de 3 Camadas (Tiered Memory)

```
┌─────────────────────────────────────────────────────────────┐
│  HOT MEMORY (Context Window) - "RAM"                        │
│  • System prompt + Core persona + Current session           │
│  • Recent facts (últimas 6-10 interações)                   │
│  • Janela: ~8k tokens (max 8192 do modelo 4B)              │
│  TTL: Sessão ativa                                          │
└─────────────────────────────────────────────────────────────┘
                            ↕ append / retrieve
┌─────────────────────────────────────────────────────────────┐
│  WARM MEMORY (Vector DB) - "SSD"                           │
│  • Fat fragments recentes (últimas 50-100 interações)      │
│  • Preferências, fatos sobre o dono, rotinas               │
│  • Embeddings: BGE-M3 / E5-small (multilingual)            │
│  • Top-K retrieval (k=5) com score threshold               │
│  TTL: Semanas a meses                                      │
└─────────────────────────────────────────────────────────────┘
                            ↕ consolidate / promote
┌─────────────────────────────────────────────────────────────┐
│  COLD STORAGE (Files/DB) - "HDD/Arquivo"                   │
│  • Conversas completas (arquivadas por data)               │
│  • Documentos, PDFs, livros, anotações                     │
│  • Embeddings para RAG (document retrieval)                │
│  • Backups, versionamento (git/annex)                      │
│  TTL: Anos (backup git/annex)                              │
└─────────────────────────────────────────────────────────────┘
```

### Fluxo de Dados (Data Flow)

```
Usuário fala → ASR → Texto
    │
    ├─→ [Memory Gate] ──→ Hot Memory (Context) ──→ Classificador (LoRA) → Ação
    │       ↑
    │       └─ Warm Memory (Vector DB) ──→ Retrieval (Top-K + rerank)
    │                                          │
    │       └─ Cold Storage (Arquivos/DB) ←───┘
    │
    ↓
[Classificador LoRA] → RESPOND/WAIT/SILENCE/BARGE
    │
    ├─ RESPOND → Chat com Tools (streaming) → TTS → Fala
    │       │
    │       └─→ Memory Consolidation Job (async)
    │
    ├─ BARGE → Kill TTS + Resposta imediata
    ├─ WAIT → Hold (aguarda mais áudio)
    └─ SILENCE → Descarta
```

### Ferramentas de Memória (Memory Tools)

```python
# Core Memory (Hot) - sempre no context
core_memory_append(key, value)      # Adiciona/atualiza fato no core
core_memory_replace(key, value)     # Substitui fato
core_memory_read(key)               # Lê fato específico

# Warm Memory (Vector DB)
archival_memory_insert(text, metadata)    # Guarda fato/preferência
archival_memory_search(query, k=5)        # Busca semântica
conversation_search(query, k=5)           # Busca em histórico recente

# Cold Storage
document_ingest(file_path, metadata)      # Ingere PDF/doc
document_search(query, k=10)              # RAG em documentos
```

### Memory Consolidation Job (Background)

```python
# Roda a cada N interações ou tempo
def consolidate_memory():
    # 1. Sumarizar conversas antigas (>N turns) → fatos atômicos
    # 2. Deduplicar fatos contraditórios/reduntantes
    # 3. Promover fatos quentes → Warm Memory (vector DB)
    # 4. Arquivar conversas antigas → Cold Storage (arquivos markdown + embeddings)
    # 5. Atualizar embeddings se modelo mudou
    
    # Estratégia: LLM summarizer (modelo menor) + embedding
    # Agendamento: a cada N interações OU cron (diário 3h)
```

### Integração com Ferramentas Existentes

```python
# RAG Tools (existentes)
web_search(query)      # Web search via Tavily
recall(query)          # Busca em Warm Memory
remember(text)         # core_memory_append
recall(query)          # archival_memory_search
web_search(query)      # Web search
shell(cmd)             # Shell commands
```

### Observabilidade / Debugging

```python
# Logs estruturados para debugging
{
    "event": "memory_operation",
    "op": "archival_memory_insert|search|recall|consolidate",
    "query": "...",
    "results": [...],
    "latency_ms": 45,
    "tokens": 120
}

# Métricas chave
- Recall accuracy (ground truth vs retrieved)
- Latency p50/p99
- Token usage per operation
- Cache hit rate (warm memory)
```

---

## PRÓXIMOS PASSOS (Implementação)

### Fase 1: Fundação (Esta semana)
1. [ ] Configurar Vector DB local (Qdrant/Chroma) + embeddings BGE-M3
2. [ ] Implementar `archival_memory_insert/search` + `conversation_search`
3. [ ] Integrar `core_memory` tools no classificador/loop
4. [ ] Job de consolidação (cron diário 3h)

### Fase 2: Consolidação Inteligente (Próxima semana)
1. Sumarizador LLM para compressão de conversas antigas
2. Deduplicação de fatos (embedding similarity > 0.95)
3. Promoção quente → quente (score de acesso)
4. Arquivamento frio (markdown + embeddings)

### Fase 3: Recuperação Avançada
1. Reranking (cross-encoder)
2. Query expansion / HyDE
3. Multi-hop reasoning (multi-hop retrieval)

### Fase 4: Observabilidade + Benchmarks
1. Métricas AgentMemBench (recall, consistency, temporal)
2. Dashboard Grafana/Prometheus
3. Avaliação contínua (golden set de perguntas)

---

## DECISÕES DE DESIGN (Rationale)

| Decisão | Rationale |
|---------|-----------|
| Qdrant/Chroma local | Offline, open-source, ARM64 nativo, suporte a filtered search |
| BGE-M3 embeddings | Multilingue (PT/EN/JA/ZH), 1024-dim, SOTA retrieval |
| Markdown + Frontmatter no Cold Storage | Git-friendly, legível humano, versionável |
| Job de consolidação diário (3h) | Baixa carga, janela ociosa, consistência diária |
| Formato wire memorywire | Portabilidade futura (Letta, Mem0, Zep) |
| Job de consolidação noturno | Janela ociosa, não compete com inferência |

---

## Próximos Passos (Esta Semana)

1. [ ] **Setup Vector DB** (Qdrant local Docker) + BGE-M3 embeddings
2. [ ] **Memory Tools** - implementar 6 tools core (insert/search/recall)
3. [ ] **Integração no loop** - classificador usa warm memory
4. [ ] **Consolidation Job v1** - sumarização + dedup + archive
4. [ ] **Eval harness** - golden set de 50 QAs para regression
5. [ ] **Docs** - ADR no repo, runbook de operações

---

*Documento vivo - atualizado conforme implementação avança*
*Última atualização: 2026-10-20 14:30*