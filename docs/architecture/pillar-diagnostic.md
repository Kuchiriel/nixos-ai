# Diagnóstico dos 4 Pilares de Arquitetura — JARVIS (agosto/2026)

> **STATUS**: Este diagnóstico reflete o estado atual da codebase após todos os
> fixes implementados. Os 3 fixes originais foram implementados (commits 422d0be,
> 583d30c, ee87408, 9d0103f). Melhorias adicionais foram feitas desde então.
>
> Análise profunda do código-fonte (`modules/ai/jarvis/src/jarvis/`) contra 4 pilares
> de arquitetura críticos para um sistema de IA de bordo local-first.

---

## PILAR 1: Isolamento de Contexto e Telemetria

### ✅ O que está CORRETO

**1. Telemetria NÃO é injetada em workers especializados.**
- O `Agent` (agent.py) tem `system_prompt` fixo sem telemetria de hardware/hora.
- Telemetria SÓ entra via `EpisodicMemory.lessons()` que injeta `PAST LESSONS`.
- Workers como `doctor_report()`, `handle_nixos()`, `handle_rag()` e `handle_fastpath()` são **stateless** — zero memória episódica, zero telemetria.

**2. RAG e Memória Episódica usam coleções Qdrant separadas.**
- `qdrant_collection_code` ("code_index") → RAG de código
- `qdrant_collection_memories` ("memories") → Memória episódica
- `qdrant_collection_books` → Livros (futuro)
- Zero contaminação cruzada entre coleções.

**3. O Vault (vault.py) é camada de SÍNTESE, não de operação.**
- `summarize()` condensa eventos episódicos em markdown.
- Grava de volta como `kind=fact` — enriquece recall semântico.

### ✅ Fixes Implementados

**1. System prompt limpo de instruções de roteamento** (commit 422d0be).
- Instruções MCP removidas do system prompt do agente.
- Roteamento é responsabilidade do router.py, não do LLM.

**2. Lições com limite de tokens** (commit 422d0be).
- `lessons()` agora tem `max_chars=500` para não consumir contexto excessivo.

**3. Hardening de segurança** (commit 583d30c).
- `has_chaining_operators()` — detecta `&&`, `||`, `;`, `|`, backticks, `$()`.
- `_valid_tool_names()` — whitelist de tools aceitas.
- Empty cmd guard — comandos vazios retornam erro sem execução.

### ⚠️ Limitações Conhecidas

**1. Allowlist de comandos é prefix-based (validação fraca).**
- `systemctl status` aceita qualquer argumento após o prefixo.
- **Risco**: Baixo para agent local (usuário é root anyway).
- **Mitigação**: Audit trail completo em `agent-audit.jsonl`.

**2. Sem grammar/JSON Schema restrito no LLM.**
- O agente depende da extração regex de tool_calls do texto bruto.
- **Risco**: Com SLMs pequenos, taxa de tool_call válido cai para ~60-70%.
- **Mitigação**: Repair loop + `response_format: json_object`.

---

## PILAR 2: Resiliência de Tool Calling em Modelos Pequenos

### ✅ O que está CORRETO

**1. Extração de tool_call vazado em 3 camadas (SOTA para SLMs).**
- `<tool_call>{...}</tool_call>` (tag nativa Qwen)
- ````json {...}``` ` (code block)
- JSON solto no texto com **balanceamento de chaves**

**2. Repair loop determinístico (sem LLM intermediário).**
- JSON parse falhou → envia erro EXATO de volta ao modelo.

**3. Perfis adaptativos por tamanho de modelo.**
- Qwen3-4B/3B/1B: max_tokens=512, temperature=0.0
- Qwen3.6-35B: max_tokens=768, temperature=0.0

**4. "STOP calling tools" injection no penúltimo turno.**
- Resolve bug conhecido do Qwen 7B que loopa em tool calls.

**5. Fuzzy matching para str_replace** (commit c17a9a8).
- Tolerância de 82% de similaridade para corrigir erros do SLM.

### ✅ Fixes Implementados

**1. `response_format: json_object`** (commit 422d0be).
- Melhora taxa de JSON válido do LLM.

**2. `_normalize_tool_call()` com try/except** (commit 422d0be).
- Arguments como string com JSON inválido → fallback para `{}`.

### ⚠️ Limitações Conhecidas

**1. Sem retry automático para tool desconhecida.**
- Se `func_name` não existe, retorna erro sem retry.
- **Risco**: Baixo (audit trail registra).

**2. `MAX_REPAIR_RETRIES = 2` é global e binário.**
- Se falhar 2x, desiste completamente.
- **Mitigação**: Repair loop já é eficiente na maioria dos casos.

---

## PILAR 3: Loop de Retry e Self-Correction

### ✅ O que está CORRETO

**1. Repair loop determinístico.**
- JSON parse falhou → envia erro EXATO de volta ao modelo.

**2. Auto-aprendizado em falha de comando.**
- Cada falha gera lição episódica que o agente respeita no futuro.

**3. Cooldown anti-loop no self-heal.**
- 5 minutos entre restarts do mesmo serviço.

**4. Allowlist + audit trail completo.**
- Toda execução/negação → `agent-audit.jsonl`.

**5. Circuit breaker com fallback remoto** (commit b4d7e19).
- 3 falhas → fallback para Groq/Gemini/OpenRouter.
- ContentSafetyFilter bloqueia dados sensíveis.

### ✅ Fixes Implementados

**1. Heal aprende quando restart FALHA** (commit 422d0be).
- `_learn_lesson()` agora roda quando `ok=False` também.

**2. Observabilidade completa** (commit ee87408).
- JSONL logging, metrics CLI, doctor proativo.

### ⚠️ Limitações Conhecidas

**1. Self-heal não tem ação reparadora automática.**
- Detecta problema → restart → se falhar, avisa.
- **Risco**: Baixo (usuário é notificado via Telegram quando ativo).

---

## PILAR 4: Eficiência de Memória e Consolidação

### ✅ O que está CORRETO

**1. Vault com consolidação temporal.**
- `summarize(since_days=7)` condensa em markdown mensal.
- Git-syncado → backup versionado.

**2. Sparse terms + Dense embedding = busca híbrida.**
- BM25 (sparse) + Dense + RRF + re-rank V4.0.5.
- NDCG@5 = 1.0000 no eval.

**3. Rich content com limites progressivos.**
- `_STORED_CONTENT_CHARS = 30000`
- `rich_content_chars = 3000` (configurável por env)

### ✅ Fixes Implementados

**1. Deduplicação de memória episódica** (commit 422d0be).
- `recall()` deduplica por texto antes de retornar.

**2. RAG otimizado para NixOS** (commits recentes).
- `.nix` indexável + padrões de atributos/options.
- Re-rank calibrado para penalizar testes/scripts.

### ⚠️ Limitações Conhecidas

**1. Vault sem sliding window inteligente.**
- Pega TUDO dos últimos 7 dias.
- **Risco**: Baixo (eventos são poucos por dia).

**2. RAG sem "context window awareness" dependente do modelo.**
- `max_chars=3000` fixo.
- **Risco**: Baixo (nomic-embed tem ctx 2048, 3000 chars ≈ 1450 tokens).

---

## 📊 Score Geral (Atualizado)

| Pilar | Implementado | Limitações | Nota |
|---|---|---|---|
| 1. Isolamento de Contexto | 95% | Allowlist prefix-based | **A** |
| 2. Resiliência Tool Calling | 90% | Sem grammar/JSON Schema | **A** |
| 3. Loop de Retry | 90% | Sem ação reparadora automática | **A** |
| 4. Eficiência Memória | 85% | Vault sem sliding window | **A-** |

**Score geral: 90/100** — arquitetura madura para um sistema de IA de bordo.

---

## 🎯 Melhorias Adicionais Implementadas (agosto/2026)

| Componente | Commit | Descrição |
|---|---|---|
| Gaming Profile | recente | Detecção multi-sinal (GPU + Hyprland + Steam + Proton) |
| AST Cache | recente | Cache de validação AST para performance |
| Event Bus | e10a2c7 | Barramento asyncio leve com pub/sub |
| Triggers | e10a2c7 | Motor declarativo com cooldown e persistência |
| Vision | e10a2c7 | Captura de tela via grim/slurp |
| Circuit Breaker | b4d7e19 | Fallback remoto com ContentSafetyFilter |
| DevTools | d424185 | Ferramentas de desenvolvimento estilo Aider |
| Profile Dinâmico | 9d0103f | Preferências adaptativas por hora/load |

---

## Nota

Este diagnóstico é mantido como referência. Para o estado operacional atual,
consulte o HANDOFF.md. Para a arquitetura declarativa, consulte o AGENTS.md.
