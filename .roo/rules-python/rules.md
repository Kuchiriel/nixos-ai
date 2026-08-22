# Python Rules for jarvis

## Project Structure
- `modules/ai/jarvis/src/jarvis/` - Main package
  - `core/` - Core modules (agent, rag, memory, etc.)
  - `providers/` - External integrations (llm, mcp, telegram)
  - `cli/` - Command-line interfaces
- `modules/ai/jarvis/tests/` - Test suite

## Python Style
- Python 3.13+ with type hints
- Use dataclasses for structured data
- Prefer f-strings for formatting
- Run `ruff check` before commit

## Testing
- Use pytest for all tests
- Run `python -m pytest -v` for verbose output
- Use hypothesis for property-based testing
- Mock external services in tests

## Common Commands
```bash
# Run tests
cd modules/ai/jarvis && python -m pytest -v

# Run specific test
python -m pytest tests/test_llm.py -v

# Lint
ruff check src/jarvis/

# Type check
mypy src/jarvis/
```
