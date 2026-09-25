"""Pytest configuration and markers for Jarvis tests.

P8: Separates tests into categories:
- Unit tests: run in Nix sandbox (no external deps)
- Integration tests: need LLM server, Qdrant, network, git, etc.
- E2E tests: need full environment (LLM + git + filesystem)

Usage:
    pytest -m "not integration"  # sandbox-safe
    pytest -m "integration"      # needs external services
    pytest                       # everything
"""

import os
import shutil
import pytest

# Hard ignore: files that need git/filesystem/network and cannot run in Nix sandbox.
# These have pytestmark = pytest.mark.integration but the marker filter
# sometimes fails in the sandbox, so we also exclude by filename.
_INTEGRATION_FILES = [
    "test_harness_e2e.py",
    "test_nightwatch_e2e_full.py",
    "test_nightwatch_project_isolation.py",
    "test_nightwatch_safety.py",
    "test_nightwatch_real_e2e.py",
    "test_longrun_e2e.py",
    "test_platform_e2e.py",
    "test_p3_fail_persistence.py",
    "test_p5_state_machine.py",
]

def pytest_collection_modifyitems(config, items):
    """Skip integration tests when git is unavailable (Nix sandbox)."""
    # Detect sandbox: no git binary or NIX_SANDBOX env var set
    sandbox = (
        os.environ.get("NIX_SANDBOX") is not None
        or shutil.which("git") is None
    )
    if sandbox:
        items[:] = [
            i for i in items
            if not any(f in str(i.fspath) for f in _INTEGRATION_FILES)
        ]

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: tests that need external services (LLM, Qdrant, network, git)",
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


@pytest.fixture(autouse=True)
def _sandbox_state_dir(tmp_path, monkeypatch) -> None:
    """Isola state_dir por teste: Agent nunca toca $HOME.

    Sandbox Nix (/homeless-shelter read-only) quebra qualquer teste que
    construa Agent/Config sem isso. Global aqui em vez de repetir por
    arquivo (test_agent.py mantém o seu local — redundância inofensiva).
    """
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))


@pytest.fixture(scope="session", autouse=True)
def _isolated_qdrant_collections() -> None:
    """Isola as coleções Qdrant da execução de teste (25/09).

    Descoberto: a suíte escrevia na coleção `memories` REAL — 6 eventos
    "E2E test fact" foram parar na memória viva do agente. Isolar só o
    `JARVIS_STATE_DIR` (arquivos) não cobre o Qdrant, que é servidor.

    Padrão de mercado (Testcontainers/DB-per-test): **unique resource
    names em vez de limpeza depois** — a quote é "isolation is
    established before application code runs rather than repaired after
    each test". Limpar depois é justamente o que corre mal com suíte
    paralela e com processo morto no meio do teste.

    Então: um prefixo único por execução, aplicado às coleções que a
    suíte escreve, e nenhuma tentativa de consertar a coleção real.
    """
    import uuid

    prefix = f"test_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    for var in (
        "JARVIS_QDRANT_COLLECTION_CODE",
        "JARVIS_QDRANT_COLLECTION_MEMORIES",
        "JARVIS_QDRANT_COLLECTION_BOOKS",
        "JARVIS_QDRANT_COLLECTION_VAULT",
    ):
        os.environ[var] = f"{prefix}_{var.removeprefix('JARVIS_QDRANT_COLLECTION_').lower()}"
    yield
    # teardown é opcional: coleções `test_*` são descartáveis por nome
    # (ou seja: o próximo `doctor`/limpeza as vê e o dono decide).
