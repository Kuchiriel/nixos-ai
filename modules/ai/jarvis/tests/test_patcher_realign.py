"""(30/09, C3b) Re-alinhamento de indentação no patcher.

Falha real medida (run nightwatch 16:45, archive/core/ast_cache.py:126):
o modelo copiava o `old_text` certo (casava literal no arquivo) mas
escrevia o `new_text` com um nível de indentação a menos →
`unindent does not match any outer indentation level`, e o safe_editor
barrava. Três tentativas no mesmo ponto.

A resposta NÃO é "é limite do modelo" — é engenharia de harness
(arxiv-2607.28802, "Model or Harness": a mesma falha pode pedir
engenharia de harness, não post-training). Aqui: o harness conserta o
deslize MECÂNICO de indentação, mas nunca mascara mudança de lógica.
"""
import ast

from nightwatch.patcher import PatchHunk, _realign_indent, apply_hunk


def test_realign_fixes_uniform_dedent():
    old = '            a = 1\n            b = 2'
    new = '        a = 1\n        b = 2'
    out = _realign_indent(new, old)
    assert out == '            a = 1\n            b = 2'


def test_realign_fixes_nonuniform_with_blank_lines():
    # caso real: linhas em branco + linha legitamente mais profunda
    old = ('            if x is None:\n'
           '                return False\n'
           '\n'
           '            a = 1')
    new = ('        if x is None:\n'
           '        return False\n'
           '\n'
           '    a = 1')
    out = _realign_indent(new, old)
    lines = out.split("\n")
    assert lines[0].startswith(" " * 12)
    assert lines[1].startswith(" " * 16)
    assert lines[3].startswith(" " * 12)


def test_realign_does_not_mask_real_logic_change():
    # conteúdo diferente → não toca (safe_editor reprova como deve)
    old = '        a = 1\n        b = 2'
    new = '        a = 999\n        b = 2 + 1'
    assert _realign_indent(new, old) == new


def test_apply_hunk_exact_match_still_realigns():
    # o bug: estratégia 1 (exact match) fazia replace sem realign
    old = ('    def check(self):\n'
           '        if True:\n'
           '            h = 1\n'
           '        return h')
    new = ('    def check(self):\n'
           '        if True:\n'
           '        h = 1\n'
           '    return h')
    content = "class X:\n" + old + "\n"
    # sem realinhamento seria inválido:
    try:
        ast.parse(content.replace(old, new, 1))
        raise AssertionError("fixture deveria ser sintaticamente inválido")
    except SyntaxError:
        pass
    ok, out = apply_hunk(content, PatchHunk(old_text=old, new_text=new))
    assert ok
    ast.parse(out)  # sem SyntaxError → o fix funcionou


def test_apply_hunk_preserves_real_change():
    old = '        a = 1'
    new = '        a = 2'
    content = "def f():\n    " + old + "\n"
    ok, out = apply_hunk(content, PatchHunk(old_text=old, new_text=new))
    assert ok and "a = 2" in out