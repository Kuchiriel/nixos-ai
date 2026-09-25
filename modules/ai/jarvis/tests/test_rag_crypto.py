"""Testes do rag_crypto — estilo Wycheproof (fraquezas conhecidas).

Conforme ~/Books/papers/web-wycheproof-crypto-testing.md (LOOP-v3 ciclo 1):
o contrato do payload cifrado em repouso inclui (1) só cifrar os campos
sensíveis, (2) prefixo `enc:` visível (dump do Qdrant não entrega texto),
(3) migração segura (mistura claro+cifrado decripta), (4) idempotência
(não cifrar 2×), (5) chave errada degrada SEM exceção e SEM entregar texto.
"""
from __future__ import annotations

import pytest

from jarvis.core import rag_crypto as rc

cryptography = pytest.importorskip("cryptography")


@pytest.fixture
def enabled(tmp_path, monkeypatch):
    from jarvis.core import vault_cipher as vc
    key = tmp_path / "k.key"
    vc.generate_key(key)
    monkeypatch.setenv("JARVIS_VAULT_ENC", "1")
    monkeypatch.setenv("JARVIS_VAULT_KEY_FILE", str(key))
    return key


def test_sem_env_falha_explicitamente(monkeypatch):
    monkeypatch.delenv("JARVIS_VAULT_ENC", raising=False)
    with pytest.raises(RuntimeError, match="JARVIS_VAULT_ENC"):
        rc.encrypt_payload({"content": "x"})


def test_cifra_so_campos_sensiveis_e_mantem_o_resto(enabled):
    payload = {"content": "texto secreto", "ext": ".md", "score": 0.42,
               "tags": ["a", "b"], "path": "/docs/x.md", "n": 7}
    out = rc.encrypt_payload(payload)
    assert out["content"].startswith("enc:") and out["content"] != "texto secreto"
    assert out["path"].startswith("enc:")
    assert out["ext"] == ".md"           # ext fica claro: filtro híbrido consulta
    assert out["score"] == 0.42          # não-str intocado
    assert out["tags"] == ["a", "b"]
    assert out["n"] == 7
    assert rc.decrypt_payload(out) == payload  # round-trip completo


def test_dump_de_storage_nao_entrega_texto(enabled):
    """O cenário real da docstring: dump do Qdrant não revela conteúdo."""
    out = rc.encrypt_payload({"content": "PLANO-SECRETO-XYZ",
                              "text": "corpo secreto"})
    blob = repr(out).encode()
    assert b"PLANO-SECRETO-XYZ" not in blob and b"corpo secreto" not in blob


def test_idempotente_nao_cifra_duas_vezes(enabled):
    once = rc.encrypt_payload({"content": "abc"})
    twice = rc.encrypt_payload(once)
    assert once == twice  # prefixo enc: já marca como cifrado


def test_migracao_mistura_claro_e_cifrado(enabled):
    """Coleção antiga tem pontos claros; novos chegam cifrados — ambos decriptam."""
    plain = {"content": "legado claro", "ext": ".md"}
    enc = rc.encrypt_payload({"content": "novo secreto", "ext": ".md"})
    assert rc.decrypt_payload(plain) == plain
    assert rc.decrypt_payload(enc)["content"] == "novo secreto"


def test_chave_errada_degrada_sem_excecao_e_sem_vazar(tmp_path, monkeypatch):
    from jarvis.core import vault_cipher as vc
    ka = tmp_path / "a.key"; vc.generate_key(ka)
    kb = tmp_path / "b.key"; vc.generate_key(kb)
    monkeypatch.setenv("JARVIS_VAULT_ENC", "1")
    monkeypatch.setenv("JARVIS_VAULT_KEY_FILE", str(ka))
    out = rc.encrypt_payload({"content": "SEGREDO-NUNCA-VAZAR"})
    monkeypatch.setenv("JARVIS_VAULT_KEY_FILE", str(kb))
    dec = rc.decrypt_payload(out)   # não lança: recall continua de pé
    assert dec["content"] == "[payload cifrado: chave ausente/errada]"
    assert "SEGREDO-NUNCA-VAZAR" not in dec["content"]


def test_tamper_no_valor_cifrado_degrada_sem_vazar(enabled):
    out = rc.encrypt_payload({"content": "secreto"})
    v = out["content"]
    meio = len(v) // 2
    out["content"] = v[:meio] + ("A" if v[meio] != "A" else "B") + v[meio + 1:]
    dec = rc.decrypt_payload(out)   # InvalidToken → placeholder, sem exceção
    assert dec["content"] == "[payload cifrado: chave ausente/errada]"
