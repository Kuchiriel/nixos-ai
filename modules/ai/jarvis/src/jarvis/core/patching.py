"""Dono único da política de SUBSTITUIR TRECHO DE TEXTO EM ARQUIVO.

(30/09) Terceira consolidação do dia. `nightwatch/patcher.py` e
`core/devtools.py` tinham cada um sua escada de busca do `old_text` e,
pior: só o patcher tinha `realign_indent`. O `devtools.str_replace` —
que é a ferramenta que o modelo USA no REPL — caía no mesmo bug de
indentação que eu levei horas para achar no nightwatch.

Duas escadas diferentes existiam:
  - patcher:  exato → whitespace-insensitive → fuzzy por LINHA (20%)
  - devtools: exato → normalizado     → difflib 75% → line-match

Unificar sem perder capacidade: as duas viraram ESTRATÉGIAS nomeadas na
mesma escada, ordenadas da mais rígida para a mais solta. Quem precisa
de um subconjunto, declara. O dono é um só.

O que NÃO entra aqui: política de segurança de path, backup, AST guard
de escrita. Isso tem dono próprio.
"""

from __future__ import annotations

import difflib
from typing import Callable

__all__ = [
    "normalize_line",
    "normalize_text",
    "realign_indent",
    "lines_match_fuzzy",
    "find_replacement",
    "apply_replacement",
    "STRATEGIES",
]


# ──────────────────────────────────────────────────────────────────────────
# Normalização
# ──────────────────────────────────────────────────────────────────────────
def normalize_line(line: str) -> str:
    """Linha sem whitespace interno — para comparar 'conteúdo', não layout."""
    return " ".join(line.split())


def normalize_text(text: str) -> str:
    """Texto com whitespace interno colapsado, linha a linha."""
    return "\n".join(normalize_line(l) for l in text.splitlines())


# ──────────────────────────────────────────────────────────────────────────
# O bug real
# ──────────────────────────────────────────────────────────────────────────
def realign_indent(new_text: str, old_text: str) -> str:
    """Re-alinha a indentação do new_text ao old_text REAL do arquivo.

    A falha real (30/09, run 16:45, ast_cache.py linha 126, 3 tentativas
    no MESMO ponto): o modelo copiava a indentação que *achava* que o
    arquivo tinha e, ao 'otimizar', reescrevia o bloco com um nível a
    menos → `unindent does not match`. O old_text casava (o harness casa
    ignorando whitespace), mas o new_text entrava com a indentação errada
    e o editor seguro barrava.

    Algoritmo: como já garantimos que o conteúdo não-indentado bate 1:1
    linha-a-linha, a indentação CORRETA de cada linha é a que o baseline
    (o old_text real) tem naquela posição. Reaplicamos o indent do
    baseline ao conteúdo do new_text. Cobre delta uniforme e não-uniforme
    (o caso real: linha em branco + `return False` legitimamente mais
    fundo). Zero aritmética de delta, zero caso especial.

    Só age quando o conteúdo bate 1:1. Se a LÓGICA difere de verdade, não
    toca — o guard reprova normalmente. Nunca mascaramos mudança de
    código real; só corrigimos deslize mecânico de indentação.
    """
    old_lines = old_text.split("\n")
    new_lines = new_text.split("\n")
    if len(old_lines) != len(new_lines) or len(old_lines) < 2:
        return new_text
    out: list[str] = []
    for o, n in zip(old_lines, new_lines):
        if not n.strip():
            out.append("")          # linha vazia fica vazia
            continue
        if o.strip() != n.strip():
            return new_text        # conteúdo diverge → não toca
        oi = len(o) - len(o.lstrip())
        out.append(" " * oi + n.strip())
    return "\n".join(out)


# ──────────────────────────────────────────────────────────────────────────
# Predicados
# ──────────────────────────────────────────────────────────────────────────
def lines_match_fuzzy(line_a: str, line_b: str, tolerance: float = 0.2) -> bool:
    """Duas linhas casam se a similaridade passa da tolerância.

    Linhas curtas (<20 chars) exigem igualdade EXATA: fuzzy em string
    curta é ruído, e é onde "casa com a linha errada" morre.
    """
    if len(line_a.strip()) < 20 or len(line_b.strip()) < 20:
        return line_a.strip() == line_b.strip()
    a, b = line_a.strip(), line_b.strip()
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= (1.0 - tolerance)


# ──────────────────────────────────────────────────────────────────────────
# A escada
# ──────────────────────────────────────────────────────────────────────────
def _s_exact(content: str, old: str) -> tuple[str | None, str]:
    if old and old in content:
        return old, "exact"
    return None, "none"


def _s_whitespace(content: str, old: str) -> tuple[str | None, str]:
    old_lines = old.splitlines()
    if not old_lines:
        return None, "none"
    cl = content.splitlines()
    for i in range(len(cl) - len(old_lines) + 1):
        window = cl[i:i + len(old_lines)]
        if "\n".join(normalize_line(l) for l in window) == "\n".join(normalize_line(l) for l in old_lines):
            return "\n".join(window), "whitespace"
    return None, "none"


def _s_line_fuzzy(content: str, old: str) -> tuple[str | None, str]:
    old_lines = old.strip().splitlines()
    cl = content.splitlines()
    if not old_lines:
        return None, "none"
    for i in range(len(cl) - len(old_lines) + 1):
        if all(lines_match_fuzzy(cl[i + j], ol) for j, ol in enumerate(old_lines)):
            return "\n".join(cl[i:i + len(old_lines)]), "line-fuzzy"
    return None, "none"


def _s_difflib(content: str, old: str) -> tuple[str | None, str]:
    old_lines = old.splitlines()
    cl = content.splitlines()
    if len(old_lines) < 2:
        return None, "none"
    best, best_i = 0.0, -1
    for i in range(len(cl) - len(old_lines) + 1):
        r = difflib.SequenceMatcher(
            None, "\n".join(old_lines), "\n".join(cl[i:i + len(old_lines)]),
        ).ratio()
        if r > best:
            best, best_i = r, i
    if best >= 0.75 and best_i >= 0:
        return "\n".join(cl[best_i:best_i + len(old_lines)]), f"difflib ({best:.0%})"
    return None, "none"


def _s_line_match(content: str, old: str) -> tuple[str | None, str]:
    old_lines = old.splitlines()
    cl = content.splitlines()
    if not old_lines:
        return None, "none"
    first = normalize_line(old_lines[0])
    for i, line in enumerate(cl):
        if normalize_line(line) == first:
            end = min(i + len(old_lines), len(cl))
            found = "\n".join(cl[i:end])
            if found.strip():
                return found, "line-match"
    return None, "none"


#: Ordem importa: da mais rígida para a mais solta. Nomes estáveis porque
#: viram log/evidência — mudar um nome aqui quebra leitura de run antigo.
STRATEGIES: dict[str, Callable[[str, str], tuple[str | None, str]]] = {
    "exact": _s_exact,
    "whitespace": _s_whitespace,
    "line-fuzzy": _s_line_fuzzy,
    "difflib": _s_difflib,
    "line-match": _s_line_match,
}
DEFAULT_ORDER = ("exact", "whitespace", "line-fuzzy", "difflib", "line-match")


def find_replacement(content: str, old: str,
                     order: tuple[str, ...] = DEFAULT_ORDER
                     ) -> tuple[str | None, str]:
    """Acha `old` em `content`. Devolve (texto_encontrado, estratégia)."""
    for name in order:
        fn = STRATEGIES.get(name)
        if not fn:
            continue
        found, strat = fn(content, old)
        if found is not None:
            return found, strat
    return None, "none"


def apply_replacement(content: str, old: str, new: str,
                      allow_multiple: bool = False,
                      order: tuple[str, ...] = DEFAULT_ORDER,
                      ) -> tuple[bool, str, str, int]:
    """Aplica old→new em `content`. Devolve (ok, novo_conteudo, estratégia, n).

    `realign_indent` é aplicado em TODO caminho, inclusive no match exato —
    a estratégia mais comum é justamente onde o deslize de indentação
    entrava e não era corrigido.
    """
    found, strategy = find_replacement(content, old, order)
    if found is None:
        return False, content, "none", 0

    # o realign usa o baseline REAL (o que está no arquivo), não o `old`
    # que o modelo mandou — é o arquivo que define a indentação correta.
    _new = realign_indent(new, found)

    n = content.count(found)
    if allow_multiple:
        new_content = content.replace(found, _new)
        return True, new_content, strategy, n
    new_content = content.replace(found, _new, 1)
    return True, new_content, strategy, 1
