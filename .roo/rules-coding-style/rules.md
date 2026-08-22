# Coding Style Rules

## Critical Rules (MUST follow)
- Always prioritize readability over cleverness
- Always fail fast and explicitly — never silently swallow errors
- Always keep functions under 20 lines
- Always validate inputs at function boundaries
- Never trust external data implicitly

## Formatting
- Consistent indentation throughout (never mix tabs and spaces)
- Meaningful variable names over short abbreviations
- Single letters only for loop counters

### Correct:
```python
maxRetryAttempts = 3
connectionTimeout = 5000
```

### Incorrect:
```python
m = 3
t = 5000
```

## Patterns and Anti-Patterns
- Never repeat yourself — extract duplicated logic into reusable functions
- Prefer composition over inheritance
- Use guard clauses to reduce nesting — never write arrow-shaped code

### Guard clause example:
```python
def process_user(user):
    if not user:
        return None
    if not user.is_active:
        return None
    return user.calculate_score()
```

## Error Handling
- Handle specific exceptions, never broad catch-all
- Log error context, not just the error message
- Never let errors vanish without trace

## Type Safety
- Use type annotations where supported
- Prefer explicit type checks for public APIs

## Function Design
- Write pure functions when possible
- Never mutate arguments unless required
- Limit parameters to 3 or fewer

## SOLID Principles
- Depend on abstractions, not concrete implementations
- Open for extension, closed for modification
- Many small interfaces over one large interface
