# BP — Como testar o Bonsai/PrismML via jarvis

## Contexto
- O llama-server PrismML/Bonsai já está rodando na máquina (porta 8080, modelo Bonsai).
- `curl -sf http://127.0.0.1:8080/health` retorna `{"status":"ok"}`.
- O módulo `PrismMLBackend` como arquivo Python NÃO existe no repo atual; o factory tenta importar e falha.
- Não rodar bonsai-bin novamente sem orientação; o serviço já responde.

## Como testar

### 1) Teste mínimo via curl
```bash
curl -sf http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"/nix/store/nc3rnnsmz17mnhbqfry1xiw3lk5sni0x-Ternary-Bonsai-8B-Q2_0_g64.gguf","messages":[{"role":"user","content":"responda apenas OK"}],"max_tokens":8,"temperature":0}'
```

### 2) Teste via jarvis CLI
```bash
JARVIS_LLM_BACKEND=prismml JARVIS_LLM_MODEL=default JARVIS_LLM_BASE_URL=http://127.0.0.1:8080/v1 jarvis chat "responda apenas OK"
```
Obs: isso pode falhar se não houver `PrismMLBackend` porque o factory tenta importar o adapter.

### 3) Teste de integração do harness
O harness usa `_default_call_llm` que instancia `LLMClient(Config())` e respeita `JARVIS_LLM_BACKEND`.
Se o backend não existir, a LLM retorna `ERROR: ...` e a tarefa falha "corretamente".
