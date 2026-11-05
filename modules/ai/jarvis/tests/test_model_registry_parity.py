"""Paridade entre o registry do Nix (SSOT) e o fallback Python (04/11).

`modules/ai/models.nix` e o SSOT (SOURCES-OF-TRUTH.md). Ele gera
`/etc/jarvis/model-registry.json`. O Python (`core/model_registry.py`) tem um
`_FALLBACK` embutido para dev/test fora do NixOS — e ele COPIAVA os dados
(endpoints, portas, units, directServers). A copia divergia em silencio: o
docstring do modulo diz "NADA de dict Python espelhando metadata", mas
existia. Como o `heal` decide qual unit reiniciar a partir do registry, uma
divergencia = o heal reinicia a unit errada.

Este teste roda SO quando o JSON do host existe (fora do NixOS ele nao
existe → skip). Onde existe, a divergencia FALHA o build.

Comparacao: estrutura (chaves e tipos) + os campos que mudam operacao
(default, endpoints, servicePorts, directServers, units, bootModel).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from jarvis.core import model_registry as mr


def _host_json() -> dict | None:
    path = Path(os.environ.get(mr.REGISTRY_ENV, mr.REGISTRY_DEFAULT_PATH))
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


@pytest.fixture(scope="module")
def host():
    data = _host_json()
    if data is None:
        pytest.skip(f"{mr.REGISTRY_DEFAULT_PATH} ausente (fora do NixOS)")
    return data


def test_same_top_level_keys(host):
    assert set(host) == set(mr._FALLBACK), (
        "chaves do registry do Nix e do fallback Python divergiram: "
        f"so no Nix={sorted(set(host) - set(mr._FALLBACK))} "
        f"so no Python={sorted(set(mr._FALLBACK) - set(host))}")


def test_default_matches(host):
    assert host.get("default") == mr._FALLBACK["default"], (
        f"default divergiu: Nix={host.get('default')} "
        f"Python={mr._FALLBACK['default']}")


def test_endpoints_match(host):
    assert host.get("endpoints") == mr._FALLBACK["endpoints"], (
        f"endpoints divergiram: Nix={host.get('endpoints')} "
        f"Python={mr._FALLBACK['endpoints']}")


def test_service_ports_match(host):
    assert host.get("servicePorts") == mr._FALLBACK["servicePorts"], (
        f"servicePorts divergiram: Nix={host.get('servicePorts')} "
        f"Python={mr._FALLBACK['servicePorts']}")


def test_direct_servers_match(host):
    got = host.get("directServers") or {}
    want = mr._FALLBACK["directServers"]
    assert got == want, (
        "directServers divergiram (o heal usa isso p/ reiniciar a unit): "
        f"Nix={got} Python={want}")


def test_units_match(host):
    """O mapa 'units' do Nix e por ID DE MODELO: a unit declarada tem de
    bater com a unit do directServers (o heal reinicia a unit errada se
    divergir)."""
    units = host.get("units") or {}
    direct = host.get("directServers") or {}
    for name, entry in direct.items():
        unit = entry.get("unit")
        if not unit:
            continue
        declared = (units.get(name) or {}).get("unit")
        assert declared == unit, (
            f"directServers[{name}].unit={unit} != units[{name}].unit={declared}")


def test_no_duplicate_ports_in_direct_servers(host):
    """Duas entradas na MESMA porta = conflito (o dono escolhe uma e falha)."""
    by_port: dict[int, list[str]] = {}
    for name, entry in (host.get("directServers") or {}).items():
        port = entry.get("endpoint")
        if port:
            by_port.setdefault(int(port), []).append(name)
    dupes = {p: names for p, names in by_port.items() if len(names) > 1}
    assert not dupes, (
        f"porta compartilhada por 2 servidores (conflito de unit): {dupes}")
