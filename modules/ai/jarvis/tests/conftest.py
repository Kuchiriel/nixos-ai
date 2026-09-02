"""Pytest configuration and markers for Jarvis tests.

P8: Separates tests into categories:
- Unit tests: run in Nix sandbox (no external deps)
- Integration tests: need LLM server, Qdrant, network, etc.
- E2E tests: need full environment (LLM + git + filesystem)

Usage:
    pytest -m "not integration"  # sandbox-safe
    pytest -m "integration"      # needs external services
    pytest                       # everything
"""

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: tests that need external services (LLM, Qdrant, network)",
    )
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end tests that need full environment",
    )
    config.addinivalue_line(
        "markers",
        "requires_llm: tests that need a running LLM server",
    )
    config.addinivalue_line(
        "markers",
        "requires_qdrant: tests that need a running Qdrant instance",
    )
    config.addinivalue_line(
        "markers",
        "requires_network: tests that need network access",
    )
    config.addinivalue_line(
        "markers",
        "requires_audio: tests that need audio hardware",
    )
