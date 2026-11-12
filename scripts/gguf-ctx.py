#!/usr/bin/env python3
"""Le o contexto REAL (treinado) dos modelos GGUF.

Por que: o `context` do registry (modules/ai/models.nix) e o limite que o
servidor USA; o GGUF carrega o limite que o MODELO foi treinado para
suportar. Divergir para cima = o servidor promete mais do que o modelo
suporta (corta/confunde); divergir para baixo = escolha de operacao
(ok, mas precisa ser visivel).

Uso:
  scripts/gguf-ctx.py                       # todos os GGUFs locais
  scripts/gguf-ctx.py ~/.models/x.gguf      # um arquivo
  scripts/gguf-ctx.py --json                # saida JSON

Exit: 0 sempre (informativo); --check sai != 0 se algum GGUF local ficar
ACIMA do limite treinado (ver script/check-ctx-drift.sh).
"""
import json
import struct
import sys
from pathlib import Path

# tipos GGUF -> tamanho/reader
_STRUCT = {
    0: ("B", 1), 1: ("b", 1), 2: ("H", 2), 3: ("h", 2), 4: ("I", 4),
    5: ("i", 4), 6: ("f", 4), 7: ("?", 1), 10: ("Q", 8), 11: ("q", 8),
    12: ("d", 8),
}


def _read(f, n):
    b = f.read(n)
    if len(b) != n:
        raise EOFError("fim do arquivo")
    return b


def _string(f):
    (ln,) = struct.unpack("<Q", _read(f, 8))
    return _read(f, ln).decode("utf-8", "replace")


def _value(f, t):
    if t == 8:
        return _string(f)
    if t == 9:  # array
        et, = struct.unpack("<I", _read(f, 4))
        (cnt,) = struct.unpack("<Q", _read(f, 8))
        if et == 8:
            return [_string(f) for _ in range(cnt)]
        fmt, size = _STRUCT[et]
        return [struct.unpack("<" + fmt, _read(f, size))[0]
                for _ in range(cnt)]
    fmt, size = _STRUCT[t]
    return struct.unpack("<" + fmt, _read(f, size))[0]


def read_meta(path):
    with open(path, "rb") as f:
        if _read(f, 4) != b"GGUF":
            raise ValueError("nao e um GGUF")
        ver, = struct.unpack("<I", _read(f, 4))
        n_tensors, = struct.unpack("<Q", _read(f, 8))
        n_kv, = struct.unpack("<Q", _read(f, 8))
        meta = {}
        for _ in range(n_kv):
            key = _string(f)
            t, = struct.unpack("<I", _read(f, 4))
            meta[key] = _value(f, t)
    return ver, n_tensors, meta


def trained_ctx(meta):
    """Contexto treinado: <arch>.context_length ou general.context_length."""
    cands = {}
    for k, v in meta.items():
        if k.endswith(".context_length") and isinstance(v, int):
            cands[k] = v
        if k == "general.context_length" and isinstance(v, int):
            cands[k] = v
    if not cands:
        return None, {}
    # sem arquitetura: o primeiro
    return max(cands.values()), cands


def gguf_root():
    roots = [Path("/var/lib/ai/models"), Path.home() / "models", Path("/home/nixos/models")]
    for r in roots:
        if r.is_dir():
            return r
    return None


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    paths = []
    if args:
        paths = [Path(a) for a in args]
    else:
        root = gguf_root()
        if root:
            paths = sorted(root.glob("**/*.gguf"))
    out = []
    for p in paths:
        if not p.exists():
            continue
        try:
            ver, nt, meta = read_meta(p)
            ctx, cands = trained_ctx(meta)
        except Exception as e:
            out.append({"path": str(p), "error": str(e)})
            continue
        out.append({
            "path": str(p),
            "size_gb": round(p.stat().st_size / 2**30, 2),
            "arch": meta.get("general.architecture", "?"),
            "trained_context": ctx,
            "context_keys": cands,
            "name": meta.get("general.name", "?"),
        })
    if as_json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    if not out:
        print("nenhum GGUF encontrado")
        return 0
    print(f"{'ctx_treinado':>13}  {'GB':>6}  arch            arquivo")
    for o in out:
        if "error" in o:
            print(f"{'ERRO':>13}  {'':>6}  {o['error'][:40]:<14}  {o['path']}")
            continue
        ctx = o["trained_context"]
        print(f"{str(ctx):>13}  {o['size_gb']:>6}  {o['arch']:<14}  "
              f"{Path(o['path']).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
