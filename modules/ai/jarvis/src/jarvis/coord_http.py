"""coord_http.py —coord em MCP por HTTP (streamable-http) para a tailnet.

POR QUE ESTE ENTRYPOINT (05/11/2026): o dono pediu a coordenação de agentes
**dentro do MCP**. O MCP do JARVIS hoje é **stdio** (JSON-RPC na stdin) — só
alcança quem está na mesma máquina. Para a outra máquina da tailnet (o
opencode do Windows) falar com o JARVIS, o mesmo conjunto de tools precisa
ser servido em **HTTP**.

O QUE ESTE MÓDULO FAZ (e não faz):
- serve o **conjunto de coordenação** (bus global + roster local) por MCP
  `streamable-http` — as mesmas funções de `core/coord.py` e
  `core/coord_roster.py`, sem duplicar lógica;
- NÃO reimplementa o MCP do JARVIS inteiro: `mcp_server.py` continua sendo o
  servidor stdio, dono das ~40 tools. Aqui o objetivo é o **canal de
  coordenação** entre máquinas, que é o que o dono pediu;
- o resto do JARVIS (RAG, memória, vault) **continua no servidor stdio** — o
  cliente remoto usa o que precisar via esse servidor.

COMO RODAR:
    python -m jarvis.coord_http --host 0.0.0.0 --port 8765
    # ou por env: FASTMCP_HOST=0.0.0.0 FASTMCP_PORT=8765

O `--host 0.0.0.0` expõe na tailnet (e na LAN) — a proteção é o **Tailscale**
(traefego ACL da tailnet) + a senha do opencode server. Para expor só na
tailnet, aponte para a IP do tailnet em vez de 0.0.0.0.

ENDPOINT: http://<host>:<porta>/mcp  (streamable-http)

CLIENTE (opencode, outro agente):
    {"type": "remote", "url": "http://<ip-tailnet>:<porta>/mcp",
     "enabled": true, "headers": {"Authorization": "Basic <b64>"}
    }
    → as tools aparecem como `coord_*` (prefixo do server key).

REQUISITO: `fastmcp` no python do serviço. Medido em 05/11/2026: presente no
python do perfil do JARVIS (3.2.3); se faltar, este comando explica o
`nix develop --command python -m jarvis.coord_http` como caminho de teste.
"""

from __future__ import annotations

import argparse
import os
import sys

SERVER_NAME = "jarvis-coord"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def build_server():
    """Cria o app FastMCP com o conjunto de coordenação."""
    try:
        from fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise SystemExit(
            "coord_http: falta o pacote 'fastmcp' neste python.\n"
            "  - no shell de desenvolvimento: nix develop --command python -m jarvis.coord_http\n"
            f"  - detalhe: {exc}"
        )

    mcp = FastMCP(SERVER_NAME, instructions=(
        "Coordenação entre agentes: publique a SUA claim antes de editar "
        "(coord_post), leia o estado (coord_read) e verifique colisão de escopo "
        "(coord_check). O roster local (coord_roster/coord_whoami/"
        "coord_set_context/coord_msg) mostra quem está fazendo o quê."
    ))

    @mcp.tool
    def coord_post(kind: str = "claim", agent: str = "", lane: str = "",
                   files: str = "", intent: str = "", pr: int | None = None,
                   note: str = "") -> str:
        """Publica a claim/status desta IA no bus de coordenação."""
        from jarvis.core.coord import post
        return post(kind=kind, agent=agent or None, lane=lane, files=files,
                    intent=intent, pr=pr, note=note)

    @mcp.tool
    def coord_read() -> str:
        """Estado do bus: claim de cada agente, colisões, claims velhos, PRs."""
        from jarvis.core.coord import read
        return read()

    @mcp.tool
    def coord_check(agent: str = "", files: str = "") -> str:
        """Verifica colisão de escopo com a claim de outro agente."""
        from jarvis.core.coord import check
        return check(agent=agent or None, files=files)

    @mcp.tool
    def coord_roster() -> str:
        """Roster local: codinome, nome, lane, estado e contexto de cada agente."""
        from jarvis.core.coord_roster import roster_text
        return roster_text()

    @mcp.tool
    def coord_whoami(agent: str = "") -> str:
        """Cartão de visita desta IA: codinome, lane, escopo e contexto."""
        from jarvis.core.coord_roster import whoami
        return whoami(agent or None)

    @mcp.tool
    def coord_set_context(context: str, agent: str = "") -> str:
        """Atualiza a frase de contexto desta IA (muda quando o assunto muda)."""
        from jarvis.core.coord_roster import set_context
        return set_context(context, agent or None)

    @mcp.tool
    def coord_msg(to: str, message: str, note: bool = True) -> str:
        """Entrega mensagem a um par (por codinome ou nome). note=True não roda o turno dele."""
        from jarvis.core.coord_roster import send_message
        return send_message(to, message, note=note)

    @mcp.tool
    def coord_peers() -> str:
        """Peers da tailnet alcançáveis desta máquina."""
        from jarvis.core.coord_roster import peers
        return peers()

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jarvis.coord_http",
        description="Serve as tools de coordenação do JARVIS por MCP streamable-http.",
    )
    parser.add_argument("--host", default=os.environ.get("FASTMCP_HOST", DEFAULT_HOST),
                        help=f"bind (default {DEFAULT_HOST}; use a IP do tailnet)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("FASTMCP_PORT", DEFAULT_PORT)),
                        help=f"porta (default {DEFAULT_PORT})")
    args = parser.parse_args(argv)

    mcp = build_server()
    mcp.run(transport="streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
