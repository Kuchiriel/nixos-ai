#!/usr/bin/env python3
"""migrate-tools-en.py — tool descriptions PT→EN (29/09, harness em inglês).

As 22 descrições de tool que o modelo lê em CADA call estavam em PT-BR.
O guard `test_harness_language.py` pegaria regressão futura, mas não
converte o que já existe. Aqui: dicionário explícito, determinístico,
revisável — nada de LLM traduzindo schema (tradução automática de
JSON schema é como se quebra um contrato sem aviso).

Idempotente: rodar 2× não muda nada. `--check` só reporta.
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / (
    "modules/ai/jarvis/src/jarvis/cli/dev.py")

# PT original -> EN. Chave = texto exato; valor = tradução revisada.
# Mantém o mesmo conteúdo informativo (o modelo depende de saber
# "sempre antes de str_replace", "old vazio = cria", etc).
M = {
    # properties (o guard de tool tambem os cobre)
    "Caminho do arquivo": "File path",
    "O que gravar": "What to store",
    "Diretório para indexar (padrão: atual)": "Directory to index (default: current)",
    "Conteúdo completo": "Full file content",
    "Modo de captura": "Capture mode",
    "Termo de busca": "Search term",
    "Conteúdo": "Content",
    "Lê um arquivo com números de linha. Use sempre antes de str_replace.":
        "Read a file with line numbers. Always read before str_replace.",
    "Caminho relativo do arquivo": "File path (relative to project root)",
    "Linha inicial (opcional, 0-indexed)": "Start line (optional, 0-indexed)",
    "Máximo de linhas (padrão 2000)": "Max lines (default 2000)",
    "Substitui trecho EXATO. old vazio = criar arquivo novo. Fuzzy match automático.":
        "Replace an EXACT snippet. Empty old = create a new file. "
        "Automatic fuzzy match.",
    "Texto exato (vazio para criar)": "Exact text (empty to create)",
    "Texto novo": "New text",
    "Executa comando shell (bash -c). Explorar, testar, git, curl.":
        "Run a shell command (bash -c). Explore, test, git, curl.",
    "Comando shell (bash -c)": "Shell command (bash -c)",
    "Busca semântica no código (mais inteligente que grep, mais lenta).":
        "Semantic search over the codebase (smarter than grep, slower).",
    "Consulta semântica (dense+sparse)": "Semantic query (dense+sparse)",
    "Cria/escreve arquivo completo. Backup automático + AST guard. Cria pastas-pai.":
        "Create/write a whole file. Auto-backup + AST guard. Creates parent dirs.",
    "Lista diretório (recursivo limitado).":
        "List a directory (limited recursion).",
    "Caminho do diretório": "Directory path",
    "Captura e analisa screenshot com vision AI.":
        "Capture and analyze a screenshot with vision AI.",
    "Cria/escreve arquivo completo. Backup automático + AST guard. Cria pastas-pai.":
        "Create/write a whole file. Auto-backup + AST guard. Creates missing "
        "parent directories: to build a directory structure, call write_file "
        "with the full path of each FILE inside it (the folders appear by "
        "themselves).",
    "Cria/escreve arquivo completo. Backup automático + AST guard. Cria pastas-pai ausentes: para criar uma estrutura de past":
        "Create/write a whole file. Auto-backup + AST guard. Creates missing "
        "parent directories: to build a directory structure, call write_file "
        "with the full path of each FILE inside it (the folders appear by "
        "themselves).",
    "Captura screenshot da tela atual.":
        "Take a screenshot of the current screen.",
    "Avalia expressão Nix.": "Evaluate a Nix expression.",
    "Roda nix flake check.": "Run `nix flake check`.",
    "Pesquisa packages/options no nixpkgs.":
        "Search packages/options in nixpkgs.",
    "Grava fato/evento na memória episódica.":
        "Store a fact/event in episodic memory.",
    "Busca memórias por similaridade.":
        "Search memories by similarity.",
    "Lista notas no vault persistente.":
        "List notes in the persistent vault.",
    "Escreve nota no vault.": "Write a note to the vault.",
    "Busca semântica no codebase.":
        "Semantic search over the codebase.",
    "Indexa diretório no RAG (torna código buscabável).":
        "Index a directory into RAG (makes code searchable).",
    "Busca lições aprendidas de erros passados.":
        "Search lessons learned from past mistakes.",
    "Lê conversa compartilhada do ChatGPT.":
        "Read a shared ChatGPT conversation.",
    "Lê conversa de qualquer IA (ChatGPT, Gemini, Claude). Auto-detecta da URL.":
        "Read a shared AI conversation (ChatGPT, Gemini, Claude). "
        "Auto-detects the platform from the URL.",
    "Pesquisa na internet (Tavily). Use para atualidades, docs e qualquer pergunta fora do codebase.":
        "Search the web (Tavily). Use for current events, docs, and any "
        "question outside the codebase.",
    "Navegador headless (somente leitura de páginas + interação simples). Ações: open (url), click (selector CSS), fill (sele":
        "Headless browser (page reading + simple interaction only). Actions: "
        "open (url), click (CSS selector), fill (selector), press (key), "
        "wait, extract (readable text).",
}

# Heurísticas para o resto (par property→description genéricos).
HEUR = {
    "Parâmetros da busca semântica": "Semantic search parameters",
    "Consulta": "Query",
    "Número máximo de resultados": "Max results",
}


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    orig = src
    hits: list[tuple[str, str]] = []
    for pt, en in M.items():
        if pt in src:
            n = src.count(pt)
            src = src.replace(pt, en)
            hits.append((pt[:44], f"x{n}"))
    for pt, en in HEUR.items():
        if pt in src:
            src = src.replace(pt, en)
            hits.append((pt[:44], "heur"))

    if "--check" in sys.argv:
        changed = [p for p in M if p in orig]
        print(f"PT ainda presente: {len(changed)}")
        for p in changed:
            print("  -", p[:60])
        return 1 if changed else 0

    if src == orig:
        print("nada a fazer (já migrado)")
        return 0
    TARGET.write_text(src, encoding="utf-8")
    print(f"migradas {len(hits)} strings:")
    for pt, n in hits:
        print(f"  [{n}] {pt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
