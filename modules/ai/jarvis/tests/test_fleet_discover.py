"""Tests for dynamic fleet discovery (no live network, no hardcoded peers)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = next((p / "scripts/fleet-discover.py"
               for p in Path(__file__).resolve().parents
               if (p / "scripts/fleet-discover.py").is_file()), None)
if SCRIPT is None:
    pytest.skip("fleet-discover.py not available in this sandbox", allow_module_level=True)
spec = importlib.util.spec_from_file_location("fleet_discover", SCRIPT)
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)

FIXTURE = """
**msg** de `WindowsAgent` na lane `windows/peer`
```coord-json
{"kind":"status","agent":"WindowsAgent","lane":"windows/peer",
 "host":{"kind":"windows","os":"win32","arch":"x64","hostname":"WORKSTATION-ABC123"}}
```
"""


def test_bus_host_metadata_is_parsed_without_hardcoded_names(monkeypatch):
    monkeypatch.setattr(fd, "bus_feed", lambda: [FIXTURE])
    monkeypatch.setattr(fd.socket, "gethostbyname", lambda h: "100.0.0.9")
    hints = fd.bus_api_hints()
    assert len(hints) == 1
    assert hints[0]["hostname"] == "WORKSTATION-ABC123"
    assert hints[0]["kind"] == "windows"
    assert hints[0]["os"] == "win32"


def test_bus_agents_are_attributed_to_the_discovered_host(monkeypatch):
    monkeypatch.setattr(fd, "bus_feed", lambda: [FIXTURE])
    agents = fd.bus_agents()
    assert agents == [{"name": "WindowsAgent", "host": "WORKSTATION-ABC123",
                       "lane": "windows/peer", "kind": "windows", "os": "win32",
                       "arch": "x64", "source": "bus-coord-json"}]


def test_manifest_is_generated_from_measurement(monkeypatch, tmp_path):
    data = {
        "generated_at": "2026-11-20T00:00:00Z",
        "agents": [{"name": "WindowsAgent", "host": "WORKSTATION-ABC123"}],
        "hosts": [{"ip": "100.0.0.9", "hostname": "WORKSTATION-ABC123",
                   "source": "bus-api", "kind": "windows", "os": "win32",
                   "arch": "x64", "methods": ["tcp", "icmp"],
                   "ports": {"445": "smb"}}],
    }
    written = fd.write_manifests(data, tmp_path)
    assert len(written) == 1
    doc = json.loads(Path(written[0]).read_text())
    assert doc["host_kind"] == "windows"
    assert doc["agentes_observados"] == ["WindowsAgent"]
    assert "smb:445" in doc["services"]


def test_source_has_no_hardcoded_peer_names():
    src = SCRIPT.read_text()
    assert "DESKTOP-" not in src and "LAPTOP-" not in src
