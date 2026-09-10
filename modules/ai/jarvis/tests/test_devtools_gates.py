"""Permission gates: escrita nunca toca protegidos; leitura continua ok."""

from __future__ import annotations


def test_write_env_denied(tmp_path):
    from jarvis.core.devtools import write_file
    from jarvis.core.paths import use_project_root
    with use_project_root(tmp_path):
        out = write_file(".env", "X=1")
    assert out["ok"] is False
    assert "Protected" in out["error"]
    assert not (tmp_path / ".env").exists()


def test_write_secret_key_denied(tmp_path):
    from jarvis.core.devtools import write_file, str_replace
    from jarvis.core.paths import use_project_root
    (tmp_path / "a.txt").write_text("oi")
    with use_project_root(tmp_path):
        assert write_file("id_rsa.key", "x")["ok"] is False
        assert write_file("api_secret.txt", "x")["ok"] is False
        r = str_replace("a.txt", "oi", "ola")
        assert r["ok"] is True  # não-protegido continua


def test_read_env_still_allowed(tmp_path):
    from jarvis.core.devtools import read_file
    from jarvis.core.paths import use_project_root
    (tmp_path / ".env").write_text("X=1\n")
    with use_project_root(tmp_path):
        out = read_file(".env")
    assert out["ok"] is True
