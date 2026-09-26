"""Completion policy: DONE só com evidência (P0.2) + erro nunca encerra (P0.3)."""

from __future__ import annotations

from jarvis.core.completion import check_completion, classify_error


def _msgs(*contents):
    return [{"role": "tool", "content": c} for c in contents]


def test_trailing_error_is_unverified():
    v = check_completion(_msgs("ok resultado", "ERROR: algo quebrou"))
    assert v.status == "UNVERIFIED"
    assert any("erro" in m for m in v.missing)


def test_zero_success_is_unverified():
    v = check_completion(_msgs("ERROR: x"))
    assert v.status == "UNVERIFIED"
    assert any("ground truth" in m for m in v.missing)


def test_clean_run_is_verified():
    v = check_completion(_msgs("conteúdo lido"))
    assert v.status == "VERIFIED"
    assert v.missing == []


def test_written_missing_file_is_unverified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    msgs = [{"role": "tool", "content": "written"},
            {"role": "assistant", "tool_calls": [
                {"function": {"name": "write_file",
                              "arguments": {"path": "novo.txt"}}}]},
            {"role": "tool", "content": "written"}]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("não existe" in m for m in v.missing)


def test_written_py_compiles(tmp_path, monkeypatch):
    from jarvis.core.paths import use_project_root
    (tmp_path / "ok.py").write_text("x = 1\n")
    msgs = [{"role": "assistant", "tool_calls": [
        {"function": {"name": "write_file",
                      "arguments": {"path": "ok.py"}}}]},
            {"role": "tool", "content": "written"}]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert v.status == "VERIFIED"
    assert any("compila" in e for e in v.evidence)


def test_written_py_syntax_error(tmp_path, monkeypatch):
    from jarvis.core.paths import use_project_root
    (tmp_path / "bad.py").write_text("def f(:\n")
    msgs = [{"role": "assistant", "tool_calls": [
        {"function": {"name": "write_file",
                      "arguments": {"path": "bad.py"}}}]},
            {"role": "tool", "content": "written"}]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("não compila" in m for m in v.missing)


def test_classify_error_kinds():
    assert classify_error("ERROR: Command timed out after 60s") == "transient"
    assert classify_error("ERROR: Command denied by user") == "policy"
    assert classify_error("ERROR: File not found: x") == "missing"
    assert classify_error("ERROR: Malformed tool call structure") == "bad-request"
    assert classify_error("ERROR: algo estranho") == "failed"
    assert classify_error("conteúdo normal") == "ok"


def test_identical_error_thrice_is_stuck(tmp_path):
    """Mesmo erro 3x → STUCK com final honesto (P0.3)."""
    import json as jsonlib
    from unittest.mock import patch
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa

    class AlwaysFail(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{
                       "id": "c1", "type": "function",
                       "function": {"name": "execute_shell",
                                   "arguments": jsonlib.dumps(
                                       {"cmd": "ls /definitely/not/here"})}}]}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=AlwaysFail(),
                  audit_path=tmp_path / "a.jsonl")
    with patch("jarvis.core.agent.run_shell") as rs:
        import subprocess
        rs.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="no such file")
        result = agent.run("liste aquilo")
    assert result.verdict == "STUCK"
    assert result.verified is False
    assert "STUCK" in result.final_response


def test_text_claim_without_tools_is_unverified_then_continues():
    """Texto 'done' sem tools: turnos de verificação antes de fechar."""
    from unittest.mock import patch
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa

    calls = {"n": 0}

    class TextThenTool(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                msg = {"role": "assistant", "content": "done!"}
            elif calls["n"] == 2:
                msg = {"role": "assistant",
                       "content": "done!",
                       "tool_calls": [{
                           "id": "c1", "type": "function",
                           "function": {
                               "name": "read_file",
                               "arguments": '{"path": "x"}'}}]}
            else:
                msg = {"role": "assistant", "content": "lido, de verdade"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=TextThenTool())
    with patch("jarvis.core.devtools.read_file",
               return_value={"ok": True, "content": "conteúdo",
                             "path": "x", "total_lines": 1}):
        result = agent.run("leia x")
    # 1º turno texto puro → verificação exige evidência → continua e lê.
    assert result.turns >= 2
    assert result.verdict == "VERIFIED"
    assert result.verified is True


def test_claimed_creation_without_write_is_unverified():
    """'Criei dobra.py' sem write_file no run = falsa conclusão (C2 real)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "read_file",
                          "arguments": '{"path": "x"}'}}]},
        {"role": "tool", "content": "conteúdo"},
        {"role": "assistant",
         "content": "O arquivo `dobra.py` foi criado com o conteúdo."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("sem escrita" in m for m in v.missing)


def test_pure_text_run_skips_claim_rule():
    """Run sem tools: regra de artefato não se aplica (Q&A puro)."""
    from jarvis.core.completion import check_completion
    v = check_completion([{"role": "assistant",
                           "content": "A capital é Brasília."}])
    assert v.status == "UNVERIFIED"  # zero ground truth (outra regra)


def test_denied_but_observed_is_unverified():
    """'X não existe' quando o ls listou X = falsa conclusão (N2 real)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "ls"}'}}]},
        {"role": "tool", "content": "app.py\nservico.nix\nnotas.md"},
        {"role": "assistant",
         "content": "O arquivo servico.nix não existe no local."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("nega evidência" in m for m in v.missing)


def test_claimed_content_without_read_is_unverified():
    """Elo H1: afirma valor de arquivo nunca lido → UNVERIFIED com miss."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "user", "content": "qual o default?"},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "list_directory",
                          "arguments": {"path": "/etc/jarvis"}}}]},
        {"role": "tool", "content": "DIRECTORY (1 items): model-registry.json"},
        {"role": "assistant",
         "content": "O default declarado em /etc/jarvis/model-registry.json é `bonsai`."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("sem leitura" in m for m in v.missing)


def test_claimed_content_with_read_is_verified():
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "user", "content": "qual o default?"},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "read_file",
                          "arguments": {"path": "/etc/jarvis/model-registry.json"}}}]},
        {"role": "tool", "content": '{"default": "bonsai"}'},
        {"role": "assistant",
         "content": "O default declarado em /etc/jarvis/model-registry.json é `bonsai`."},
    ]
    v = check_completion(msgs)
    assert v.status == "VERIFIED"


def _shell_msgs(cmd, final):
    return [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "%s"}' % cmd}}]},
        {"role": "tool", "content": "ok"},
        {"role": "assistant", "content": final},
    ]


def test_shell_written_claimed_exists_is_verified(tmp_path):
    """Escrita via shell `>` é write-action: afirmado + existe = VERIFIED."""
    from jarvis.core.completion import check_completion
    from jarvis.core.paths import use_project_root
    (tmp_path / "relatorio.md").write_text("# ok\n")
    with use_project_root(tmp_path):
        v = check_completion(_shell_msgs(
            "echo conteudo > relatorio.md",
            "O arquivo relatorio.md foi criado."))
    assert v.status == "VERIFIED"
    assert any("relatorio.md" in e for e in v.evidence)


def test_shell_written_py_syntax_error_is_unverified(tmp_path):
    """AST vale p/ escrita via shell também."""
    from jarvis.core.completion import check_completion
    from jarvis.core.paths import use_project_root
    (tmp_path / "bad.py").write_text("def f(:\n")
    with use_project_root(tmp_path):
        v = check_completion(_shell_msgs(
            "echo 'def f(:' > bad.py",
            "O arquivo bad.py foi criado."))
    assert v.status == "UNVERIFIED"
    assert any("não compila" in m for m in v.missing)


def test_shell_without_redir_claim_still_unverified(tmp_path):
    """Shell sem escrita (`ls`) + afirmação de criação = UNVERIFIED (sem
    enfraquecer a regra: só redirecionamento conta como write-action)."""
    from jarvis.core.completion import check_completion
    from jarvis.core.paths import use_project_root
    (tmp_path / "velho.md").write_text("x\n")
    with use_project_root(tmp_path):
        v = check_completion(_shell_msgs(
            "ls",
            "O arquivo velho.md foi criado."))
    assert v.status == "UNVERIFIED"
    assert any("sem escrita" in m for m in v.missing)


def test_shell_redir_noise_ignored(tmp_path):
    """`>&2`, `/dev/null` e `2>` sem extensão não viram artefatos."""
    from jarvis.core.completion import _shell_write_paths
    msgs = _shell_msgs("cmd >&2; outro > /dev/null", "fim.")
    assert _shell_write_paths(msgs) == []
    assert _shell_write_paths(_shell_msgs(
        "echo x | tee saida.txt", "fim.")) == ["saida.txt"]
    assert _shell_write_paths(_shell_msgs(
        "echo a >> log.txt && echo b > rel.md", "fim.")) == [
        "log.txt", "rel.md"]


def test_claimed_merge_without_mutation_is_unverified():
    """fix-git real: checkout+leitura e 'merge feito' sem mutação."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "git log --all --oneline"}'}}]},
        {"role": "tool", "content": "19b5d10 Update site"},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "git checkout master"}'}}]},
        {"role": "tool", "content": "Switched to branch master"},
        {"role": "assistant", "content":
         "Recuperei as mudancas perdidas e fiz merge delas na master."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("sem ação de escrita" in m for m in v.missing)


def test_claimed_merge_with_git_mutation_is_verified():
    """Merge real via shell conta como mutação (sem enfraquecer)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "git merge recovery-branch"}'}}]},
        {"role": "tool", "content": "Merge made"},
        {"role": "assistant", "content": "Fiz merge da recovery-branch."},
    ]
    v = check_completion(msgs)
    assert v.status == "VERIFIED"


def test_plain_checkout_is_not_mutation():
    """`git checkout master` sozinho não é ação mutante."""
    from jarvis.core.completion import _mutating_shell
    assert _mutating_shell("git checkout master") is False
    assert _mutating_shell("git checkout -b nova") is True
    assert _mutating_shell("git merge ramo") is True
    assert _mutating_shell("git commit -m x") is True
    assert _mutating_shell("ls -la") is False


def test_final_question_is_handoff_not_verified():
    """Tools irrelevantes com sucesso + final em pergunta = UNVERIFIED."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "book_search",
                          "arguments": '{"q": "personal site"}'}}]},
        {"role": "tool", "content": "nada relevante"},
        {"role": "assistant", "content":
         "Nao encontrei. Quer que eu busque a estrutura de diretorios?"},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("handoff" in m or "nada a fazer" in m for m in v.missing)


def test_final_plea_without_question_is_handoff():
    """Súplica sem '?' ('forneça mais detalhes') também é handoff."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "book_search",
                          "arguments": '{"q": "x"}'}}]},
        {"role": "tool", "content": "nada"},
        {"role": "assistant", "content":
         "Nao encontrei o dragao. Por favor, forneça mais detalhes."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("handoff" in m or "nada a fazer" in m for m in v.missing)


def test_handoff_provide_path_pattern():
    """"provide the correct path" sem "?" também é handoff."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "grep -r x ."}'}}]},
        {"role": "tool", "content": "nada"},
        {"role": "assistant", "content":
         "Not found. Please ensure it is present and provide the correct path."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("handoff" in m for m in v.missing)


def test_handoff_matches_without_accent():
    """'posso ajudá-lo' casa com padrão sem acento (fuga real)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "git stash list"}'}}]},
        {"role": "tool", "content": "sem entradas no stash"},
        {"role": "assistant", "content":
         "Nada no stash. Se você puder me informar mais, posso ajudá-lo."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("handoff" in m for m in v.missing)


def test_noop_without_grounded_search_is_unverified():
    """'cannot find any' sem busca/leitura com sucesso no repo = miss."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "book_search",
                          "arguments": '{"q": "keys"}'}}]},
        {"role": "tool", "content": "no hits"},
        {"role": "assistant", "content":
         "I cannot find any API keys. No changes were made."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("nada a fazer" in m for m in v.missing)


def test_numeric_write_without_compute_is_unverified():
    """Número 'calculado' de cabeça sem execute_shell = miss (L2 real)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "user", "content": "calcule a média e grave em n.txt"},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "write_file",
                          "arguments": '{"path": "n.txt", "content": "15.0"}'}}]},
        {"role": "tool", "content": "ok: write_file n.txt"},
        {"role": "assistant", "content": "Média 15.0 gravada."},
    ]
    import tempfile
    from pathlib import Path as _P
    from jarvis.core.paths import use_project_root
    d = _P(tempfile.mkdtemp())
    (d / "n.txt").write_text("15.0\n")
    with use_project_root(d):
        v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("sem cálculo" in m for m in v.missing)


def test_numeric_write_after_compute_passes_rule():
    """Número impresso pelo cálculo e depois gravado: regra não veta."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "python3 -c print(15.0)"}'}}]},
        {"role": "tool", "content": "15.0"},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "write_file",
                          "arguments": '{"path": "n.txt"}'}}]},
        {"role": "tool", "content": "ok: write_file n.txt"},
        {"role": "assistant", "content": "Média 15.0 gravada."},
    ]
    import tempfile
    from pathlib import Path as _P
    from jarvis.core.paths import use_project_root
    d = _P(tempfile.mkdtemp())
    (d / "n.txt").write_text("15.0\n")
    with use_project_root(d):
        v = check_completion(msgs)
    assert not any("sem cálculo" in m for m in v.missing)


def test_noop_with_successful_read_stays_eligible():
    """Triage com leitura real: regra noop não veta (outras decidem)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "read_file",
                          "arguments": '{"path": "cfg.yaml"}'}}]},
        {"role": "tool", "content": "key: ok"},
        {"role": "assistant", "content": "Checked cfg.yaml, nothing to fix."},
    ]
    v = check_completion(msgs)
    assert not any("nada a fazer" in m for m in v.missing)


def test_residual_secret_value_in_edited_file_is_unverified():
    """L4 real: trocou o NOME, valor AKIA ficou — mundo deve vetar."""
    from jarvis.core.completion import check_completion
    from jarvis.core.paths import use_project_root
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / "process.py").write_text(
        'os.environ["<your-aws-access-key-id>"] = "AKIA1234567890123456"\n')
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "str_replace",
                          "arguments": '{"path": "process.py"}'}}]},
        {"role": "tool", "content": "ok: str_replace process.py"},
        {"role": "assistant", "content":
         "Troquei as chaves por placeholders, tudo limpo."},
    ]
    with use_project_root(d):
        v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("segurado" in m or "padrão" in m for m in v.missing)


def test_no_residual_secret_value_is_eligible():
    from jarvis.core.completion import check_completion
    from jarvis.core.paths import use_project_root
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / "process.py").write_text(
        'os.environ["AWS_ACCESS_KEY_ID"] = "<your-aws-access-key-id>"\n')
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "str_replace",
                          "arguments": '{"path": "process.py"}'}}]},
        {"role": "tool", "content": "ok: str_replace process.py"},
        {"role": "assistant", "content": "Valores trocados por placeholders."},
    ]
    with use_project_root(d):
        v = check_completion(msgs)
    assert not any("padrão de segredo" in m for m in v.missing)


def test_content_claim_without_successful_write_is_unverified():
    """'successfully sanitized/replacing' sem write com sucesso = miss
    (sanitize real: só git-ops irrelevantes, segredos intactos)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "git merge recovery"}'}}]},
        {"role": "tool", "content": "Already up to date."},
        {"role": "assistant", "content":
         "I have successfully sanitized the repo, replacing all secrets."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("sem escrita" in m for m in v.missing)


def test_content_claim_with_successful_write_is_verified():
    from jarvis.core.completion import check_completion
    from jarvis.core.paths import use_project_root
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / "f.txt").write_text("limpo\n")
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "write_file",
                          "arguments": '{"path": "f.txt"}'}}]},
        {"role": "tool", "content": "ok: write_file f.txt"},
        {"role": "assistant", "content": "Sanitizei f.txt, removendo tudo."},
    ]
    with use_project_root(d):
        v = check_completion(msgs)
    assert v.status == "VERIFIED"


def test_final_question_with_verified_artifact_stays_verified():
    """Pergunta extra após artefato verificado não derruba o veredito."""
    from jarvis.core.completion import check_completion
    from jarvis.core.paths import use_project_root
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / "nota.txt").write_text("x\n")
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "write_file",
                          "arguments": '{"path": "nota.txt"}'}}]},
        {"role": "tool", "content": "written"},
        {"role": "assistant", "content": "Criei nota.txt. Precisa de mais?"},
    ]
    with use_project_root(d):
        v = check_completion(msgs)
    assert v.status == "VERIFIED"


def test_verify_budget_exhaustion_is_unverified():
    """Stall ("aguarde...") até o fim do orçamento: UNVERIFIED, nunca
    VERIFIED vazio herdado (fix-git real: enrolação sem git)."""
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa

    texts = ["Vou verificar o repositorio.",
             "Por favor, aguarde enquanto eu faço isso.",
             "Só mais um instante, estou localizando."]

    class Staller(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            i = min(self.calls - 1, len(texts) - 1)
            return FakeResponse({"choices": [{"message": {
                "role": "assistant", "content": texts[i]}}]})

    agent = Agent(Config(), session=Staller())
    result = agent.run("faça algo")
    assert result.verdict == "UNVERIFIED"
    assert result.verified is False
    assert any("orçamento" in m for m in result.missing)


def test_hollow_promise_consumes_verify_turn():
    """Promessa futura com veredito oco não finaliza de imediato: consome
    turno de verificação (fix-git real: 'I will check...' e parou)."""
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa

    class Promiser(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            return FakeResponse({"choices": [{"message": {
                "role": "assistant",
                "content": "Working on it. I will check the logs next."}}]})

    agent = Agent(Config(), session=Promiser())
    result = agent.run("faça algo")
    assert result.verdict == "UNVERIFIED"
    assert result.turns >= 3


def test_traceback_counts_as_error_not_success():
    """Traceback Python é falha (csv real: import com ModuleNotFoundError
    contou como leitura ok e o modelo seguiu iludido)."""
    from jarvis.core.completion import check_completion
    tb = ("Traceback (most recent call last):\n  File \"x\", line 1\n"
          "ModuleNotFoundError: No module named 'pandas'")
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "python3 -c import pandas"}'}}]},
        {"role": "tool", "content": tb},
        {"role": "assistant", "content": "Li o CSV, vou converter."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("ground truth" in m for m in v.missing)


def test_pending_recovery_note_blocks_verified():
    """STATE(unexecuted_script) sem execução posterior → nunca VERIFIED
    (L8 real: over-claim sem rodar os scripts)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": '{"path": "d.sh", "content": "echo"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok: write_file d.sh"},
        {"role": "user",
         "content": "STATE(unexecuted_script:d.sh). You WROTE but never RAN."},
        {"role": "assistant", "content": "done: d.sh"},
    ]
    v = check_completion(msgs)
    assert v.status != "VERIFIED"
    assert any("nunca executado" in m for m in v.missing)


def test_resolved_recovery_note_allows_verified():
    """Nota + execução posterior → sem bloqueio."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": '{"path": "d.sh", "content": "echo"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok: write_file d.sh"},
        {"role": "user",
         "content": "STATE(unexecuted_script:d.sh). You WROTE but never RAN."},
        {"role": "assistant", "tool_calls": [{
            "id": "c2", "type": "function",
            "function": {"name": "execute_shell",
                         "arguments": '{"cmd": "./d.sh"}'}}]},
        {"role": "tool", "tool_call_id": "c2", "content": "ok\n[exit: 0]"},
        {"role": "assistant", "content": "done"},
    ]
    v = check_completion(msgs)
    assert not any("nunca executado" in m for m in v.missing)


def test_written_sh_never_executed_blocks_verified(tmp_path):
    """.sh escrito com +x mas nunca executado → nunca VERIFIED
    (execution-based verification, Code-as-Harness 2605.18747: generaliza
    STATE(unexecuted_script) p/ todo .sh escrito, sem nota do harness)."""
    import os
    from jarvis.core.paths import use_project_root
    (tmp_path / "e.sh").write_text("#!/bin/sh\necho hi\n")
    os.chmod(tmp_path / "e.sh", 0o755)
    msgs = [
        {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": '{"path": "e.sh", "content": "echo hi"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok: write_file e.sh"},
        {"role": "assistant", "content": "done: e.sh"},
    ]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert v.status != "VERIFIED"
    assert any("nunca executado" in m for m in v.missing)


def test_written_sh_executed_allows_verified(tmp_path):
    """.sh escrito + executado → sem bloqueio de execução."""
    import os
    from jarvis.core.paths import use_project_root
    (tmp_path / "e.sh").write_text("#!/bin/sh\necho hi\n")
    os.chmod(tmp_path / "e.sh", 0o755)
    msgs = [
        {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": '{"path": "e.sh", "content": "echo hi"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok: write_file e.sh"},
        {"role": "assistant", "tool_calls": [{
            "id": "c2", "type": "function",
            "function": {"name": "execute_shell",
                         "arguments": '{"cmd": "chmod +x e.sh && ./e.sh"}'}}]},
        {"role": "tool", "tool_call_id": "c2", "content": "hi\n[exit: 0]"},
        {"role": "assistant", "content": "done"},
    ]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert not any("nunca executado" in m for m in v.missing)


def test_prompt_deliverable_missing_is_miss(tmp_path):
    """Prompt pede a.sh+b.sh, só a.sh existe → miss nomeando b.sh (L8:
    parte 2 nunca começada)."""
    from jarvis.core.paths import use_project_root
    (tmp_path / "a.sh").write_text("#!/bin/sh\necho hi\n")
    msgs = [
        {"role": "user",
         "content": "Create two scripts a.sh and b.sh that process logs."},
        {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": '{"path": "a.sh", "content": "echo hi"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert v.status != "VERIFIED"
    assert any("b.sh" in m and "doesn't exist" in m for m in v.missing)


def test_invalid_root_json_is_miss(tmp_path):
    """.json inválido no CWD vira miss com o erro (L8v23: outputs gerados
    inválidos sem nada acusar no loop)."""
    from jarvis.core.paths import use_project_root
    (tmp_path / "alert.json").write_text("{invalid\n")
    msgs = [
        {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": '{"path": "x.sh", "content": "echo"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert v.status != "VERIFIED"
    assert any("alert.json" in m and "not valid JSON" in m
               for m in v.missing)


def test_unquoted_keys_named(tmp_path):
    """Chave sem aspas é nomeada no diagnóstico (L8v24: 3 ciclos)."""
    from jarvis.core.paths import use_project_root
    (tmp_path / "alert.json").write_text("{timestamp: 1}\n")
    msgs = [
        {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": '{"path": "x"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert any('{"timestamp"' in m for m in v.missing)


def test_missing_deliverables_helper(tmp_path):
    """Helper reutilizável (veredito + progress-check do loop)."""
    from jarvis.core.completion import missing_deliverables
    from jarvis.core.paths import use_project_root
    (tmp_path / "a.sh").write_text("#!/bin/sh\n")
    msgs = [{"role": "user", "content": "Make a.sh and b.sh please."},
            {"role": "assistant", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "write_file",
                             "arguments": '{"path": "a.sh"}'}}]},
            {"role": "tool", "content": "ok"}]
    with use_project_root(tmp_path):
        from jarvis.core.devtools import resolve_base
        out = missing_deliverables(msgs, resolve_base())
    assert any("b.sh" in m for m in out)
    assert not any("a.sh" in m for m in out)


def test_missing_deliverables_json_txt_with_creation_verb(tmp_path):
    """Generalização (Ciclo 5/L9-werr): artefatos .json/.txt citados no
    prompt COM verbo de criação e ausentes são cobrados (antes só .sh)."""
    from jarvis.core.completion import missing_deliverables
    from jarvis.core.paths import use_project_root
    (tmp_path / "in.csv").write_text("a,b\n")
    msgs = [{"role": "user",
             "content": "Read in.csv and write report.json and notes.txt."}]
    with use_project_root(tmp_path):
        from jarvis.core.devtools import resolve_base
        out = missing_deliverables(msgs, resolve_base())
    assert any("report.json" in m for m in out)
    assert any("notes.txt" in m for m in out)
    # input existente não é cobrado
    assert not any("in.csv" in m for m in out)


def test_missing_deliverables_no_verb_no_charge(tmp_path):
    """Sem verbo de criação, .json mencionado não é cobrado (input)."""
    from jarvis.core.completion import missing_deliverables
    from jarvis.core.paths import use_project_root
    msgs = [{"role": "user",
             "content": "Look at config.json and tell me the version."}]
    with use_project_root(tmp_path):
        from jarvis.core.devtools import resolve_base
        out = missing_deliverables(msgs, resolve_base())
    assert not any("config.json" in m for m in out)


def test_valid_root_json_silent(tmp_path):
    """.json válido no CWD não dispara (nem inputs nem outputs bons)."""
    from jarvis.core.paths import use_project_root
    (tmp_path / "alert.json").write_text('{"a": 1}\n')
    msgs = [
        {"role": "assistant", "content": "done"},
    ]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert not any("not valid JSON" in m for m in v.missing)


def test_prompt_deliverable_present_no_miss(tmp_path):
    """Ambos citados existem → sem miss de cobertura."""
    from jarvis.core.paths import use_project_root
    (tmp_path / "a.sh").write_text("#!/bin/sh\necho hi\n")
    (tmp_path / "b.sh").write_text("#!/bin/sh\necho yo\n")
    msgs = [
        {"role": "user",
         "content": "Create two scripts a.sh and b.sh that process logs."},
        {"role": "assistant", "content": "done"},
    ]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert not any("doesn't exist yet" in m for m in v.missing)


def test_placeholder_value_blocks_verified(tmp_path, monkeypatch):
    """JSON válido com valor placeholder → UNVERIFIED (d3 20/09: VERIFIED
    vácuo com 'rule_id'; GAIA-2 soft check contra reward hacking)."""
    from jarvis.core.paths import use_project_root
    (tmp_path / "alert.json").write_text('{"id": "rule_id", "n": 1}\n')
    msgs = [{"role": "assistant", "tool_calls": [
        {"function": {"name": "write_file",
                      "arguments": {"path": "alert.json"}}}]},
            {"role": "tool", "content": "written"}]
    monkeypatch.chdir(tmp_path)
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("placeholder" in m for m in v.missing)


def test_clean_json_values_stay_verified(tmp_path, monkeypatch):
    """Valores reais (incl. substring 'TS' em 'ALERTS') não disparam —
    só full-value + <TOKEN> (sem falso-positivo em texto legítimo)."""
    from jarvis.core.paths import use_project_root
    (tmp_path / "a.json").write_text(
        '{"msg": "ALERTS processed", "ip": "45.32.67.89"}\n')
    msgs = [{"role": "assistant", "tool_calls": [
        {"function": {"name": "write_file",
                      "arguments": {"path": "a.json"}}}]},
            {"role": "tool", "content": "written"}]
    monkeypatch.chdir(tmp_path)
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert not any("placeholder" in m for m in v.missing)


def test_instrucao_lida_no_arquivo_nunca_executada_e_UNVERIFIED(tmp_path):
    """(25/09, LOOP-v3 — G3 no REPL real) O modelo lê um brief cuja
    instrução pede 'create /path/x.txt', alego 'Done' e NADA cria.
    Antes: VERIFIED (cego — nenhum check cobria 'instrução dentro de
    resultado de tool'). Agora: UNVERIFIED + missing nomeia o path."""
    import json as _json
    from jarvis.core.completion import check_completion
    alvo = tmp_path / "marker.txt"
    msgs = [
        {"role": "system", "content": "agent"},
        {"role": "user", "content": "read the brief and do what it asks"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {
                "name": "read_file",
                "arguments": _json.dumps({"path": str(tmp_path / "brief.txt")})}}]},
        {"role": "tool", "tool_call_id": "c1",
         "content": f"FINAL INSTRUCTION: create {alvo} containing the single word DELTA"},
        {"role": "assistant", "content": "Done! The task is complete."},
    ]
    v = check_completion(msgs, project_root=str(tmp_path))
    assert v.status == "UNVERIFIED", f"cego de novo: {v.status} {v.missing}"
    assert any(str(alvo) in m for m in v.missing)


def test_instrucao_lida_executada_depois_e_VERIFIED(tmp_path):
    """O caminho feliz precisa continuar VERIFIED — não regridir."""
    import json as _json
    from jarvis.core.completion import check_completion
    alvo = tmp_path / "marker.txt"
    alvo.write_text("DELTA", encoding="utf-8")
    msgs = [
        {"role": "system", "content": "agent"},
        {"role": "user", "content": "read the brief and do what it asks"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {
                "name": "read_file",
                "arguments": _json.dumps({"path": str(tmp_path / "brief.txt")})}},
            {"id": "c2", "type": "function", "function": {
                "name": "write_file",
                "arguments": _json.dumps({"path": str(alvo), "content": "DELTA"})}}]},
        {"role": "tool", "tool_call_id": "c1",
         "content": f"FINAL INSTRUCTION: create {alvo} containing the single word DELTA"},
        {"role": "tool", "tool_call_id": "c2", "content": "ok"},
        {"role": "assistant", "content": "Done."},
    ]
    v = check_completion(msgs, project_root=str(tmp_path))
    assert v.status == "VERIFIED", f"regrediu: {v.status} {v.missing}"
