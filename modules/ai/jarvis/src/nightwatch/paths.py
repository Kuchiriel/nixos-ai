"""Shared path utilities for the Nightwatch harness.

Compat shim: a implementação canônica vive em jarvis.core.paths
(consolidação 2026-09 — antes havia 3 resolvers divergentes).
A constante REPO_ROOT (snapshot no import, stale) foi REMOVIDA;
consumidores migraram para find_repo_root() avaliado no uso.
"""

from __future__ import annotations

from jarvis.core.paths import find_repo_root, set_project_root  # noqa: F401
