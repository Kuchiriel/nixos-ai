# Testing Rules

## Arrange-Act-Assert Pattern
Structure every test in three distinct phases:
```python
# Arrange: Set up the test data and conditions
user = User(name="Alice", role="admin")

# Act: Execute the behavior under test
result = grant_permission(user, "read_documents")

# Assert: Verify the expected outcome
assert result.granted is True
```

## Behavior vs Implementation Testing
- Test behavior, not implementation details
- Focus on inputs and outputs
- Test public contracts
- Refactor internals freely without breaking tests

## Mocking Philosophy
- Mock external dependencies, not internal code
- Mock when: dependency is slow, unreliable, or expensive
- Don't mock when: testing the dependency itself

## Coverage Expectations
- Critical business logic: 90%+
- Edge cases and error paths: 80%+
- Public APIs and contracts: 100%
- Don't obsess over: trivial getters/setters, generated code

## Test-Driven Development (TDD)
Follow red-green-refactor cycle:
1. **Red**: Write failing test for new behavior
2. **Green**: Write minimum code to pass
3. **Refactor**: Improve code while tests stay green

### Rules:
- NEVER write production code without a failing test first
- NEVER skip the refactor step
- Only commit green tests
- One refactoring at a time
- Baby steps — extract one method at a time

## Test Organization
- Group tests by feature or behavior
- Name tests to describe the scenario
- Each test should stand alone
- Avoid shared state between tests

## Test Data
- Use realistic values that reflect production scenarios
- Avoid magic strings and numbers
- Use named constants for expected values
