# Python Rules for jarvis

## Project Structure
- `modules/ai/jarvis/src/jarvis/` - Main package
  - `core/` - Core modules (agent, rag, memory, devtools)
  - `providers/` - External integrations (llm, mcp, telegram)
  - `cli/` - Command-line interfaces (dev, devtools, launcher)
- `modules/ai/jarvis/tests/` - Test suite

## Python Code Conventions (AGENTS)

### Toolchain
```bash
# Package management
uv init my-project --package
uv add numpy pandas
uv add --dev pytest ruff pyright hypothesis
uv run python -m pytest

# Linting & formatting
[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "F", "W", "I", "N", "UP"]
ignore = ["E501"]

# Type checking
[tool.pyright]
typeCheckingMode = "strict"
```

### Idioms
- Use comprehensions (list, dict, set)
- Use context managers for resource cleanup
- Use generators for lazy evaluation
- Use f-strings for formatting
- Use dataclasses for structured data

### Anti-Patterns (NEVER USE)
- Bare except: `except:` → use `except SpecificError:`
- Mutable defaults: `def f(items=[])` → use `def f(items=None)`
- Global state: `global counter` → use classes
- Star imports: `from x import *` → use explicit imports

### Coding Style (AGENTS)
- Functions under 20 lines, parameters max 3
- Prefer composition over inheritance
- Use guard clauses to reduce nesting
- Always handle specific exceptions
- Always log error context
- Never silently swallow errors

### Commit Format
- `feat(scope): add feature`
- `fix(scope): resolve issue`
- `refactor(scope): improve code`
- `test(scope): add tests`
- Subject max 72 chars, imperative mood ("add" not "added")

## Testing
- Use pytest for all tests
- Run `python -m pytest -v` for verbose output
- Use hypothesis for property-based testing
- Mock external services in tests
- Follow Arrange-Act-Assert pattern
- Test behavior, not implementation

### Common Commands
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

## WEB SEARCH
Use tavily_search when you need to verify:
- Current version of a library (fastapi, pydantic, etc.)
- API docs that changed between versions
- Updated best practices for Python patterns
- CVEs in dependencies
- New Python features (3.13, 3.14)
Priority: HIGH — APIs change frequently
