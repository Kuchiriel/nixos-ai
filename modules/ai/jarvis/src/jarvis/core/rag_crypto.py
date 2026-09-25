"""Cifragem do payload do RAG em coleções protegidas (24/09).

O que protege: o TEXTO e o PATH dos pontos ficam cifrados em repouso no
Qdrant. Sem a chave do space, um dump do storage/collections não entrega
conteúdo — só vetores (que não dão o texto de volta) e metadados inertes.

O que NÃO é cifrado (e por quê):
  - `ext`: o filtro híbrido (`ext_filter`) consulta esse campo no Qdrant;
    cifrá-lo quebraria a busca por tipo de arquivo. Só revela ".md"/".py".
  - o vetor: é computado localmente do texto claro; sem o texto, o vetor
    não reconstrói o documento.

Modelo: mesma chave Fernet do vault do space (JARVIS_VAULT_KEY_FILE).
Prefixo `enc:` marca o valor cifrado → permite migrar coleções antigas
(mistura de claro e cifrado é lida pelos dois caminhos).
"""
from __future__ import annotations

import os
from typing import Any

# Campos considered sensíveis (cifrados). `ext` fora de propósito.
SENSITIVE_FIELDS = ("content", "text", "path", "summary", "snippet",
                    "chunk", "document", "title")
PREFIX = "enc:"


def _fernet():
    from cryptography.fernet import Fernet

    key_file = os.environ.get("JARVIS_VAULT_KEY_FILE", "").strip()
    if not key_file or os.environ.get("JARVIS_VAULT_ENC", "0") != "1":
        raise RuntimeError(
            "RAG cifrado exige JARVIS_VAULT_ENC=1 e JARVIS_VAULT_KEY_FILE")
    with open(os.path.expanduser(key_file), encoding="utf-8") as fh:
        return Fernet(fh.read().strip().encode())


def _enc_str(value: str) -> str:
    if not isinstance(value, str) or value.startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode()


def _dec_str(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode("utf-8")
    except InvalidToken:
        return "[payload cifrado: chave ausente/errada]"


def encrypt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for k in SENSITIVE_FIELDS:
        if k in out and isinstance(out[k], str):
            out[k] = _enc_str(out[k])
    return out


def decrypt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for k in SENSITIVE_FIELDS:
        if k in out and isinstance(out[k], str):
            out[k] = _dec_str(out[k])
    return out
