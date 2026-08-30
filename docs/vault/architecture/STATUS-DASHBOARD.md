# JARVIS System Status Dashboard

> Last updated: {{date}}

## 🟢 Active Services

| Service | Port | Status | Model |
|---------|------|--------|-------|
| LLM Server | 8080 | {{#if llama_status}}✅ Running{{else}}❌ Offline{{/if}} | Qwen3.6-35B MoE |
| Embeddings | 8081 | {{#if embed_status}}✅ Running{{else}}❌ Offline{{/if}} | nomic-embed-text-v2-moe |
| Reranker | 8082 | {{#if rerank_status}}✅ Running{{else}}❌ Offline{{/if}} | bge-reranker-v2-m3 |
| Qdrant | 6333 | {{#if qdrant_status}}✅ Running{{else}}❌ Offline{{/if}} | Vector DB |

## 🧠 Intelligence Metrics

| Metric | Value | Target |
|--------|-------|--------|
| Context Window | 32K tokens | 32K |
| RAG Index Size | {{rag_count}} documents | — |
| Memory Entries | {{memory_count}} facts | — |
| Vault Notes | {{vault_count}} notes | — |
| Tools Available | 22 tools | 22 |

## 🎯 MCU Parity Score

| Capability | Status | Score |
|------------|--------|-------|
| Voice Interface | ✅ Working | 8/10 |
| Context Understanding | ✅ Working | 7/10 |
| Memory & Persistence | ✅ Working | 6/10 |
| Tool Integration | ✅ Working | 8/10 |
| Safety & Validation | ✅ Working | 7/10 |
| Proactive Diagnostics | ⚠️ Partial | 3/10 |
| Adaptive Responses | ❌ Missing | 1/10 |
| Security Classification | ❌ Missing | 2/10 |
| **Overall Parity** | — | **5.3/10** |

## 📈 Recent Activity

```mermaid
graph LR
    A[Session Start] --> B[Tool Calls]
    B --> C[File Edits]
    C --> D[Tests Run]
    D --> E[Commits]
    E --> F[Session End]
    
    style A fill:#4ecdc4
    style F fill:#ff6b6b
```

## 🔧 Quick Commands

```bash
# Check system status
jarvis status

# Test voice pipeline
jarvis speak "System online"

# Run health check
jarvis doctor

# Check RAG
jarvis rag search "test query"

# Check memory
jarvis recall "recent events"
```

## 📊 Hardware Status

| Component | Usage | Status |
|-----------|-------|--------|
| GPU (RTX 4050) | {{gpu_usage}}% | {{#if gpu_ok}}✅{{else}}⚠️{{/if}} |
| RAM | {{ram_usage}}GB/32GB | {{#if ram_ok}}✅{{else}}⚠️{{/if}} |
| VRAM | {{vram_usage}}GB/6GB | {{#if vram_ok}}✅{{else}}⚠️{{/if}} |
| CPU | {{cpu_usage}}% | {{#if cpu_ok}}✅{{else}}⚠️{{/if}} |

## 🎮 Gaming Mode

| Setting | Value |
|---------|-------|
| Status | {{#if gaming}}🎮 Active{{else}}💻 Normal{{/if}} |
| Services Stopped | {{gaming_stopped}} |
| Performance Mode | {{#if gaming}}Maximum{{else}}Balanced{{/if}} |

## 📱 Interfaces

| Interface | Status | Access |
|-----------|--------|--------|
| Waybar | {{#if waybar}}✅ Visible{{else}}❌ Hidden{{/if}} | System tray |
| REPL | ✅ Available | `jarvis dev` |
| Telegram | {{#if telegram}}✅ Connected{{else}}❌ Disconnected{{/if}} | @jarvis_lab_bot |
| Rofi | ✅ Available | Super+Shift+J |
| Obsidian | ✅ Installed | ~/vaults/nixos-ai |

## 🔄 Nightwatch Status

| Metric | Value |
|--------|-------|
| Last Run | {{nightwatch_last}} |
| Tasks Completed | {{nightwatch_completed}} |
| Tasks Failed | {{nightwatch_failed}} |
| Next Run | 03:00 daily |
| Timer Status | {{#if nightwatch_timer}}✅ Active{{else}}❌ Inactive{{/if}} |
