"""Harness fala inglês (29/09).

Consenso do setor: harness de agente é em inglês, mesmo com modelo
multilíngue. Motivo prático, não estético: modelo pequeno processa
instrução na língua em que foi mais treinado, e mistura de idioma em
prompt grande degrada aderência (já medido aqui: R1 e bonsai rendem
melhor em EN).

Este teste é o **guard de arquitetura**: qualquer lógica de decisão
que case literal PT-BR contra saída do modelo volta aqui. Bug real
encontrado por este caminho (29/09): o filtro de artefato do veredito
casava só "não existe", mas completion.py emite "doesn't exist yet" —
em prompt EN o nudge NUNCA disparava, RC 0 com zero entrega, e o
modelo lia/calculava certo sem nunca gravar. Custo: 0/16 numa bateria
inteira, sem nenhum erro aparente.

Distinção que este guard impõe:
- string PT **exibida ao usuário** (Rich, output do CLI) = OK
- string PT **injetada no modelo** ou **comparada com o modelo** = bug
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"

# Palavras PT que indicam lógica de decisão (não texto exibido).
# Detector por PALAVRA, não por regex de literal: o bug real usa
# aspas simples dentro de aspas duplas, e qualquer regex por string
# erra nesse caso. O teste valida isso contra o bug pré-fix.
PT_WORDS = frozenset("""
não nao nenhum nenhuma pasta leia crie escreva corrija precisa preciso
obrigatório obrigatorio concluído concluido conclusao concluida
resolvido feito criado instrução instrucao verificacao verifique
procure encontre arquivo arquivos
""".split())


def _has_pt(text: str) -> bool:
    """Contém palavra PT de decisão? (case-insensitive, acento-insensitive)"""
    import unicodedata
    norm = "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if not unicodedata.combining(c))
    return any(re.search(rf"\b{re.escape(w)}\b", norm) for w in PT_WORDS)


def _py_files():
    return [p for p in SRC.rglob("*.py")
            if "webui" not in str(p) and "node_modules" not in str(p)]


def test_no_pt_literal_in_comparisons() -> None:
    """Nada de comparar literal PT contra saída do modelo."""
    offenders = []
    for p in _py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for op in node.ops:
                if not isinstance(op, (ast.In, ast.NotIn)):
                    continue
                sides = [node.left, *node.comparators]
                for side in sides:
                    if (isinstance(side, ast.Constant)
                            and isinstance(side.value, str)
                            and _has_pt(side.value)):
                        offenders.append(f"{p}:{node.lineno} {side.value[:60]!r}")
    # Exceção real: validator.py casa PT **e** EN no mesmo teste (bug
    # sanitize de 16/09 já treated). Qualquer outro PT é bug.
    assert not [o for o in offenders if not o.rsplit("/", 1)[-1].startswith("validator.py")], (
        "literal PT em comparação sem par EN — adicione o par EN ou case "
        "por classe:\n" + "\n".join(
            o for o in offenders if not o.rsplit("/", 1)[-1].startswith("validator.py")))


def test_system_nudges_are_english_first() -> None:
    """Nudges injetados no histórico começam em inglês.

    O harness injeta instrução para o MODELO ler. Se começar em PT, um
    modelo não-bilingue perde a instrução inteira sem erro visível.
    """
    offenders = []
    for p in _py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except ast.SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            role = content = None
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                    if k.value == "role":
                        role = v.value
                    elif k.value == "content" and isinstance(v.value, str):
                        content = v.value
            if role not in ("system", "user"):
                continue
            if not content or len(content) < 40:
                continue
            if _has_pt(content):
                # aceita se as primeiras palavras já são ASCII/EN
                head = content[:60]
                has_en_head = bool(re.match(
                    r"^[\x00-\x7F\u2014\s\.,:;()\-'\"/]+[A-Za-z]{3,}", head))
                if not has_en_head:
                    offenders.append(f"{p}:{node.lineno} {content[:70]!r}")
    assert not offenders, (
        "nudge injetado em PT-BR sem cabeçalho EN — o modelo pode não "
        "entender a instrução:\n" + "\n".join(offenders))


def test_tool_descriptions_are_english() -> None:
    """29/09: as 22 descrições de tool que o modelo lê em CADA call
    estavam em PT-BR. Tradução de schema é contrato — migração por
    dicionário determinístico (`scripts/migrate-tools-en.py`), nunca
    por LLM."""
    import re as _re
    import jarvis.cli.dev as _dev
    from jarvis.core.completion import _PATH_LIKE  # noqa: F401

    # verbos PT em forma de verbo (naoradical: 'Cria' tambem eh
    # 'Creates' em EN, entao exige palavra PT inteira).
    PT_DESC = _re.compile(
        r'\b(leia|escreva|escrita|corrija|correção|procure|procurar|'
        r'navegador|obrigatório|obrigatorio|conteúdo|conteudo|'
        r'retorna|devolve|listar|gravar|rodar|avaliar|indexar)\b', _re.I)
    tools = _dev._get_tools(None)
    assert tools, "tool surface vazia — o guard testaria nada"
    offenders = []
    for t in tools:
        fn = t.get("function") or {}
        for text in (fn.get("description", ""), *[
                (p.get("description") or "") for p in
                ((fn.get("parameters") or {}).get("properties") or {}).values()
                if isinstance(p, dict)]):
            if text and PT_DESC.search(text):
                offenders.append(f"{fn.get('name')}: {text[:60]}")
    assert not offenders, (
        "tool description em PT-BR — o modelo le isso a cada call:\n"
        + "\n".join(offenders))
