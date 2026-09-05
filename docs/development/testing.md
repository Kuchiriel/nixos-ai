# Testing Guide — Guia de Testes do nixos-ai

> Este guia documenta a suíte de testes, convenções e como executar validações.
> **Status**: 859 passed, 0 failed, 26 skipped, 5 xpassed (2026-09-03)

## Regra Fundamental (BUFFY §2)

```
Teste unitário passando ≠ evidência de que o agente completa uma tarefa.
```

| Nível | O que valida |
|-------|-------------|
| Unit | Função isolada com mocks |
| Integration | Componentes reais comunicando |
| E2E | Fluxo completo executado |
| Behavioral | Trajetória do agente observada |
| Mission | Tarefa real completada e aceita |

## Executar Testes

```bash
# SEMPRE usar nix develop — NUNCA nix-shell (dependências faltantes)
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# Suite completa com verbose
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -v

# Teste específico por arquivo
nix develop --command python3 -m pytest modules/ai/jarvis/tests/test_agent.py -x -q

# Teste específico por nome
nix develop --command python3 -m pytest -k "test_rag" -x -q

# Com cobertura
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ --cov=jarvis --cov-report=term-missing
```

## Estrutura de Testes

```
modules/ai/jarvis/tests/
├── test_agent.py              # Agent core + tool calling
├── test_rag.py                # RAG híbrido (Qdrant)
├── test_memory.py             # remember/recall
├── test_devtools.py           # File operations + shell
├── test_mcp_server.py         # MCP tools
├── test_harness.py            # Nightwatch harness
├── test_checkpoint.py         # State persistence
├── test_safe_editor.py        # Atomic file editing
├── test_validator.py          # Syntax + AST validation
├── test_security.py           # Path traversal, injection
├── test_property_based.py     # Hypothesis (31 adversarial)
├── test_fuzzing.py            # Stress + mutation (56 tests)
└── ...
```

## Convenções

### Markers

```python
@pytest.mark.integration   # Requer serviços rodando (Qdrant, llama.cpp)
@pytest.mark.e2e           # Fluxo completo — mais lento
@pytest.mark.xfail         # Esperado falhar (ex: requer SLM externo)
@pytest.mark.skip          # Comportamento intencional de pular
```

### Mocks

- Mocks são **permitidos apenas para unit tests** (BUFFY §5 ANTI-MOCK)
- Para testes de integração, usar serviços reais quando tecnicamente possível
- `@pytest.mark.integration` sinaliza que requer serviços reais

### Validação antes de commit

```bash
# 1. Sintaxe Python
python3 -c "import ast; ast.parse(open('arquivo.py').read())"

# 2. Imports
python3 -c "import jarvis.core; import jarvis.control_plane; print('OK')"

# 3. Nix
nix flake check

# 4. Suite completa
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q
```

## Categorias de Teste por Componente

### RAG + Qdrant

```bash
# Requer Qdrant rodando na :6333
nix develop --command python3 -m pytest tests/test_rag.py -x -q -m integration
```

### Segurança (property-based)

```bash
# Hypothesis: 31 testes adversariais para parsers e regex
nix develop --command python3 -m pytest tests/test_property_based.py -v
```

### Harness (Nightwatch)

```bash
# Smoke test sem LLM (dry-run)
nix develop --command python3 -c "
from nightwatch.harness import run_nightwatch
run_nightwatch(dry_run=True, max_tasks=2, use_llm=False)
"
```

## Verificação de Integridade Completa

Sequência completa antes de qualquer PR ou rebuild:

```bash
# 1. Git status limpo
git status

# 2. Todos os testes
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# 3. Build Nix
git add -A && nix build .#jarvis --no-link

# 4. Flake check
nix flake check

# 5. Smoke test do JARVIS
nix develop --command python3 -c "from jarvis.core import agent; print('OK')"
```

## Testes Excluídos do Build Nix (checkPhase)

Alguns testes escrevem em `~/.local/state/` e falham no sandbox Nix:

```nix
# Em package.nix
checkPhase = ''
  pytest tests/ --ignore=tests/test_integration_qdrant.py -q
'';
```

Estes testes devem ser executados manualmente em ambiente real.

---
**Ver também:** [[getting-started]] | [[repl-guide]]
[[agent-harness]] | [[nightwatch-components]] | [[../../BUFFY]]
