#!/usr/bin/env python3
"""Download com resume + retry + verificação de tamanho (stdlib only).

Para links instáveis (ex.: HF a ~100 B/s com quedas): retoma de onde
parou via Range, N tentativas com backoff, valida bytes finais.
Uso: python3 fetch-resume.py URL DESTINO [--tries 50]
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request

CHUNK = 1024 * 256


def remote_size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ln = r.headers.get("Content-Length")
            return int(ln) if ln else None
    except Exception:
        return None


def main() -> int:
    url, dest = sys.argv[1], sys.argv[2]
    tries = int(sys.argv[4]) if len(sys.argv) > 4 else 50
    total = remote_size(url)
    print(f"total remoto: {total or '?'} bytes", flush=True)
    for attempt in range(1, tries + 1):
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
        if total and have >= total:
            print(f"OK completo: {have} bytes")
            return 0
        req = urllib.request.Request(url)
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                partial = r.status == 206
                mode = "ab" if partial and have else "wb"
                if not partial and have:
                    print("servidor ignorou Range — recomeçando do zero")
                    have = 0
                with open(dest, mode) as f:
                    while True:
                        buf = r.read(CHUNK)
                        if not buf:
                            break
                        f.write(buf)
                        have += len(buf)
            print(f"tentativa {attempt}: {have}/{total or '?'} bytes", flush=True)
        except Exception as e:
            print(f"tentativa {attempt} falhou ({e}); retry em 10s", flush=True)
            time.sleep(10)
    have = os.path.getsize(dest) if os.path.exists(dest) else 0
    if total and have >= total:
        print(f"OK completo: {have} bytes")
        return 0
    print(f"INCOMPLETO: {have}/{total or '?'}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
