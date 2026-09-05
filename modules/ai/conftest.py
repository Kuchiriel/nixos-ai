"""Root conftest — register markers so -m filtering works in Nix sandbox."""

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: tests that need external services (LLM, Qdrant, network, git, audio)",
    )
