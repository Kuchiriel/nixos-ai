"""Testes do canal A2A (scripts/agent-msg.sh) — os 3 defeitos medidos.

(26/11, medido no host nitro-v15) O canal entre agentes estava QUEBRADO em
tres pontos, todos com sintoma proprio e nenhum com teste:

1. `--to <nome>` devolvia "nenhum alvo (modo=<nome>)" mesmo com a sessao do
   alvo VIVA na API. Causa: no resolver, o `else` que acrescentava o alvo
   estava ligado ao `if hit:` dentro de `elif me and not force:`; com claim do
   remetente e SEM sobreposição de arquivos, o alvo era descartado em
   silencio.

2. A liveness era medida por uma URL que nao respondia. O serve do opencode
   escuta SO no IP do tailnet (home-manager/modules/services/opencode-serve.nix
   -> `--hostname 100.121.100.103 --port 4599`), mas o config centralizado
   declarava `http://127.0.0.1:4599` (Connection refused) -> o roster marcava
   sessao VIVA como dead, o `agent-msg.sh` recusava a entrega ("nao esta vivo")
   e o prune do roster APAGAVA entradas de agentes vivos.

3. A fila de pendentes nunca fechava: o pedido e gravado no log como
   `$5 = id=m-1795...` e a resposta traz `$6 = re=m-1795...`; o awk tirava o
   prefixo "re=" e guardava `m-1795...`, enquanto o pedido ficava sob
   `id=m-1795...` -> nenhuma resposta casava e os 104 pedidos ficavam
   "pendentes" para sempre.

Teste OFFLINE: nao toca rede, nao acorda agente, nao escreve no roster real.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AGENT_MSG = REPO / "scripts" / "agent-msg.sh"
AGENT_CONFIG = REPO / "scripts" / "agent-config.json"


def _run(*args: str, log: Path | None = None, env: dict | None = None
         ) -> subprocess.CompletedProcess:
    """Roda o agent-msg.sh com LOG isolado (nunca toca o log da casa)."""
    import os
    e = dict(os.environ)
    if log is not None:
        e["AGENTS_MSG_LOG"] = str(log)
    if env:
        e.update(env)
    return subprocess.run(["bash", str(AGENT_MSG), *args], capture_output=True,
                          text=True, env=e, timeout=60, cwd=str(REPO))


# ── defeito 3: a fila de pendentes tem de fechar quando a resposta chega ──

def _pending_lines(log: Path) -> list[str]:
    proc = _run("--pending", log=log)
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def test_pending_clears_when_the_reply_carries_the_receipt(tmp_path):
    """Um ask respondido por `re=<id>` NAO pode continuar na fila."""
    log = tmp_path / "AGENTS-MSG.log"
    log.write_text(
        "26/11 00:00 | agent-1 | ask | challenge-dev(@sess:ses_x) | "
        "id=m-123 | re=- | please redo the submission\n"
        "26/11 00:05 | challenge-operator | note | challenge-dev(@sess:ses_x) | "
        "id=m-456 | re=m-123 | done, rescore 14/14\n",
        encoding="utf-8")
    out = _pending_lines(log)
    assert not any("m-123" in ln for ln in out), out


def test_pending_keeps_unanswered_ask(tmp_path):
    """Sem resposta, o ask continua na fila (o tracker nao pode mentir)."""
    log = tmp_path / "AGENTS-MSG.log"
    log.write_text(
        "26/11 00:00 | agent-1 | ask | challenge-dev(@sess:ses_x) | "
        "id=m-123 | re=- | please redo the submission\n",
        encoding="utf-8")
    out = _pending_lines(log)
    assert any("m-123" in ln for ln in out), out
    assert any("please redo the submission" in ln for ln in out), out


def test_pending_shows_the_request_text_not_the_re_field(tmp_path):
    """O texto exibido e o do PEDIDO ($7), nao o campo `re=` ($6)."""
    log = tmp_path / "AGENTS-MSG.log"
    log.write_text(
        "26/11 00:00 | agent-1 | ask | challenge-dev(@sess:ses_x) | "
        "id=m-123 | re=- | please redo the submission\n",
        encoding="utf-8")
    out = _pending_lines(log)
    assert out and "re=- |" not in out[0], out


def test_pending_ignores_the_dash_placeholder_as_a_receipt(tmp_path):
    """`re=-` e o placeholder de 'sem referencia': nao fecha nada."""
    log = tmp_path / "AGENTS-MSG.log"
    log.write_text(
        "26/11 00:00 | agent-1 | ask | challenge-dev(@sess:ses_x) | "
        "id=m-123 | re=- | please redo the submission\n"
        "26/11 00:05 | challenge-operator | note | challenge-dev(@sess:ses_x) | "
        "id=m-456 | re=- | sem referencia\n",
        encoding="utf-8")
    out = _pending_lines(log)
    assert any("m-123" in ln for ln in out), out


# ── defeito 2: as URLs do config tem de ser as que respondem ─────────────

def _config() -> dict:
    import json
    return json.loads(AGENT_CONFIG.read_text(encoding="utf-8"))


def test_config_oc_url_is_the_tailnet_address_not_loopback():
    """O serve escuta SO no IP do tailnet: o loopback recusa a conexão."""
    cfg = _config()
    assert cfg["ambiente"]["AGENTS_OC_URL"] == "http://100.121.100.103:4599"
    assert cfg["servicos"]["opencode_serve"]["host"] == "100.121.100.103"


def test_config_coord_mcp_url_is_the_tailnet_address_not_loopback():
    """O coord-mcp tambem escuta SO no tailnet (medido: 127.0.0.1:8765 recusa)."""
    cfg = _config()
    assert cfg["ambiente"]["COORD_MCP_URL"] == "http://100.121.100.103:8765/mcp"
    assert cfg["servicos"]["coord_mcp"]["host"] == "100.121.100.103"


def test_agent_config_module_exposes_the_working_urls():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "agent_config_probe", REPO / "scripts" / "agent_config.py")
    mod = importlib.util.module_from_spec(spec)
    # o dataclass precisa do modulo registrado em sys.modules
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    c = mod.cfg()
    assert c.env("AGENTS_OC_URL") == "http://100.121.100.103:4599"
    assert c.env("COORD_MCP_URL") == "http://100.121.100.103:8765/mcp"
    assert c.OC_URL == "http://100.121.100.103:4599"
    assert c.COORD_URL == "http://100.121.100.103:8765/mcp"


# ── defeito 1: o alvo nomeado tem de entrar na lista de destinos ─────────

def test_named_target_is_not_dropped_when_there_is_no_file_overlap():
    """O `else` do resolver nao pode descartar o alvo nomeado.

    Regressao do sintoma medido: `agent-msg.sh --to <nome>` devolvia
    'nenhum alvo (modo=<nome>)' mesmo com o alvo VIVO.
    """
    src = AGENT_MSG.read_text(encoding="utf-8")
    # o bloco que decide o alvo nomeado precisa acrescentar o alvo ao
    # protegido por `elif me and not force:` (sem overlap => target entra)
    bloco = re.search(
        r"elif me and not force:(.*?)\n    else:\n        targets\.append",
        src, re.S)
    assert bloco, "bloco 'elif me and not force:' nao encontrado"
    corpo = bloco.group(1)
    assert "targets.append(alvo(a))" in corpo, (
        "o alvo nomeado e descartado quando nao ha sobreposicao de arquivos")
