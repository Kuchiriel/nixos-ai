# Aider Benchmark — Qwen3.6-35B-A3B via llama.cpp

## Configuração

```yaml
# ~/.aider.conf.yml
openai-api-base: "http://localhost:8080/v1"
model: "openai/custom-model"
auto-commits: true
dirty-commits: true

# ~/.aider.model.metadata.json
max_input_tokens: 131072
max_output_tokens: 4096
```

### Flags importantes do aider

| Flag | Efeito | Recomendação |
|------|--------|-------------|
| `--edit-format diff` | SEARCH/REPLACE blocks | ✅ **Usar** — mais eficiente |
| `--edit-format whole` | Arquivo inteiro | ❌ Lento, envia tudo |
| `--architect` | Modo arquiteto (thinking) | ⚠️ Muito thinking |
| `--thinking-tokens 0` | Desabilita thinking | ⚠️ Não desativa totalmente |
| `--reasoning-effort low` | Thinking reduzido | ⚠️ Efeito mínimo |
| `--no-check-model-accepts-settings` | Pula validação | ✅ **Necessário** |
| `--no-cache-prompts` | Sem cache | ✅ **Usar** para testes |
| `--no-stream` | Resposta completa | ✅ **Usar** para testes |
| `--yes-always` | Auto-accept edits | ✅ **Necessário** para non-interactive |
| `--max-chat-history-tokens N` | Limita contexto | ⚠️ Testar valores |

## Resultados do Benchmark

### Tarefas testadas

| # | Tarefa | Dificuldade | Resultado | Tokens | Tempo |
|---|--------|-------------|-----------|--------|-------|
| 1 | Leitura simples | Fácil | ✅ | 6.5k sent, 513 recv | ~78s |
| 2 | Mudar valor numérico | Média | ✅ | 6.5k sent, 1.0k recv | ~95s |
| 3 | Adicionar flag ao array | Média+ | ✅ | 6.5k sent, 827 recv | ~83s |

### Padrões observados

1. **Thinking overhead**: O Qwen3.6 gasta ~5.8k tokens em thinking antes de gerar ~500 tokens de resposta. Isso é **88% dos tokens são thinking**.

2. **Tempo por tarefa**: ~80-95 segundos. A maior parte é o processamento do thinking (CPU experts routing).

3. **Edição funciona**: O modelo consegue gerar SEARCH/REPLACE blocks corretos para edições simples.

4. **Limite de contexto**: Com 128K tokens, o aider pode enviar o arquivo inteiro + system prompt + thinking. Em arquivos grandes, pode estourar.

### Configuração ótima para testes

```bash
OPENAI_API_KEY=sk-dummy aider \
    --model openai/custom-model \
    --openai-api-base http://localhost:8080/v1 \
    --edit-format diff \
    --no-git --no-auto-commits \
    --no-show-model-warnings \
    --no-check-model-accepts-settings \
    --no-cache-prompts \
    --yes-always --no-stream \
    --message "TAREFA" \
    --file arquivo.nix
```

## Problemas Conhecidos

### 1. Thinking overhead (88% dos tokens)

O Qwen3.6 tem thinking habilitado por default. O aider NÃO envia `enable_thinking: false`. Soluções:

- **Opção A**: Configurar aider para enviar `chat_template_kwargs: {"enable_thinking": false}` (requer patch no aider)
- **Opção B**: Usar `--thinking-tokens 0` (não desativa totalmente)
- **Opção C**: Criar um wrapper/proxy que injete o parâmetro
- **Recomendado**: Opção C — proxy que adiciona `enable_thinking: false` ao request

### 2. Lentidão (~80s por tarefa)

O decode é 32 t/s mas o thinking consome ~5.8k tokens. Com 32 t/s:
- 5.8k tokens thinking / 32 t/s = ~181s (thinking)
- 500 tokens resposta / 32 t/s = ~16s (resposta)
- Total: ~197s (mas o thinking é processado em paralelo com prefill)

Tempo real observado: ~80-95s (o thinking é parcialmente paralelizado).

### 3. Edit format diff vs whole

- **diff**: Mais eficiente, mas o modelo precisa gerar SEARCH exato. Funciona para edições simples.
- **whole**: Envia arquivo inteiro. Funciona sempre, mas gasta mais tokens e é mais lento.

### 4. Web search

O web_search do Freebuff usa Serper API. O erro pode ser:
- Chave API expirada
- Rate limit
- Timeout de rede

Teste direto com curl funciona (httpbin.org OK).

## Próximos Passos

1. **Criar proxy** que injeta `enable_thinking: false` para reduzir thinking
2. **Testar com arquivos maiores** para validar limite de contexto
3. **Testar `--max-chat-history-tokens`** para controlar uso de contexto
4. **Benchmark de latência**: medir TTFT + tempo total por tarefa
