"""Cifragem opt-at-rest do vault (24/09, perfil isolado Qwen 4B).

Por que: o dono pediu uma sessão RAG/memória/vault SEPARADA e CRIPTOGRAFADA
para rodar um modelo local sem filtro. Isolamento por state_dir/collections
não basta: o conteúdo no disco fica legível por qualquer processo do usuário.
Aqui o vault inteiro (e cada nota) é cifrado com Fernet (AES-128-CBC + HMAC,
autenticado) usando chave em arquivo fora do estado — padrão da casa
(/etc/jarvis-secrets/*, 640 root:nixos).

Opt-in por env (o vault PRINCIPAL fica em texto puro, sem mudança de
comportamento):
  JARVIS_VAULT_ENC=1            liga a cifragem
  JARVIS_VAULT_KEY_FILE=<path>  chave Fernet (gerar com `vault-keygen`)

Nomes de arquivo mudam: `nota.md` → `nota.md.enc` quando cifrado.
"""
from __future__ import annotations

import os
from pathlib import Path

ENC_SUFFIX = ".enc"


def enabled() -> bool:
    return os.environ.get("JARVIS_VAULT_ENC", "0") == "1"


def key_path() -> Path | None:
    raw = os.environ.get("JARVIS_VAULT_KEY_FILE", "").strip()
    return Path(raw).expanduser() if raw else None


def _fernet():
    from cryptography.fernet import Fernet

    kp = key_path()
    if kp is None or not kp.exists():
        raise RuntimeError(
            "JARVIS_VAULT_ENC=1 mas JARVIS_VAULT_KEY_FILE ausente/inválido: "
            f"{kp}")
    return Fernet(kp.read_text(encoding="utf-8").strip().encode())


def generate_key(dest: str | Path) -> str:
    """Gera uma chave Fernet e escreve com 0600. Devolve a chave (1×)."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    p = Path(dest).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(key)
    os.chmod(p, 0o600)
    return key.decode()


def note_path(base: Path, name: str) -> Path:
    """`.md` em texto puro; `.md.enc` quando cifrado."""
    p = base / name
    return p.with_name(p.name + ENC_SUFFIX) if enabled() else p


def _enc_path(path: Path) -> Path:
    """Com cifragem on, garante suffix `.enc` (idempotente: nunca dobra).

    (25/09, LOOP-v3 ciclo 1 — armadilha achada por teste Wycheproof-style:
    write_text cifrado gravava no path que o caller desse; se o caller
    esquecesse note_path(), a nota ficava INVISÍVEL para iter_notes para
    sempre. Agora o mecanismo garante o suffix, não a disciplina do caller.)
    """
    if enabled() and not path.name.endswith(ENC_SUFFIX):
        return path.with_name(path.name + ENC_SUFFIX)
    return path


def write_text(path: Path, content: str, *, append: bool = False) -> None:
    """Escreve (ou anexa) cifrando quando habilitado.

    Append exige reescritura do arquivo inteiro: o conteúdo antigo é
    decifrado, o novo é concatenado e o arquivo é recifado. Vaults são
    pequenos (notas mensais), o custo é irrelevante.
    """
    if not enabled():
        if append:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(content)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return

    existing = ""
    path = _enc_path(path)
    if append and path.exists():
        existing = read_text(path)
    f = _fernet()
    token = f.encrypt((existing + content).encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(token)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def read_text(path: Path) -> str:
    if not enabled():
        return path.read_text(encoding="utf-8", errors="replace")
    enc = _enc_path(path)
    if not enc.exists():
        # Nota legada pré-cifragem ainda em claro: lê transparente
        # (mesma filosofia de migração do rag_crypto — mistura de claro
        # e cifrado é lida pelos dois caminhos). Se nenhum dos dois
        # existe, contrato anterior: string vazia.
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return _fernet().decrypt(enc.read_bytes()).decode("utf-8")


def encrypt_text(plain: str) -> str:
    """Cifra um texto solto (uso: detalhe de log JSONL, linha a linha)."""
    return _fernet().encrypt(plain.encode("utf-8")).decode()


def decrypt_text(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode("utf-8")


def iter_notes(base: Path) -> list[Path]:
    """Lista as notas, decifradas (nomes sem .enc)."""
    if not base.exists():
        return []
    if enabled():
        return sorted(base.glob(f"*.md{ENC_SUFFIX}"), reverse=True)
    return sorted(base.glob("*.md"), reverse=True)
