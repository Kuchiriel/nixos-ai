"""Testes do vault_cipher — estilo Wycheproof (fraquezas conhecidas).

Conforme ~/Books/papers/web-wycheproof-crypto-testing.md (LOOP-v3 ciclo 1):
não basta round-trip; o contrato inclui REJEITAR (tamper, chave errada)
e não vazar plaintext no disco. Fernet = AES-128-CBC + HMAC-SHA256.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from jarvis.core import vault_cipher as vc

cryptography = pytest.importorskip("cryptography")


def _key(tmp_path: Path, name: str = "k.key") -> Path:
    p = tmp_path / name
    vc.generate_key(p)
    return p


def _enable(monkeypatch, key: Path) -> None:
    monkeypatch.setenv("JARVIS_VAULT_ENC", "1")
    monkeypatch.setenv("JARVIS_VAULT_KEY_FILE", str(key))


# --- defaults (default fraco é falha de segurança — Wycheproof) ---


def test_enabled_e_opt_in_por_default(monkeypatch):
    monkeypatch.delenv("JARVIS_VAULT_ENC", raising=False)
    assert vc.enabled() is False  # plaintext por design, documentado no módulo


def test_note_path_ganha_suffix_enc_so_quando_habilitado(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_VAULT_ENC", raising=False)
    assert vc.note_path(Path("/v"), "n.md") == Path("/v/n.md")
    _enable(monkeypatch, _key(tmp_path))
    assert vc.note_path(Path("/v"), "n.md") == Path("/v/n.md.enc")


def test_fernet_sem_chave_falha_explicitamente(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path / "inexistente.key")
    with pytest.raises(RuntimeError, match="JARVIS_VAULT_KEY_FILE"):
        vc.encrypt_text("x")


def test_generate_key_cria_0600_e_valida(tmp_path):
    p = _key(tmp_path)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    from cryptography.fernet import Fernet
    Fernet(p.read_text().strip())  # não lança = chave válida


# --- round-trip e segurança semântica (comportamento esperado) ---


def test_roundtrip_unicode_e_vazio(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    for plain in ["", "acentuação テスト 🎤 ", "a" * 5000]:
        assert vc.decrypt_text(vc.encrypt_text(plain)) == plain


def test_mesmo_plaintext_gera_tokens_distintos(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    t1, t2 = vc.encrypt_text("secreto"), vc.encrypt_text("secreto")
    assert t1 != t2  # segurança semântica: nonce fresco por token


def test_chave_errada_rejeita(monkeypatch, tmp_path):
    ka, kb = _key(tmp_path, "a.key"), _key(tmp_path, "b.key")
    _enable(monkeypatch, ka)
    token = vc.encrypt_text("secreto")
    monkeypatch.setenv("JARVIS_VAULT_KEY_FILE", str(kb))
    from cryptography.fernet import InvalidToken
    with pytest.raises(InvalidToken):
        vc.decrypt_text(token)


def test_tamper_no_token_rejeita(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    token = vc.encrypt_text("secreto")
    from cryptography.fernet import InvalidToken
    # flip num char do meio do corpo (não no padding base64)
    meio = len(token) // 2
    bad = (token[:meio] + ("A" if token[meio] != "A" else "B")
           + token[meio + 1:])
    with pytest.raises(InvalidToken):
        vc.decrypt_text(bad)


# --- nível arquivo: disco JAMAIS contém plaintext com enc on ---


def test_write_enc_nao_vaza_plaintext_no_disco(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    p = tmp_path / "v" / "nota.md"
    segredo = "SEGREDO-QUE-NAO-VA-PRO-DISCO-12345"
    vc.write_text(p, f"text {segredo} here")
    raw = p.with_name(p.name + vc.ENC_SUFFIX).read_bytes()  # contrato: .enc no disco
    assert segredo.encode() not in raw          # plaintext ausente do disco
    assert vc.read_text(p) == f"text {segredo} here"


def test_write_read_e_append_roundtrip(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    p = tmp_path / "n.md"
    vc.write_text(p, "linha1\n")
    vc.write_text(p, "linha2\n", append=True)   # reescritura whole-file recifrada
    assert vc.read_text(p) == "linha1\nlinha2\n"


def test_write_enc_0600(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    p = tmp_path / "n.md"
    vc.write_text(p, "x")
    assert stat.S_IMODE(os.stat(p.with_name(p.name + vc.ENC_SUFFIX)).st_mode) == 0o600


def test_modo_plaintext_nao_muda_comportamento(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_VAULT_ENC", raising=False)
    p = tmp_path / "n.md"
    vc.write_text(p, "claro")
    assert p.read_text(encoding="utf-8") == "claro"
    vc.write_text(p, "+", append=True)
    assert vc.read_text(p) == "claro+"


def test_read_enc_inexistente_devolve_vazio(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    assert vc.read_text(tmp_path / "nada.md") == ""


def test_iter_notes_lista_sufixo_certo(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    # caller passa nome PLAIN (sem note_path) — mecanismo garante .enc
    vc.write_text(tmp_path / "a.md", "x")
    vc.write_text(tmp_path / "b.md", "y")
    notas = vc.iter_notes(tmp_path)
    assert [n.name for n in notas] == ["b.md.enc", "a.md.enc"]
    # e o disco realmente tem .enc, não o nome plain
    assert (tmp_path / "a.md.enc").exists() and not (tmp_path / "a.md").exists()


def test_write_read_por_nome_plain_funciona_end_to_end(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    p = tmp_path / "n.md"
    vc.write_text(p, "conteúdo")
    assert vc.read_text(p) == "conteúdo"  # read auto-resolve o .enc


def test_suffix_idempotente_nao_dobra(monkeypatch, tmp_path):
    _enable(monkeypatch, _key(tmp_path))
    p = tmp_path / "n.md.enc"  # caller já aplicou o suffix (padrão dev.py)
    vc.write_text(p, "x")
    assert vc.read_text(p) == "x"
    assert not (tmp_path / "n.md.enc.enc").exists()


def test_nota_legada_em_claro_e_lida_transparente(monkeypatch, tmp_path):
    p = tmp_path / "legado.md"
    vc.write_text(p, "pré-cifragem")  # com enc OFF
    _enable(monkeypatch, _key(tmp_path))
    assert vc.read_text(p) == "pré-cifragem"  # fallback migração
