# Environment Variables — nixos-ai

> Referência completa de todas as env vars necessárias para o projeto.
> Atualizado: 2026-08-29

## Serviços NixOS (configurados em /etc/)

### llama-server (port 8080)
Configurado em `modules/services/llama-cpp.nix` via `models.nix`.
- Sem env vars necessárias (flags via command line)

### Embeddings (port 8081)
Configurado em `modules/services/embeddings.nix`.
- Sem env vars necessárias

### Rerank (port 8082)
Configurado em `modules/services/rerank.nix`.
- Sem env vars necessárias

### Qdrant (port 6333)
Configurado em `modules/services/qdrant.nix`.
- Sem env vars necessárias

## JARVIS (configurados via EnvironmentFile)

### LLM Provider
| Var | Default | Descrição |
|-----|---------|-----------|
| `JARVIS_LLM_BASE_URL` | `http://127.0.0.1:8080/v1` | URL do llama-server |
| `JARVIS_LLM_MODEL` | `default` | Nome do modelo |
| `JARVIS_LLM_TIMEOUT` | `120` | Timeout em segundos |
| `JARVIS_LLM_DISABLE_THINKING` | `1` | Desabilitar thinking |

### RAG / Embeddings
| Var | Default | Descrição |
|-----|---------|-----------|
| `JARVIS_QDRANT_URL` | `http://127.0.0.1:6333` | URL do Qdrant |
| `JARVIS_QDRANT_COLLECTION_CODE` | `code_index` | Coleção de código |
| `JARVIS_QDRANT_COLLECTION_MEMORIES` | `memories` | Coleção de memórias |
| `JARVIS_QDRANT_COLLECTION_BOOKS` | `books` | Coleção de livros |
| `JARVIS_RERANK_BASE_URL` | `http://127.0.0.1:8082` | URL do reranker |

### Telegram
| Var | Default | Descrição |
|-----|---------|-----------|
| `JARVIS_TELEGRAM_TOKEN` | `""` | Token do BotFather |
| `JARVIS_TELEGRAM_CHAT_ID` | `""` | Chat ID (ou lista vírgula) |

**Setup:**
1. Criar bot via @BotFather no Telegram
2. Copiar token
3. Mandar mensagem pro bot
4. Chamar `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Copiar `chat.id`
6. Criar `/etc/jarvis-telegram.env`:
   ```
   JARVIS_TELEGRAM_TOKEN=seu_token
   JARVIS_TELEGRAM_CHAT_ID=seu_chat_id
   ```
7. `sudo chmod 600 /etc/jarvis-telegram.env`
8. `sudo systemctl restart jarvis-telegram`

### Vision
| Var | Default | Descrição |
|-----|---------|-----------|
| `JARVIS_LLM_URL` | `http://127.0.0.1:8080` | URL do LLM para vision |

### Vault
| Var | Default | Descrição |
|-----|---------|-----------|
| `JARVIS_VAULT_DIR` | `~/.local/state/jarvis/vault` | Diretório do vault |

## Roo Dev (configurados em MCP settings)

### tavily-search
| Var | Local | Descrição |
|-----|-------|-----------|
| `TAVILY_API_KEY` | MCP settings | Chave API Tavily |

### jarvis
| Var | Local | Descrição |
|-----|-------|-----------|
| `JARVIS_PROJECT_ROOT` | MCP settings | Root do projeto |

## Verificação Rápida

```bash
# Verificar serviços
curl -sf http://127.0.0.1:8080/health  # llama-server
curl -sf http://127.0.0.1:8081/health  # embeddings
curl -sf http://127.0.0.1:8082/health  # rerank
curl -sf http://127.0.0.1:6333/collections  # qdrant

# Verificar env vars
env | grep JARVIS_
cat /etc/jarvis-telegram.env 2>/dev/null || echo "Telegram não configurado"

# Testar JARVIS
jarvis status
jarvis doctor
```
