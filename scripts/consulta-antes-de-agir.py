#!/usr/bin/env python3
"""
consulta-antes-de-agir.py — CLI auxiliar para forçar a consulta prévia.

Dado um topico ou ação, responde quais MCP chamar e onde fica a
documentação relevante, para o agente nao "bater cabeca" sem consultar.

Uso:
  python3 scripts/consulta-antes-de-agir.py topico="editar arquivo X"
  python3 scripts/consulta-antes-de-agir.py acao="rm -rf algo"
  python3 scripts/consulta-antes-de-agir.py --list-mcps
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("JARVIS_REPO", "/home/nixos/projects/nixos-ai"))

# Mapa: topico/chave -> (quais MCP chamar, onde fica a doc, o que ler)
CONSULTA_MAP = {
    "editar": {
        "mcps": ["jarvis_rag_search", "jarvis_recall"],
        "colecoes": ["code"],
        "query_hint": "nome do arquivo ou funcao a editar",
        "doc": "docs/architecture/context-engineering.md",
        "leia_antes": "AGENTS.md do projeto mais proximo ao arquivo",
    },
    "arquivo": {
        "mcps": ["jarvis_rag_search", "jarvis_recall"],
        "colecoes": ["code"],
        "query_hint": "caminho do arquivo",
        "doc": "docs/architecture/context-engineering.md",
        "leia_antes": "AGENTS.md + BUFFY.md (regra do proprietario)",
    },
    "comando destrutivo": {
        "mcps": ["jarvis_lessons", "jarvis_rag_search"],
        "colecoes": ["memories", "code"],
        "query_hint": "erro ou acao semelhante ja feita",
        "doc": "ai-mesh/docs/ARMADILHAS.md",
        "leia_antes": "ARMADILHAS.md (host, erro, causa, correcao)",
    },
    "erro repetido": {
        "mcps": ["jarvis_lessons", "jarvis_recall"],
        "colecoes": ["memories"],
        "query_hint": "texto do erro ou codigo de saida",
        "doc": "ai-mesh/docs/ARMADILHAS.md",
        "leia_antes": "liçao ja registrada para este erro",
    },
    "decisao ja tomada": {
        "mcps": ["jarvis_recall", "jarvis_rag_search"],
        "colecoes": ["memories", "sessions"],
        "query_hint": "decisao sobre o topico",
        "doc": "docs/architecture/ADR-002-memory-layers.md",
        "leia_antes": "fato em recall prevalece sobre hipotese working",
    },
    "revisao de codigo": {
        "mcps": ["jarvis_rag_search", "jarvis_recall"],
        "colecoes": ["code"],
        "query_hint": "modulo ou padrao a revisar",
        "doc": "docs/architecture/agent-harness.md",
        "leia_antes": "checker travado + prova de 2 sentidos",
    },
    "deploy / rebuild": {
        "mcps": ["jarvis_lessons", "jarvis_rag_search"],
        "colecoes": ["memories", "code"],
        "query_hint": "rebuild-host ou nixos-rebuild",
        "doc": "docs/architecture/system-overview.md",
        "leia_antes": "rebuild-host.sh so com autorizacao do dono",
    },
    "acao no bus": {
        "mcps": ["jarvis_coord_read", "jarvis_coord_check"],
        "colecoes": [],
        "query_hint": "files que pretende tocar",
        "doc": ".agents/mcp-catalog.md",
        "leia_antes": "colisao de escopo com outro agente",
    },
    "novo agente / spawn": {
        "mcps": ["jarvis_coord_roster", "jarvis_rag_search"],
        "colecoes": ["code"],
        "query_hint": "lane e arquivos do novo agente",
        "doc": ".agents/mcp-catalog.md",
        "leia_antes": "roster.json + claim de escopo",
    },
}

MCPS_DESC = {
    "jarvis_rehydrate": "Início de sessão / problema repetido: guarda + fila + HANDOFF + memoria + RAG + roster.",
    "jarvis_recall": "Fato/decisao/erro do passado. top_k=5, vazia significa 'na ha memoria registrada'.",
    "jarvis_rag_search": "Codigo/doc onde vive X. collection=code|memories|books|sessions, antes de grep cego.",
    "jarvis_lessons": "Armadilha ja registrada para este erro. Obrigatorio antes de retry.",
    "jarvis_coord_read": "Estado do bus: claims, colisoes, PRs abertos.",
    "jarvis_coord_check": "Veredito mecanico de colisao para um escopo de arquivos.",
    "jarvis_coord_roster": "Quem esta nessa maquina e o que esta fazendo.",
}


def topico_para_chave(topico: str) -> str:
    t = topico.lower()
    for chave in CONSULTA_MAP:
        if chave in t:
            return chave
    return "desconhecido"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Diga quais MCP consultar antes de agir."
    )
    ap.add_argument("topico", nargs="?", help="topico ou acao planejada")
    ap.add_argument("--list-mcps", action="store_true", help="lista todos os MCP de consulta")
    args = ap.parse_args()

    if args.list_mcps:
        print("MCP de consulta (qualquer um satisfate o requisito):")
        for nome, desc in MCPS_DESC.items():
            print(f"  {nome}: {desc}")
        return 0

    if not args.topico:
        ap.error("informe o topico (ex.: 'editar arquivo X', 'comando destrutivo')")

    chave = topico_para_chave(args.topico)
    entrada = CONSULTA_MAP.get(chave)

    print(f"Topico: {args.topico}")
    print(f"Cenário detectado: {chave}")
    print()

    if entrada:
        print("MCP para chamar (antes de agir):")
        for mcp in entrada["mcps"]:
            print(f"  • {mcp}")
        if entrada["colecoes"]:
            print(f"  Coleções sugeridas: {', '.join(entrada['colecoes'])}")
        print(f"  Query sugerida: {entrada['query_hint']}")
        print()
        print(f"Doc de referência: {entrada['doc']}")
        print(f"Leia antes: {entrada['leia_antes']}")
    else:
        print("Cenario nao reconhecido. Consulte pelo menos um destes MCP:")
        print("  • jarvis_rehydrate(task=...)")
        print("  • jarvis_recall(query=...)")
        print("  • jarvis_rag_search(query=..., collection=code)")
        print("  • jarvis_lessons(query=...)")
        print()
        print("Doc geral: .agents/mcp-catalog.md")

    print()
    print("Ordem obrigatoria: rehydrate -> recall -> rag_search -> act -> lessons (falha) -> remember (fim)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
