# Mapear fallback cascade systems (@general subagent)

- **sessão:** `ses_ee95c16fbffekl6YcCyQN7AKit`
- **quando:** 2026-10-07 13:53 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 12 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

READ-ONLY (não edite nada). Em /home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/, mapeie TODOS os sistemas de cascata/fallback/escalonamento: model_registry (select_model, fallback entre tiers), providers/llm.py (LLMClient: retries, fallback de modelo, timeout), provider_registry, e qualquer circuit-breaker/degradação graceful. Para cada um devolva: arquivo:linha, o que dispara o fallback (condição), para onde cai, e se existe furo (ex: sem fallback, fallback infinito, sem log). Também cheque /home/nixos/projects/opencode.json: quais providers são locais vs API (groq? anthropic?) e se há fallback configurado entre eles. Terse, tabela por sistema.

---

## · ?

Mapeando as cascatas e fallbacks — só leitura, sem alterações.

---

## · ?

Primeira leva lida — agora vou rastrear os pontos de escalonamento restantes.

---

## · ?

Quase completo — buscando as últimas cadeias de fallback.

---

## · ?

## 1. `model_registry.py` — carga do registry

| arquivo:linha | dispara (condição) | cai para | furo |
|---|---|---|---|
| `core/model_registry.py:119-130` `load()` | `OSError/ValueError` ao ler `JARVIS_MODEL_REGISTRY` ou `/etc/jarvis/model-registry.json` | `_FALLBACK` embutido (27-83), `source="fallback"`, `warning` logado | ⚠️ conteúdo pode divergir do Nix; só estrutura é garantida (paridade só pega em teste) |
| `core/model_registry.py:136-139` `_validate()` | `version != 1` | `raise RegistryError` — sem fallback | OK (fail-closed), mas derruba `select_model` inteiro |
| `core/model_registry.py:162-164` | `default` fora de `models` | `raise RegistryError` — sem fallback | OK (fail-closed) |
| `core/model_registry.py:169-175` `get()` | `model_id` inexistente | `raise RegistryError` | OK, mas caller precisa tratar |
| `core/model_registry.py:180-185` `sampling_for()` | `RegistryError` | `{}` (vazio) | ⚠️ silencioso: caller usa default heurístico sem log |

## 2. `model_policy.py` — `select_model` + `select_tier` + `CASCADE_MAP`

| arquivo:linha | dispara | cai para | furo |
|---|---|---|---|
| `core/model_policy.py:341-345` | zero elegível p/ `capabilities` | `raise ModelRouteError` — **sem fallback** (por design) | OK intencional; furo se caller não captura → crash em vez de degradar |
| `core/model_policy.py:348-356` | tier pedido sem elegível | elegível mais barato (`_TIER_RANK` speed<fast<reasoning, 346), `reason={tier_fallback, tier_match:False}` | ✅ logado em `reason`; não é silencioso |
| `core/model_policy.py:208-216` `ModelPolicy.select_tier()` | `vram_required > available` | `medium` → `cheap` → cheapest | ⚠️ sem log; `strong` 20GB nunca cabe em 6GB → sempre downgrade silencioso; só usado por código legado |
| `core/model_policy.py:370-421` `CASCADE_MAP` + `424-426` `cascade_for()` | camada desconhecida | `[]` (lista vazia = sem tentativa) | ✅ caller (`agent.py:2580`) itera zero vezes → retorna `None` → STUCK; sem log |
| `core/model_policy.py:429-432` `cascade_key_present()` | env key vazia/ausente | `False` → entrada pulada | ✅ mas nunca loga qual key faltou |

## 3. `runtime/policy.py` — funil único

| arquivo:linha | dispara | cai para | furo |
|---|---|---|---|
| `runtime/policy.py:18-38` `select_model_for_task()` | sempre (choke point F6/ADR-005) | delega a `model_policy.select_model`, só adiciona `emit("model_selected")` | ⚠️ **zero fallback próprio**; `emit` com `try/except: pass` (36-37) engole erro de telemetria sem log |

## 4. `providers/llm.py` — `LLMClient` (breaker + classificação, **sem retry loop**)

| arquivo:linha | dispara | cai para | furo |
|---|---|---|---|
| `providers/llm.py:482,640,677,715` `before_call()` | circuito `OPEN` | `raise CircuitOpenError` imediato, sem rede | ✅ fail-fast; `is_busy()` (320-326) trata `open` como busy |
| `providers/llm.py:490,650,687,723` `record_success/failure()` | exceção qualquer no backend | incrementa breaker; classifica e re-raise | ⚠️ **1 tentativa só — nenhum retry nem troca de modelo aqui**; retry vive só na sessão HTTP do backend |
| `providers/llm.py:495-501,655-661` | `"context"+"exceed/size/overflow"` na msg | `LLMContextOverflowError` (nunca retentar) | ✅ correto; classificação por substring — frágil se servidor mudar texto |
| `providers/llm.py:497-500,657-660` | `"timeout"/"connection"` na msg | `LLMTimeoutError` / `LLMConnectionError` | ⚠️ mesma fragilidade substring; resto vira `LLMError` genérico (501,661) |
| `providers/llm.py:216-238` `__init__` | `llm_model in ("","default")` | resolve via `ModelRegistry.load().default`, `except: pass` | ⚠️ `except` mudo (237-238) — sem log se falhar |
| `providers/llm.py:340-353` `_resolve_model_id()` | `backend.info()` falha | retorna `cfg.llm_model` + `warning` | ✅ logado |
| `providers/llm.py:295-310` `is_available()` | exceção no `health()` | `False` + `debug` | ✅ com cache TTL 2s (214,297-300) |
| `providers/llm.py:249-263` | — | **dois breakers independentes**: `_breaker` (chat :8080) + `_embed_breaker` (:8081) | ✅ domínios de falha separados; limiar `llm_circuit_failure_threshold=4`, `recovery=15s` via `getattr` (sem campo no `Config` — sempre default) |
| `providers/llm.py:674-676,712-714` `chat_stream/achat_stream` | backend sem `chat_stream` | fallback não-streaming `yield self.chat(...)` único | ✅; `GeneratorExit` libera slot via `release()` (688-692) — sem isso liveness bug |
| Timeout | `llm_factory.py:57-58` → `connect 5s / read llm_timeout=120` (`config.py:42`) | `Timeout` → classificado acima | ⚠️ sem override por chamada; stream longo pode estourar 120s sem escalonamento |

### Breaker interno `providers/llm.py:89-161` (Nygard, thread-safe)

| linha | dispara | cai para | furo |
|---|---|---|---|
| `139-144` | `consecutive_failures >= 4` | `CLOSED→OPEN`, `warning` | ✅ |
| `104-108` | `OPEN + 15s` | `OPEN→HALF_OPEN` + `info` | ✅ |
| `118-121` | >1 call em `HALF_OPEN` | `CircuitOpenError` | ✅ |
| `131-138` | falha na sondagem | `HALF_OPEN→OPEN` + `warning` | ✅ |

## 5. `providers/llm_llama_cpp.py` — retry HTTP + reload

| arquivo:linha | dispara | cai para | furo |
|---|---|---|---|
| `llm_llama_cpp.py:38-60` `_build_session()` | `429/500/502/503/504`, connect/read | `Retry(total=3, backoff 0.5+jitter 0.3, GET+POST)` via urllib3 | ⚠️ `raise_on_status=False` + retry em POST não-idempotente pode duplicar inferência; `400/context-overflow` **não** retentado (correto) |
| `llm_llama_cpp.py:219-233` | `>=500` com `"failed to load"/"loading"` no corpo | sleep 2s → retry, sleep 5s → retry (só esse caso) | ✅ específico p/ unload/load do router `--models-max 1`; outro 500 sai direto sem retry extra |
| `llm_llama_cpp.py:188-196` | payload est. > `n_ctx` (`/props`) | auto-clamp `max_tokens = min(want, room)` | ✅ evita 500; sem log |
| `llm_llama_cpp.py:105-131` `_stable_model_name()` | `model="default"` | fixa no residente (`bonsai` se no path) p/ evitar churn unload/load | ⚠️ cache de classe `_STABLE_MODEL` nunca invalidado; `except: pass` (129-130) sem log |

## 6. `providers/llm_factory.py` + `llm_remote.py` + `llm_backend.py`

| arquivo:linha | dispara | cai para | furo |
|---|---|---|---|
| `llm_factory.py:49-104` `create_backend()` | `llm_backend` | `llama-cpp/prismml/bonsai(=prismml)/remote` — **escolha única, sem cascata** | ❌ tipo desconhecido → `ValueError` (107-111); `bonsai` e `prismml` são o mesmo construtor — fallback ilusório |
| `llm_factory.py:91-104` `remote` | sempre Groq default (`JARVIS_REMOTE_BASE_URL`, key `JARVIS_REMOTE_API_KEY`) | `RemoteBackend` | ⚠️ key vazia aceita (constrói sem `Authorization`, falha só no `POST`) |
| `llm_remote.py:94-100` `RemoteBackend.chat()` | HTTP erro | `raise_for_status()` — **zero retry, zero fallback interno** | ❌ caller (`agent.py:2602`) faz `except: continue` mudo p/ próxima entrada |
| `llm_remote.py:119-120` `embed()` | qualquer chamada | `raise NotImplementedError` | ✅ explícito |
| `llm_backend.py:76-82` docstring | — | promete "circuit breaker, retries" no `LLMClient` | ⚠️ doc desatualizada: `LLMClient` não tem retry loop nem troca de modelo |

## 7. `core/circuit_breaker.py` — breaker com fallback remoto + gate (distinto do de `llm.py`)

| arquivo:linha | dispara | cai para | furo |
|---|---|---|---|
| `circuit_breaker.py:294-295` `_try_local()` | `failure_count >= 3` (default, 182) | `CLOSED→OPEN` + `_transition` | ✅ |
| `circuit_breaker.py:297-299` | `local_fn` levanta **e** `fallback_fn` existe | `_try_fallback()` imediato (sem esperar threshold) | ⚠️ 1ª falha já vaza p/ nuvem se PUBLIC — threshold só governa estado, não o atalho |
| `circuit_breaker.py:244-250` `execute()` OPEN | circuito aberto | erro controlado se `fallback_fn is None` (`backend:"rejected"`) | ✅ fail-closed, mas string de erro, não exceção tipada |
| `circuit_breaker.py:253-263` + `308-333` `_try_fallback()` (choke point) | prompt não-`PUBLIC` (`ContentSafetyFilter`) | bloqueia egresso, `total_rejected+=1`, `backend:"rejected"` | ✅ duplo gate (execute + _try_fallback); log só em `_log` interno (377-387, cap 200, `recent_log` 20) — sem `logger` |
| `circuit_breaker.py:346-354` | fallback remoto também falha | `backend:"fallback_error"`, string | ❌ **terminal: sem 2º nível, sem re-raise tipado** — caller que espera exceção recebe dict |
| `circuit_breaker.py:236-241` | `HALF_OPEN`, local OK | `→CLOSED` | ✅; `force_local/force_remote/force_open` (394-408) permitem operador forçar |
| `circuit_breaker.py:233` | `force_local=True` | tenta local mesmo com circuito OPEN | ✅ bypass explícito |

## 8. `core/agent.py` — cascata STUCK→API (último recurso)

| arquivo:linha | dispara (só 3 caminhos STUCK) | cai para | furo |
|---|---|---|---|
| `agent.py:2559-2604` `_try_api_cascade()` | loop abortado / warnings 2x / mesmo erro 3x (doc 2563-2564) | `cascade_for(_api_layer_for(prompt))`, 1ª entrada com env key presente vence; `RemoteBackend.chat(sys+prompt fresco, temp 0, 1024 tok)` | ❌ `except: continue` (2602-2603) e `except: return None` (2577-2578) **mudos**; sem key → `None` silencioso; **1x por run** (`_api_fallback_used`, 2572) — 2º STUCK no mesmo run nunca tenta |
| `agent.py:915-925` `_api_layer_for()` | keywords no prompt | `classify/docs/batch`, default `dev` | ⚠️ heurística substring; `coding-long/rag/vision/mechanical` do `CASCADE_MAP` inalcançáveis por aqui (só via harness) |
| `agent.py:2606-2625` `_stuck_or_cascade()` | `fb` truthy | `final_response=fb`, `api_fallback=True`, `_finalize` sem STUCK | ✅ telemetria `api_fallback` + evento (2596-2598, `session.py:38-60` propaga) |
| `agent.py:2627-2667` `_ensure_routed_model()` | todo `run` | `select_model_for_task` → `base_url_for` (binário certo) → `ensure_model` | ✅ **fail-closed explícito** (2632-2633, `model_lifecycle.py:35-47`): routing/ensure propaga, nunca cai p/ modelo incapaz; furo: `ensure` pode levar 300s sem liberar peer (mitigado por `_evict_peers`, `model_lifecycle.py:96-109`) |

## 9. `core/provider_registry.py` — morto

| arquivo:linha | estado |
|---|---|
| `provider_registry.py:197-250` `route()`, `253-258` `route_for_persona()` | **DEPRECATED F6/ADR-005 (208-213, 256-257): 0 callers produtivos** — especifica `local→free→agregadores`, gate `DataClass` (`_class_allows`, 190-194), `local_only`/`SECRET→["local"]` (218-219). Só `CANONICAL_CONTEXT=32768` (40) é vivo (consumido por `llm.py:772-773`). Furo: `REGISTRY` (162-167) lista cerebras/groq/gemini/nvidia/openrouter sem keys/health — se religado, chama sem credencial. |

## 10. Degradação graceful (fora do caminho LLM principal)

| sistema | arquivo:linha | cai para | furo |
|---|---|---|---|
| Vision | `core/vision.py:947-1038` `observe_with_fallback()` | `local→gemini→nvidia→openrouter→OCR`, budget total 45s, cap 20s/nível, `_mark_dead` evita repetição | ✅ melhor cascata do repo; Groq removido (979-981, VLM descontinuado 01/10); sem display → `SEM DISPLAY` honesto (971) |
| Reranker | `providers/reranker.py:12-13,39-43` | `RerankerError` → RAG segue **sem rerank** | ⚠️ "fallback silencioso" assumido — depende do caller tratar; `is_available()` (36-37) existe mas nada obriga checar |
| Embeddings | `providers/llm.py:741-758` + `providers/embedding.py` (chunk+mean-pool) | breaker separado (não veta chat); chunk respeita ctx 512 | ✅ comentário (744-749) documenta bug anterior de truncamento silencioso |
| Saúde | `core/health_monitor.py:27-31,54-71` `HEALTHY/DEGRADED/DOWN`, TTL 10s, latência >5s = degraded | só observa; `doctor.py:375-396` agrega `ok/degraded/down` sem derrubar overall por componente não-essencial (185) | ⚠️ `DEGRADED` não dispara ação automática em nenhum caller — é telemetria |

## 11. `opencode.json` — locais vs API

| questão | achado |
|---|---|
| Locais | **10/10 providers são locais** (`opencode.json:12-158`): `local` (sem `baseURL` — default) + 9× `openai-compatible` em `127.0.0.1:8083-8093` (`local-fast`, `uncensored-4b`, `uncensored`, `deepseek-7b`, `phi-mini`, `gemma-4b`, `xlam-8b`, `qwen30b-moe`, `uncensored-q4kp`). `small_model: local/bonsai` (l.5) |
| API (groq? anthropic?) | **Zero**: nenhum `groq`, `anthropic`, `openrouter`, `openai` nem env key no arquivo |
| Fallback entre eles | **Não configurado**: nenhuma chave `fallback`/`fallback_models` ou roteamento; cada provider é ilha com 1 modelo; queda de uma porta = erro, sem escalonamento opencode-side (o fallback real vive no JARVIS: `CASCADE_MAP` + `_try_api_cascade`, fora deste arquivo) |

---

