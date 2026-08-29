# Gap Analysis Round 3 — 2026-08-29

## Componentes verificados nesta rodada

### ✅ Funcional e integrado
| Componente | Evidência |
|-----------|-----------|
| Vision (screenshot) | `vision.py` — grim → PIL → base64 → llama.cpp vision |
| MCP vision tools | `jarvis_capture_screen`, `jarvis_observe_screen` expostos |
| Idle mode | Integrado no CLI (`jarvis idle status/worker`) |
| HackMD | Integrado no MCP server (list/get/create/update/sync) |
| Legacy preservation | router (312L), rules (242L), triggers (322L), emotion (117L) |
| Recovery context | `generate_recovery_summary()` agora integrada no harness |
| Context budget | `should_compact()` agora chamada antes de LLM calls |
| Failure classification | `FailureType` enum + `classify_failure()` |
| Loop detector | `LoopDetector` com `record_attempt()` + anti-loop no harness |

### ❌ Gap: Infrastructure existe mas não integrada
| Componente | Linhas | Status |
|-----------|--------|--------|
| Event Bus | 264L | Definido, testado, mas **não importado em nenhum módulo de produção** |
| Audiobook | 476L | Implementado, **zero testes** |
| Multi-AI Reader | 225L | Implementado, **zero testes** |
| HackMD tests | 212L | Implementado, **zero testes** |

### ⚠️ Gap: Parcialmente integrado
| Componente | Status |
|-----------|--------|
| Voice (STT/TTS) | 12 testes, mas requer `jarvis-voice` flag |
| Nightwatch long-run | Timer configurado, mas não validado em execução real multi-hora |
| Multi-agent | TaskQueue existe, mas sem orquestração real |

## Ações recomendadas (prioridade)

### P1 — Integrar Event Bus
O Event Bus (pub/sub, retry, DLQ) está pronto mas não conectado.
Módulos que deveriam usar: voice, triggers, doctor, heal.
Esforço: Médio (importar e conectar, não reescrever).

### P2 — Testes para módulos sem cobertura
- `test_audiobook.py` — 476L sem teste
- `test_hackmd.py` — 212L sem teste
- `test_multi_ai_reader.py` — 225L sem teste

### P3 — Validar nightwatch long-run
O timer systemd está configurado, mas o harness nunca foi testado
rodando por >30 minutos com múltiplas tasks.

## Resumo das 3 rodadas

| Rodada | Foco | Gaps encontrados |
|--------|------|-----------------|
| 1 | README, MCP reader, test fixes | shell=True, test failures, m3ta aliases |
| 2 | Segurança, legacy, performance | recovery context não integrada, context budget não chamada |
| 3 | Orquestração, módulos não integrados | Event Bus não integrado, 3 módulos sem teste |
