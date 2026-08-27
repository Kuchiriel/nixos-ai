# Gap Analysis — JARVIS Agent Harness

**Data:** 2026-08-27
**Stack:** NixOS, Qwen3.6-35B-A3B (32K ctx), llama.cpp, Python, Roo Code

## O que já existe (FORTE)

| Componente | Status | Notas |
|------------|--------|-------|
| Agent loop | ✅ | Tool calling com repair, MAX_TURNS, audit |
| Tool execution | ✅ | execute_shell + devtools + MCP + vision |
| Allowlist + approval | ✅ | Read-only direto, write exige approval |
| Audit trail | ✅ | JSONL com timestamp, cmd, exit_code, output |
| Episodic memory | ✅ | Lições automáticas em falhas |
| Circuit breaker | ✅ | Fallback local→remoto |
| MCP client | ✅ | stdio transport, tool discovery |
| Duplicate detection | ✅ | Mesma tool+args 3x → warning |
| AST guard | ✅ | Valida Python antes de escrever |
| Adaptive profiles | ✅ | 4B/7B/32B+ com parâmetros diferentes |
| Vision | ✅ | capture_screen tool |
| Devtools | ✅ | read_file, write_file, str_replace, etc. |

## GAPS CRÍTICOS (alto ROI)

### 1. Loop Detection superficial
**Status:** Apenas detecção de duplicata exata (mesma tool + mesmos args)
**Gap:** Não detecta:
- Sequência A→B→A→B
- Edição→reversão→edição
- Teste falhando sem mudança
- Progresso zero por N iterações
**Impacto:** Agente pode rodar infinitamente em loops sutis
**ROI:** ALTO — previne waste de compute

### 2. Recovery = "tente novamente"
**Status:** retryAttempts existe mas não altera condição
**Gap:** Retry não muda:
- contexto
- estratégia
- ferramenta
- prompt
- diagnóstico
**Impacto:** Mesmo erro se repete MAX_REPAIR_RETRIES vezes
**ROI:** ALTO — previne stagnation

### 3. Sem context budget management
**Status:** TOOL_OUTPUT_MAX_CHARS=8000 (fixo)
**Gap:** Não conta tokens, não prioriza, não descarta
**Impacto:** Context overflow silencioso, respostas degradadas
**ROI:** ALTO — essencial pra 32K ctx limitado

### 4. Sem evaluation harness
**Status:** Testes unitários existem, mas sem E2E de agent
**Gap:** Não existe:
- Task templates congelados
- Trajectory recording
- Métricas por task
- Comparação A/B de configs
**ROI:** ALTO — sem isso não sabemos se melhorias funcionam

### 5. Sem integração com Roo Dev
**Status:** Roo Dev roda separado, sem acesso a JARVIS
**Gap:** Não existe:
- MCP server expondo JARVIS tools
- Custom mode que usa JARVIS
- Compartilhamento de memória/RAG
**ROI:** MÉDIO —拓宽 capacidades do Roo

### 6. Sem GUI interaction
**Status:** Vision existe (capture_screen) mas sem input
**Gap:** Não existe:
- Keyboard input via xdotool
- Mouse click/move
- Screenshot + action loop
**ROI:** MÉDIO — útil pra automação desktop

## GAPS MENORES (baixo ROI agora)

| Gap | Prioridade | Nota |
|-----|------------|------|
| Streaming responses | BAIXA | Modelo local, streaming é opcional |
| Multi-agent orchestration | BAIXA | Roo Dev já faz isso |
| Sandboxing | BAIXA | NixOS já provide isolamento |
| Cost tracking | BAIXA | Modelo local = custo zero |

## PLANO DE IMPLEMENTAÇÃO

### Prioridade 1: Loop Detector + Recovery (imediato)
- Adicionar `_detect_loop()` com 4 padrões
- Adicionar `_recover()` com 3 estratégias
- Integrar no `_run_loop()`

### Prioridade 2: Context Budget (imediato)
- Contar tokens por mensagem
- Truncar tool outputs por prioridade
- Inserir warning quando >80% do budget

### Prioridade 3: MCP Server (curto prazo)
- Expor execute_shell, read_file, etc. via MCP
- Integrar com Roo Dev

### Prioridade 4: Eval Harness (médio prazo)
- Task templates
- Trajectory recording
- Métricas

### Prioridade 5: GUI Interaction (médio prazo)
- xdotool wrapper
- Screenshot + click loop
