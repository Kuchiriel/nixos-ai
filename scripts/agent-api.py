#!/usr/bin/env python3
"""Entrega mensagens numa sessao do opencode — QUALQUER versao da API.

Por que: o servidor `opencode serve` pode ser o 1.18.34 (rotas 1.x:
`/session/:id/message`, `/session/:id/prompt_async`) ou o 2.2.6 (rota nova:
`/api/session/:id/prompt` com `{"text":…,"delivery":…}`). A frota silenciou
por ~5 h em 07/11 porque as rotas 1.x devolvem **405** no 2.2.6 e a rota
nova precisa do prefixo `/api` (sem ele o POST cai no catch-all da SPA e
devolve HTML 200).

Fala: o opencode roda em Duas linguas diferentes e o dono perde mensagens
sem nenhum erro visivel. Duas regras seguiram do episodio:
  1. o `serve` tem que ser o MESMO binario do TUI (o dono usa o do PATH);
  2. a entrega tenta as rotas em ordem e cai para a antiga se a nova nao
     existir (404/405/501) — nunca depende da versao.

Uso:
  scripts/agent-api.py --session <id> --text "..." [--note|--ask]
  scripts/agent-api.py --session <id> --text "..." --abort
  scripts/agent-api.py --db-path        # caminho do banco do opencode vivo
Exit: 0 = entregue; 1 = falhou (a mensagem diz o HTTP e o corpo).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = os.environ.get("AGENTS_OC_URL", "http://100.121.100.103:4599")
ENVFILE = os.environ.get(
    "AGENTS_OC_ENVFILE", str(Path.home() / ".config/opencode/server.env"))


def _auth() -> tuple[str, str]:
    user = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    pw = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not pw:
        try:
            for raw in Path(ENVFILE).read_text().splitlines():
                if raw.startswith("OPENCODE_SERVER_PASSWORD="):
                    pw = raw.split("=", 1)[1].strip().strip("\"'")
                    break
        except OSError:
            pass
    return user, pw


def _headers() -> dict[str, str]:
    user, pw = _auth()
    return {
        "Content-Type": "application/json",
        "Authorization": "Basic " +
        base64.b64encode(f"{user}:{pw}".encode()).decode(),
    }


def _post(url: str, payload: dict, timeout: int = 25):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 method="POST", headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()[:300].decode(errors="replace")


def deliver(base: str, session: str, text: str, *, note: bool = False,
            timeout: int = 25) -> tuple[int, str]:
    """Entrega o texto. Retorna (status, corpo). Levanta RuntimeError."""
    # 2.2.6: rota nova (precisa do /api). O enum de delivery e
    # {steer, queue}: NAO existe "nota sem rodar" no 2.x (o 1.x tinha
    # noReply=true). Uma "nota" no 2.x = queue (a mensagem fica na inbox
    # e o agente a ve no proximo turno) — entrego assim, com o aviso.
    novo = {"text": text, "delivery": "queue"}
    for url, payload in (
        (f"{base}/api/session/{session}/prompt", novo),
        # 2.x sem o prefixo (alguns builds) e 1.x com {parts, noReply}
        (f"{base}/session/{session}/prompt", novo),
        (f"{base}/session/{session}/message",
         {"parts": [{"type": "text", "text": text}], "noReply": bool(note)}),
        (f"{base}/session/{session}/prompt_async", {"text": text}),
    ):
        try:
            st, out = _post(url, payload, timeout=timeout)
            return st, out
        except urllib.error.HTTPError as e:
            body = (e.read() or b"")[:200].decode(errors="replace")
            if e.code in (404, 405, 501):
                continue  # rota nao existe nesta versao → tenta a proxima
            raise RuntimeError(f"HTTP {e.code} {body}") from e
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{type(e).__name__}: {e}") from e
    raise RuntimeError("nenhuma rota de entrega respondeu (404/405 em todas)")


def abort(base: str, session: str, timeout: int = 15) -> tuple[int, str]:
    for url in (f"{base}/session/{session}/abort", f"{base}/api/session/{session}/abort"):
        try:
            st, out = _post(url, {}, timeout=timeout)
            return st, out
        except urllib.error.HTTPError as e:
            if e.code in (404, 405, 501):
                continue
            raise RuntimeError(f"HTTP {e.code}") from e
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(str(e)) from e
    raise RuntimeError("rota de abort nao encontrada")


def live_db_path() -> str:
    """Caminho do banco SQLite que o opencode VIVO tem aberto.

    Medido 07/11: a 1.18.34 usa `opencode.db` e a 2.2.6 usa
    `opencode-stable.db` — ler o arquivo errado faz o watcher achar que
    todo agente esta ocioso (e acorda a fleet o tempo todo).
    """
    import glob
    for pid_dir in glob.glob("/proc/[0-9]*"):
        pid = Path(pid_dir).name
        try:
            cmd = (Path(pid_dir) / "cmdline").read_bytes().decode(errors="replace")
        except OSError:
            continue
        if "opencode" not in cmd or "serve" not in cmd:
            continue
        try:
            for fd in (Path(pid_dir) / "fd").iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                if target.endswith(".db") and "opencode" in target:
                    return target
        except OSError:
            continue
    # fallback: o maior *.db no data dir
    base = Path.home() / ".local/share/opencode"
    cands = sorted(base.glob("opencode*.db"), key=lambda p: p.stat().st_size,
                   reverse=True)
    return str(cands[0]) if cands else str(base / "opencode.db")


def main() -> int:
    ap = argparse.ArgumentParser(description="entrega de mensagem no opencode")
    ap.add_argument("--session", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--note", action="store_true", help="nota: o agente NAO roda")
    ap.add_argument("--ask", action="store_true", help="pedido: o agente roda")
    ap.add_argument("--abort", action="store_true")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--db-path", action="store_true")
    ns = ap.parse_args()
    if ns.db_path:
        print(live_db_path())
        return 0
    if not ns.session:
        print("ERRO: --session obrigatorio", file=sys.stderr)
        return 2
    try:
        if ns.abort:
            st, out = abort(ns.url, ns.session)
        else:
            st, out = deliver(ns.url, ns.session, ns.text, note=ns.note)
    except RuntimeError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    print(f"{st} {out}")
    return 0 if st < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
