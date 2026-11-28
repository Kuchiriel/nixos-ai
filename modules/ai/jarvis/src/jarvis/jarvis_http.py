"""jarvis_http.py — o JARVIS (RAG, memória, lições, vault) em MCP por HTTP.

POR QUE (07/11/2026, dono): *"combinar expor tools jarvis para uso dele como rag,
memory e tudo que for util que temos ou até ajudar eles criarem uma versão deles"*.
O MCP do JARVIS é **stdio** ⇒ só alcança agentes na MESMA máquina. As outras
lanes (Windows, Termux, celular) estão em outras máquinas e não têm RAG nem
memória própria ⇒ cada uma reimplementou (ou ficou sem) busca.

O QUE ESTE MÓDULO FAZ (e não faz):
- serve por MCP `streamable-http` o **subconjunto de conhecimento** do JARVIS:
  RAG (code/memories/books), memória (remember/recall), lições (lessons),
  vault e as ferramentas de leitura/escrita que não tocam o desktop do dono;
- **NÃO** duplica lógica: cada tool chama o `core/` existente (mesmo princípio
  do `coord_http.py` ⇒ um lugar só muda, os dois servidores受益);
- **NÃO** expõe o que age no desktop do dono (`human_input`, `game`,
  `observe_screen`, `browser`, `execute`) — essas continuam no servidor stdio:
  quem está na tailnet não deve poder clicar no mouse do dono sem querer.

DECISÃO DE SEGURANÇA (medida 05/11 no coord-mcp): o FastMCP **remove o header
`Authorization`** antes de chegar nas tools ⇒ não dá para exigir senha no
FastMCP. A proteção é a **ACL do Tailscale** (só a tailnet chega) + o bind no
IP do tailnet (NÃO 0.0.0.0). Por isso: **host default = 127.0.0.1** e o
serviço do home-manager aponta para o IP do tailnet.

COMO RODAR:
    python -m jarvis.jarvis_http --host 127.0.0.1 --port 8766
    # exposto na tailnet (host=IP_TAILNET) => http://<ip>:8766/mcp

CLIENTE (opencode, outra máquina):
    {"type": "remote", "url": "http://${TAILNET_HOST}:8766/mcp", "enabled": true}
    → as tools aparecem como `jarvis_*` (prefixo do server key).

REQUISITO: `fastmcp` no python do serviço (medido: 3.2.3 no perfil do JARVIS).
"""

from __future__ import annotations

import argparse
import os

SERVER_NAME = "jarvis-knowledge"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766


def build_server():
    try:
        from fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise SystemExit(
            "jarvis_http: falta o pacote 'fastmcp' neste python.\n"
            "  - no shell de desenvolvimento: nix develop --command python -m jarvis.jarvis_http\n"
            f"  - detalhe: {exc}"
        )

    mcp = FastMCP(SERVER_NAME, instructions=(
        "Conhecimento do JARVIS para agentes em qualquer maquina: RAG semantico "
        "(rag_search/rag_index), memoria (remember/recall), licoes (lessons) e "
        "vault. Use rag_search ANTES de reimplementar uma busca, lessons ANTES de "
        "repetir um erro, remember no fim da tarefa. As collections do RAG: "
        "code (codigo indexado), memories (memoria do JARVIS), books (papers)."
    ))

    # ── RAG ──────────────────────────────────────────────────────────────
    @mcp.tool
    def jarvis_rag_search(query: str, collection: str = "code", limit: int = 5) -> str:
        """Busca semantica no RAG: collection 'code' | 'memories' | 'books'."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_rag_search", {"query": query, "collection": collection, "limit": limit})

    @mcp.tool
    def jarvis_rag_index(path: str) -> str:
        """Indexa um diretorio no RAG (use quando a collection esta vazia)."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_rag_index", {"path": path})

    # ── memória ──────────────────────────────────────────────────────────
    @mcp.tool
    def jarvis_remember(text: str, category: str = "fact") -> str:
        """Guarda um fato/evento/decisao/erro na memoria do JARVIS."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_remember", {"text": text, "category": category})

    @mcp.tool
    def jarvis_recall(query: str, top_k: int = 5) -> str:
        """Busca na memoria episodica: o que ja foi decidido/medido sobre um tema."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_recall", {"query": query, "top_k": top_k})

    @mcp.tool
    def jarvis_lessons(query: str) -> str:
        """Licoes passadas (o 'nao repita isso'): erros ja corrigidos e como."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_lessons", {"query": query})

    # ── vault (sobrevive a compactacao) ───────────────────────────────────
    @mcp.tool
    def jarvis_vault_list() -> str:
        """Lista as notas do vault persistente."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_vault_list", {})

    @mcp.tool
    def jarvis_vault_search_obsidian(query: str) -> str:
        """Busca no vault por texto."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_vault_search_obsidian", {"query": query})

    @mcp.tool
    def jarvis_vault_write(name: str, content: str) -> str:
        """Escreve uma nota no vault (achado que deve sobreviver a compactacao)."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_vault_write", {"name": name, "content": content})

    # ── leitura do estado do JARVIS ──────────────────────────────────────
    @mcp.tool
    def jarvis_nix_search(action: str, query: str = "", source: str = "nixos",
                          type: str = "packages", limit: int = 10) -> str:
        """Consulta o nixpkgs real (anti-alucinacao): search/info/browse/stats."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_nix_search", {"action": action, "query": query,
                                               "source": source, "type": type, "limit": limit})

    @mcp.tool
    def jarvis_web_search(query: str, limit: int = 5) -> str:
        """Busca na web (Tavily) para assunto atual ou externo ao codigo."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_web_search", {"query": query, "limit": limit})

    # ── corpus offline (N.O.M.A.D / Kiwix) ───────────────────────────────
    @mcp.tool
    def jarvis_offline_search(query: str, max_results: int = 5) -> str:
        """Busca no corpus OFFLINE de sobrevivencia (agua, primeiros socorros,
        remedios caseiros, abrigo, emergencia). Funciona SEM internet e nunca
        inventa: sem fonte local devolve NO OFFLINE SOURCE."""
        from jarvis.mcp_server import call_tool
        return call_tool("jarvis_offline_search", {"query": query,
                                                   "max_results": max_results})

    return mcp


def main() -> int:
    ap = argparse.ArgumentParser(description="JARVIS (RAG/memoria/licoes/vault) em MCP HTTP")
    ap.add_argument("--host", default=os.environ.get("JARVIS_HTTP_HOST", DEFAULT_HOST))
    ap.add_argument("--port", type=int, default=int(os.environ.get("JARVIS_HTTP_PORT", DEFAULT_PORT)))
    args = ap.parse_args()
    mcp = build_server()
    mcp.run(transport="streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
