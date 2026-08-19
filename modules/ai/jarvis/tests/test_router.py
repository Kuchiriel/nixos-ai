"""Testes do roteador de intenções (core/router.py)."""

from jarvis.core.router import (
    _extract_nix_term,
    _strip_stopwords,
    route_request,
)


# ---------------------------------------------------------------------------
# Roteamento (cascata por custo)
# ---------------------------------------------------------------------------


def test_route_doctor() -> None:
    for text in [
        "como está a saúde do sistema?",
        "status dos serviços ativos",
        "verificar o sistema e o disco",
        "checar se os serviços estão rodando",
        "doctor",
    ]:
        assert route_request(text).handler == "doctor", text


def test_route_nixos() -> None:
    for text in [
        "qual o pacote do ripgrep no nixpkgs?",
        "existe services.qdrant.enable no nixos?",
        "como habilitar o serviço de ssh no nixos?",
        "procure a opção programs.git do home manager",
    ]:
        assert route_request(text).handler == "nixos", text


def test_route_rag() -> None:
    for text in [
        "onde está o arquivo vector_store.py no código?",
        "qual função implementa o hybrid search no repo?",
        "procura no código onde é usado o QdrantStore",
        "como funciona o intents.py indexado?",
    ]:
        assert route_request(text).handler == "rag", text


def test_route_agent_fallback() -> None:
    for text in [
        "conte uma história sobre gatos",
        "me explique o conceito de recursão",
        "escreva um e-mail para meu chefe",
        "o que você acha de nixos?",
    ]:
        assert route_request(text).handler == "agent", text


def test_route_empty() -> None:
    assert route_request("").handler == "agent"


def test_route_extension_forces_rag() -> None:
    assert route_request("me mostra o content de default.nix").handler == "rag"
    assert route_request("o que tem no flake.nix").handler == "rag"


def test_route_reason_present() -> None:
    r = route_request("qual o pacote do kitty")
    assert r.reason and "nixpkgs" in r.reason


# ---------------------------------------------------------------------------
# Extração de termos Nix
# ---------------------------------------------------------------------------


def test_extract_nix_term_option() -> None:
    assert _extract_nix_term("existe services.qdrant.enable?") == "services.qdrant.enable"
    assert _extract_nix_term("como habilitar programs.git") == "programs.git"


def test_extract_nix_term_package() -> None:
    assert _extract_nix_term("qual o pacote do ripgrep") == "ripgrep"
    assert _extract_nix_term("procure o package kitty") == "kitty"


def test_extract_nix_term_none() -> None:
    assert _extract_nix_term("oi tudo bem") is None


def test_strip_stopwords() -> None:
    out = _strip_stopwords("qual o pacote do ripgrep no nixpkgs")
    assert "ripgrep" in out
    assert "o" not in out.split()


# ---------------------------------------------------------------------------
# Handlers (com mocks)
# ---------------------------------------------------------------------------


def test_handle_nixos_with_mcp_fake(tmp_path, monkeypatch) -> None:
    """A rota nixos chama o mcp-nixos (fake via subprocess) e retorna o texto."""
    import sys

    server = tmp_path / "fake_mcp.py"
    server.write_text(
        "import json, sys\n"
        "def respond(m): sys.stdout.write(json.dumps(m)+'\\n'); sys.stdout.flush()\n"
        "for line in sys.stdin:\n"
        "    line = line.strip()\n"
        "    if not line: continue\n"
        "    try: req = json.loads(line)\n"
        "    except Exception: continue\n"
        "    if req.get('method') == 'initialize':\n"
        "        respond({'jsonrpc':'2.0','id':req['id'],'result':{'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'fake','version':'1'}}})\n"
        "    elif req.get('method') == 'tools/list':\n"
        "        respond({'jsonrpc':'2.0','id':req['id'],'result':{'tools':[{'name':'nix','description':'q','inputSchema':{'type':'object','properties':{}}}]}})\n"
        "    elif req.get('method') == 'tools/call':\n"
        "        respond({'jsonrpc':'2.0','id':req['id'],'result':{'content':[{'type':'text','text':'Option: services.qdrant.enable'}]}})\n"
    )
    from jarvis.core.router import handle_nixos

    out = handle_nixos("existe services.qdrant.enable?", mcp_bin=f"{sys.executable} {server}")
    assert out["route"] == "nixos"
    assert out["query"] == "services.qdrant.enable"
    assert "services.qdrant.enable" in out["result"]
    assert out["error"] is None


def test_handle_nixos_bin_missing() -> None:
    from jarvis.core.router import handle_nixos

    out = handle_nixos("qual o pacote do kitty", mcp_bin="/nope/does-not-exist-bin")
    assert out["error"] is not None
    assert out["result"] == ""
