# LLM Backend Architecture

## Overview

The Jarvis inference layer uses an adapter pattern to support multiple LLM backends:

```
Jarvis Core (Agent Loop, RAG, Memory, Nightwatch)
    ↓
LLMClient (circuit breaker, retries, error classification)
    ↓
LLMBackend (abstract interface)
    ├── LlamaCppBackend (default)
    ├── PrismMLBackend (Bonsai ternary)
    └── (future backends)
```

## Configuration

Backend selection is via environment variable:

```bash
# Default (llama.cpp)
JARVIS_LLM_BACKEND=llama-cpp

# PrismML/Bonsai (ternary models)
JARVIS_LLM_BACKEND=prismml

# Bonsai (alias for prismml, same runtime)
JARVIS_LLM_BACKEND=bonsai
```

Other config options:

```bash
JARVIS_LLM_BASE_URL=http://127.0.0.1:8080/v1  # Main server
JARVIS_EMBED_BASE_URL=http://127.0.0.1:8081/v1  # Embeddings server
JARVIS_LLM_MODEL=default  # Model name
JARVIS_LLM_TIMEOUT=120  # Request timeout
```

## Backend Details

### llama-cpp (Default)

- **Binary**: `llama-server` from nixpkgs or custom builds
- **API**: OpenAI-compatible (`/v1/chat/completions`, `/v1/embeddings`)
- **Model format**: GGUF (Q4_K_M, Q8_0, etc.)
- **Features**: Tool calling, streaming, embeddings, reranking
- **Status**: IMPLEMENTED, TESTED, VERIFIED

### prismml (Bonsai Ternary)

- **Binary**: PrismML fork of llama.cpp (`prism-llama.cpp`)
- **API**: Same OpenAI-compatible API (fork maintains compatibility)
- **Model format**: Q2_0 GGUF (ternary, 1.58-bit)
- **Features**: Tool calling (if model supports), streaming, embeddings
- **Status**: IMPLEMENTED (adapter), TESTED (unit), NOT TESTED (integration - requires PrismML binary)

### bonsai

- **Runtime**: Same as prismml (PrismML fork)
- **Models**: Ternary-Bonsai-{1.7B,4B,8B,27B}-Q2_0.gguf
- **Status**: IMPLEMENTED (adapter alias for prismml)

## Adding a New Backend

1. Create `jarvis/providers/llm_<name>.py` implementing `LLMBackend`:

```python
from jarvis.providers.llm_backend import LLMBackend, ChatResponse, BackendInfo

class MyBackend(LLMBackend):
    def chat(self, messages, *, temperature=0.0, max_tokens=None,
             tools=None, tool_choice=None, stream=False, extra=None):
        # Implement chat completion
        return ChatResponse(content="...", backend="my-backend")
    
    def embed(self, text, model=None):
        # Implement embedding
        return [0.1, 0.2, ...]
    
    def health(self, timeout=3.0):
        # Implement health check
        return True
    
    def info(self):
        # Return backend info
        return BackendInfo(backend_type="my-backend", ...)
```

2. Register in `jarvis/providers/llm_factory.py`:

```python
elif backend == "my-backend":
    from .llm_my_backend import MyBackend
    return MyBackend(...)
```

3. Add tests in `tests/test_llm_backend.py`

## Testing

### Unit Tests (no server required)

```bash
python -m pytest tests/test_llm_backend.py -v
```

### Integration Tests (requires running server)

```bash
# Start your backend server first
JARVIS_LLM_BACKEND=prismml python -m pytest tests/test_integration.py -v
```

## Benchmarking

Use `benchmarks/experiment_tracker.py` for scientific comparisons:

```python
from jarvis.benchmarks.experiment_tracker import ExperimentTracker

tracker = ExperimentTracker()

# Start experiment
exp = tracker.start_experiment(
    name="llama-cpp-vs-prismml",
    description="Compare upstream with Bonsai ternary",
    config={"model": "Qwen3.6-35B-A3B vs Ternary-Bonsai-8B"},
)

# Record runs
tracker.record_run(exp.id, "llama-cpp", {
    "backend": "llama-cpp",
    "model": "Qwen3.6-35B-A3B-Q4_K_M",
    "peak_tg": 32.5,
    "sustained_tg": 28.1,
    "gpu_temp_c": 62,
    "n_ctx": 4096,
    "n_gpu_layers": 45,
})

tracker.record_run(exp.id, "prismml", {
    "backend": "prismml",
    "model": "Ternary-Bonsai-8B-Q2_0",
    "peak_tg": 45.2,
    "sustained_tg": 40.1,
    "gpu_temp_c": 55,
    "n_ctx": 4096,
})

# Compare
comparison = tracker.compare(exp.id)
print(comparison["delta"])  # improvement_pct, winner, etc.
```

## Hardware Requirements

### RTX 4050 Laptop (6GB VRAM)

| Backend | Model | VRAM | RAM | Notes |
|---------|-------|------|-----|-------|
| llama-cpp | Qwen3.6-35B-A3B Q4_K_M | ~5GB | ~6GB | MoE, experts on CPU |
| prismml | Ternary-Bonsai-8B Q2_0 | ~2GB | ~3GB | Ternary, fast on GPU |
| prismml | Ternary-Bonsai-27B Q2_0 | ~7GB | ~8GB | Needs CPU offload |

## Architecture Decisions

1. **OpenAI-compatible API**: All backends use the same API contract
2. **No mock backends in production**: If server is down, fail explicitly
3. **Quality validation**: Throughput alone doesn't determine winner
4. **Reproducible benchmarks**: Record all parameters for each run
5. **Fork tracking**: Record which fork/commit produced each result
