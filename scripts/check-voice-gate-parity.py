"""Prova de paridade: o gate do duplex-asrd e o de voice_gate.py são o mesmo.

POR QUE (09/11, sweep-2026-11)
O bench media um proxy do gate (igualdade exata em 2 TSV) e o gate de
produção é uma pilha de ramos (substring, greeting-fantasma, redup,
"legenda", léxico gated, ALL-CAPS, stats, tokens-vs-duração). Medir o proxy
dá um número que não é o do gate, e a divergência aparece como "o gate
fecha / não fecha" — que é exatamente a decisão pendente do dono.

Este checker compara os DOIS códigos por token stream (não por texto): nome,
literais e operadores precisam bater; comentário, quebra de linha e indentação
não contam. String é comparada por conteúdo (um "e aí" diferente de "e ai"
aparece como divergência, porque a lista de greeting depende da letra).

O que é comparado:
  1. a função anti_halluc (a decisão);
  2. a função load_lexicon (a lista base);
  3. o bloco try que carrega a lista multilingual (gated + ban-hard);
  4. os literais HALLUC_PT, SOCIAL_KEEP e GREET_SUS.

USO
    python3 scripts/check-voice-gate-parity.py
SAÍDA
    0 = paridade ✓   1 = divergência (com o bloco culpado)
"""
import ast
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASRD = ROOT / "scripts" / "duplex-asrd.py"
GATE = ROOT / "scripts" / "voice_gate.py"

KEEP = (tokenize.NAME, tokenize.NUMBER, tokenize.STRING, tokenize.OP)


def file_tokens(path: Path) -> list:
    """Todos os tokens significativos do arquivo, com a linha de origem."""
    out = []
    with path.open() as f:
        for tok in tokenize.generate_tokens(f.readline):
            if tok.type in KEEP:
                out.append((tok.start[0], tokenize.tok_name[tok.type], tok.string))
    return out


def node_tokens(all_toks: list, node) -> list:
    """Tokens do nó, pelo intervalo de linhas."""
    lo = getattr(node, "lineno", 0)
    hi = getattr(node, "end_lineno", lo)
    return [(kind, s) for (line, kind, s) in all_toks if lo <= line <= hi]


def find_func(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def find_assign(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return node
    return None


def find_multi_try(tree: ast.AST):
    """O try que carrega a lista multilingual.

    O marcador e o NOME DO ARQUIVO, e nao `MULTI_HARD`: em 10/11 a lane de
    voz removeu o ramo ban-hard (que o gate nunca consultava), e o bloco
    deixou de mencionar aquela variavel. Procurar pelo arquivo acha o
    bloco nos dois formatos.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and "whisper-halluc-ban-multilingual" in ast.dump(node):
            return node
    return None


def check(label: str, ta: list, tb: list, problems: list) -> None:
    if ta == tb:
        print(f"  [ok]   {label} ({len(ta)} tokens)")
        return
    problems.append(label)
    print(f"  [FALHA] {label}")
    for i, (x, y) in enumerate(zip(ta, tb)):
        if x != y:
            print(f"          primeira diferença no token {i}: "
                  f"asrd={x} gate={y}")
            print(f"          contexto asrd: {ta[max(0, i - 6):i + 6]}")
            print(f"          contexto gate: {tb[max(0, i - 6):i + 6]}")
            break
    else:
        print(f"          tamanhos diferentes: asrd={len(ta)} gate={len(tb)}")


def main() -> int:
    asrd_src = ASRD.read_text()
    gate_src = GATE.read_text()
    asrd_tree = ast.parse(asrd_src)
    gate_tree = ast.parse(gate_src)
    asrd_toks = file_tokens(ASRD)
    gate_toks = file_tokens(GATE)
    problems: list = []

    print(f"paridade do gate: {ASRD.name} <-> {GATE.name}")
    for fname in ("anti_halluc", "load_lexicon"):
        fa = find_func(asrd_tree, fname)
        fb = find_func(gate_tree, fname)
        if fa is None or fb is None:
            problems.append(fname)
            print(f"  [FALHA] {fname}: função não encontrada "
                  f"(asrd={fa is not None} gate={fb is not None})")
            continue
        check(fname, node_tokens(asrd_toks, fa), node_tokens(gate_toks, fb),
              problems)

    ta = find_multi_try(asrd_tree)
    tb = find_multi_try(gate_tree)
    if ta is None or tb is None:
        problems.append("bloco multilingual")
        print("  [FALHA] bloco multilingual: try não encontrado")
    else:
        check("bloco multilingual (gated + ban-hard)",
              node_tokens(asrd_toks, ta), node_tokens(gate_toks, tb), problems)

    for lit in ("HALLUC_PT", "SOCIAL_KEEP", "GREET_SUS"):
        aa = find_assign(asrd_tree, lit)
        ab = find_assign(gate_tree, lit)
        if aa is None or ab is None:
            problems.append(lit)
            print(f"  [FALHA] {lit}: literal não encontrado")
            continue
        try:
            va = ast.literal_eval(aa.value)
            vb = ast.literal_eval(ab.value)
        except Exception as exc:  # noqa: BLE001
            problems.append(lit)
            print(f"  [FALHA] {lit}: literal_eval falhou ({exc})")
            continue
        if va == vb:
            print(f"  [ok]   {lit} ({len(va)} entradas)")
        else:
            problems.append(lit)
            print(f"  [FALHA] {lit}: asrd={sorted(va)} gate={sorted(vb)}")

    if problems:
        print(f"\nDIVERGENCIA: {', '.join(problems)}")
        return 1
    print("\nparidade ok: o gate do asrd e o de voice_gate.py sao o mesmo codigo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
