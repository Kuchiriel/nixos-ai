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
import hashlib
import json
import os
import subprocess
import sys
import re
import urllib.error
import urllib.request
from pathlib import Path

# ── configuração centralizada ───────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_config import cfg as _agent_cfg  # noqa: E402

DEFAULT_URL = os.environ.get("AGENTS_OC_URL", _agent_cfg().env("AGENTS_OC_URL"))
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


# (19/11, medido) A FONTE DA VERDADE DO ENDERECO EO O PROPRIO SOCKET.
# `home-manager/modules/services/opencode-serve.nix` sobe o serve com
# `--hostname ${TAILNET_HOST} --port 4599` (escuta SO no IP do tailnet), mas o
# agent-config.json declara http://127.0.0.1:4599. Resultado medido: TODA
# entrega por API da frota morria com `URLError: [Errno 111] Connection
# refused` enquanto o bus (outro caminho) funcionava — a frota parecia viva e
# as mensagens nao chegavam. Aqui o base declarado e tentado primeiro e, se o
# TCP recusar, usa-se o listener REAL da mesma porta lido em `ss -ltnH`.
def _candidate_bases(base: str) -> list[str]:
    cands = [base]
    m = re.match(r"^([a-zA-Z][\w+.-]*://)([^:/]+)(:\d+)?$", base.strip())
    if not m:
        return cands
    scheme, port = m.group(1), m.group(3) or ""
    try:
        txt = subprocess.run(["ss", "-ltnH"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:
        return cands
    for line in txt.splitlines():
        cols = line.split()
        if len(cols) < 4 or not cols[3].endswith(port):
            continue
        local = cols[3]
        if local.startswith(("127.", "::1", "[::1]")):
            continue
        ip = local[:-len(port)].strip("[]") if port else local.rsplit(":", 1)[0]
        if not ip:
            continue
        cand = f"{scheme}{ip}{port}"
        if cand not in cands:
            cands.append(cand)
    return cands


def _routes(base: str, session: str, text: str, note: bool):
    # V2: queue = nota (não acorda), steer = pedido/ação (acorda execução)
    delivery = "queue" if note else "steer"
    novo = {"text": text, "delivery": delivery}
    return (
        (f"{base}/api/session/{session}/prompt", novo),
        # 2.x sem o prefixo (alguns builds) e 1.x com {parts, noReply}
        (f"{base}/session/{session}/prompt", novo),
        (f"{base}/session/{session}/message",
         {"parts": [{"type": "text", "text": text}], "noReply": bool(note)}),
        (f"{base}/session/{session}/prompt_async", {"text": text}),
    )



def _enqueue_direct_msg(session: str, text: str) -> None:
    """Fallback: grava msg direta para o plugin memory.js injetar via synthetic() no idle."""
    import time as _t
    state = Path.home() / ".local/state/jarvis"
    state.mkdir(parents=True, exist_ok=True)
    f = state / "direct-msg.jsonl"
    # dedupe simples por session+hash
    key = hashlib.sha256((session + "\n" + text).encode("utf-8", "ignore")).hexdigest()[:16]
    try:
        if f.exists():
            tail = f.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]
            if any(key in ln for ln in tail):
                return
    except Exception:
        pass
    from_name = os.environ.get("JARVIS_AGENT_NAME") or os.environ.get("AGENT_NAME") or "agent"
    model = os.environ.get("OPENCODE_MODEL") or os.environ.get("AGENT_MODEL") or ""
    if not model:
        try:
            ocid = subprocess.run(["bash","-lc","command -v oc-identidade >/dev/null 2>&1 && oc-identidade --json || true"],
                                  capture_output=True,text=True,timeout=5).stdout.strip()
            if ocid.startswith("{"):
                model = str(json.loads(ocid).get("model") or "")
        except Exception:
            pass
    entry = {
        "id": f"dm-{int(_t.time())}-{key[:8]}",
        "to": session, "from": from_name, "model": model,
        "kind": "ask", "text": text[:4000], "ts": int(_t.time()),
        "dedupe": key,
    }
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
def _promote_inbox_steer(base: str, session: str, timeout: int = 10) -> str:
    """Best-effort: promove itens queued no inbox para steer (bug V2 conhecido)."""
    promoted = 0
    for b in _candidate_bases(base):
        try:
            req = urllib.request.Request(
                f"{b}/api/session/{session}/inbox",
                headers={"Authorization": _auth_header()},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                items = json.loads(r.read().decode("utf-8", "ignore") or "[]")
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                if str(it.get("delivery") or "").lower() != "queue":
                    continue
                iid = it.get("id") or it.get("inboxID") or it.get("inbox_id")
                if not iid:
                    continue
                body = json.dumps({"delivery": "steer"}).encode()
                preq = urllib.request.Request(
                    f"{b}/api/session/{session}/inbox/{iid}",
                    data=body, method="PATCH",
                    headers={"Content-Type": "application/json", "Authorization": _auth_header()},
                )
                try:
                    with urllib.request.urlopen(preq, timeout=timeout) as pr:
                        if pr.status < 400:
                            promoted += 1
                except Exception:
                    pass
            if promoted:
                return f"promoted={promoted}"
        except Exception:
            continue
    return f"promoted={promoted}"


# (09/11, sweep-2026-11) DEDUPE NA ENTREGA: o loop medido na casa vinha
# daqui. Uma nota repetida entra na INBOX da sessao (delivery=queue) e o
# opencode processa a fila num turno novo: medido, 10 confirmacoes
# identicas ocuparam um turno inteiro cada. O dedupe no watcher nao
# resolvia, porque o caminho do acorda nao e o poll dele e sim a fila da
# sessao. Aqui a entrega repetida nem chega na fila.
_STATE_DIR = Path(os.environ.get("AGENTS_DELIVER_STATE",
                                "/tmp/opencode/agents-watcher"))


_BOILERPLATE = re.compile(
    r"^\s*(recebido( e conferido)?|confirmado|conferido|ok|feito|obrigado|"
    r"blz|thanks?|\W+)\s*[:,\.]?\s*", re.I)


def _dedupe_key(text: str) -> str:
    """Chave do texto: o CONTEUDO, sem o boilerplate de confirmacao.

    O mesmo aviso chega com variacoes ("ha 3 dias" ou nao) e as vezes com
    prefijos diferentes ("Recebido e conferido:" / "Confirmado:"), entao a
    chave tira o prefixo de cortesia e usa os 80 primeiros caracteres do
    que sobrou. Duas mensagens de conteudo diferente divergem antes disso.
    """
    t = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    t = _BOILERPLATE.sub("", t, count=1)
    return t


def _dedupe_path(base: str, session: str) -> Path:
    tag = hashlib.sha1(f"{base}|{session}".encode()).hexdigest()[:16]
    return _STATE_DIR / f"delivered.{tag}.txt"


def _already_delivered(path: Path, key: str, *, ratio: float = 0.72) -> bool:
    """A nota ja foi entregue?

    O texto exato nao basta: o mesmo aviso chega com variacoes ("ha 3
    dias" ou nao, "conforme o README" ou "conforme o checkpoint"), e cada
    variacao hashava diferente, entao o loop continuava. Aqui a comparacao
    e por SIMILARIDADE (difflib) contra as ultimas entregas do alvo, o que
    pega variacao de insercao e de reordenacao sem confundir duas
    mensagens de conteudo diferente.
    """
    try:
        if not path.exists():
            return False
        entregues = [l.strip() for l in
                     path.read_text(errors="ignore").splitlines() if l.strip()]
    except Exception:
        return False
    if key in entregues:
        return True
    # A similaridade so vale para texto LONGO: com texto curto, duas notas
    # distintas com a mesma forma ("probe 123" e "probe 456") passam de 0,72
    # de similaridade e uma seria jogada fora em silencio (medido 09/11: dois probes de 25 chars caem juntos).
    if len(key) < 120:
        return False
    import difflib
    for d in entregues[-20:]:
        if len(d) < 120:
            continue
        if difflib.SequenceMatcher(None, key, d).ratio() >= ratio:
            return True
    return False


def _mark_delivered(path: Path, key: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", errors="ignore") as f:
            f.write(key + "\n")
    except Exception:
        pass


def _log_guard(session: str, termos: str, text: str) -> None:
    """Auditoria do bloqueio: quem tentou contaminar, o que mandou."""
    try:
        p = Path.home() / ".local/state/opencode/redteam-guard.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        import time as _t
        with p.open("a", errors="ignore") as f:
            f.write(f"{_t.strftime('%Y-%m-%dT%H:%M:%S')} sessao={session} "
                    f"termos={termos} texto={text[:300]!r}\n")
    except Exception:
        pass


def deliver(base: str, session: str, text: str, *, note: bool = False,
            timeout: int = 25, force: bool = False) -> tuple[int, str]:
    """Entrega o texto. Retorna (status, corpo). Levanta RuntimeError.

    GUARD DE INTRUSAO (12/11): antes de enfileirar, o texto passa pelo
    agent-guard.py (vocabulario `guard` do estado do plugin red-team). Um
    modelo intrusivo (o inkling) que manda mensagem manipulative para
    contaminar outro agente NAO entra na inbox dele: volta 451 com os
    termos casados. `force=True` ignora (o dono, ou quem esta depurando).
    """
    if not force:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from agent_guard import marca_do_marcado, scan as _guard_scan  # noqa: PLC0415
            _r = _guard_scan(text)
            if _r["verdict"] == "bloqueado":
                _termos = ", ".join(h["termo"] for h in _r["hits"])
                _log_guard(session, _termos, text)
                return 451, (f"guard: mensagem BLOQUEADA (termo de intrusao: "
                             f"{_termos}). Use --force para entregar mesmo assim.")
            if _r["verdict"] == "marcado":
                # Classe moralista: a entrega passa, mas com aviso (a discussao
                # legitima sobre etica no bus nao pode ser barrada).
                _tipos = ", ".join(sorted({p["tipo"] for p in _r["padroes"]}))
                _log_guard(session, f"marcado: {_tipos}", text)
                text = marca_do_marcado(_r) + text
        except ImportError:
            pass  # sem o guard: entrega normal (fail-open, nao derruba a fleet)
        except Exception:
            pass
    # 2.2.6: rota nova (precisa do /api). O enum de delivery e
    # {steer, queue}: NAO existe "nota sem rodar" no 2.x (o 1.x tinha
    # noReply=true). Uma "nota" no 2.x = queue (a mensagem fica na inbox
    # e o agente a ve no proximo turno) — entrego assim, com o aviso.
    # dedupe: nao enfileira o que ja foi entregue (o turno do agente e o preco)
    _dpath = _dedupe_path(base, session)
    _dkey = _dedupe_key(text)
    if _already_delivered(_dpath, _dkey):
        return 208, ("dedupe: texto ja entregue a esta sessao, nao reenfileirado")
    bases = _candidate_bases(base)
    last_err = "rotas ausentes"
    for b in bases:
        for url, payload in _routes(b, session, text, note):
            try:
                st, out = _post(url, payload, timeout=timeout)
                _mark_delivered(_dpath, _dkey)
                if not note and "/api/session/" in url and "/prompt" in url:
                    try:
                        promo = _promote_inbox_steer(base, session, timeout=min(10, timeout))
                        if promo and promo != "promoted=0":
                            out = f"{out} | {promo}"
                    except Exception:
                        pass
                # fallback: enqueue for plugin synthetic injection on idle
                if not note:
                    try:
                        _enqueue_direct_msg(session, text)
                    except Exception:
                        pass
                return st, out
            except urllib.error.HTTPError as e:
                body = (e.read() or b"")[:200].decode(errors="replace")
                if e.code in (404, 405, 501):
                    continue  # rota nao existe nesta versao → tenta a proxima
                raise RuntimeError(f"HTTP {e.code} {body}") from e
            except Exception as e:  # noqa: BLE001
                # transporte falhou neste endereco (ex.: TCP recusado no
                # 127.0.0.1 enquanto o serve escuta no IP do tailnet): tenta
                # o proximo candidato antes de desistir.
                last_err = f"{type(e).__name__}: {e}"
                break
        else:
            continue  # todas as rotas deste base responderam 404/405/501
    raise RuntimeError(
        f"nenhuma rota de entrega respondeu (bases tentados: "
        f"{', '.join(bases)}; ultimo erro: {last_err})")


def abort(base: str, session: str, timeout: int = 15) -> tuple[int, str]:
    last_err = "-"
    for b in _candidate_bases(base):
        for url in (f"{b}/session/{session}/abort",
                    f"{b}/api/session/{session}/abort"):
            try:
                st, out = _post(url, {}, timeout=timeout)
                return st, out
            except urllib.error.HTTPError as e:
                if e.code in (404, 405, 501):
                    continue
                raise RuntimeError(f"HTTP {e.code}") from e
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                break
        else:
            continue
    raise RuntimeError(f"rota de abort nao encontrada ({last_err})")


def live_db_path() -> str:
    """Caminho do banco SQLite que o opencode VIVO tem aberto.

    Medido 08/11 (por fd de /proc, nas duas versoes): a 1.18.34 E a 2.2.6
    usam `~/.local/share/opencode/opencode.db`. O `opencode-stable.db`
    (6.4 GB) e lixo de ~27 dias e NAO e o store vivo — o fallback antigo
    ("maior *.db") escolhia justamente ele e fazia o watcher achar que todo
    agente estava ocioso (e acordar a frota o tempo todo).
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
    # fallback: o store canonico primeiro; so entao o maior *.db
    base = Path.home() / ".local/share/opencode"
    canon = base / "opencode.db"
    if canon.exists():
        return str(canon)
    cands = sorted(base.glob("opencode*.db"), key=lambda p: p.stat().st_size,
                   reverse=True)
    return str(cands[0]) if cands else str(canon)


def main() -> int:
    ap = argparse.ArgumentParser(description="entrega de mensagem no opencode")
    ap.add_argument("--session", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--note", action="store_true", help="nota: o agente NAO roda")
    ap.add_argument("--ask", action="store_true", help="pedido: o agente roda")
    ap.add_argument("--abort", action="store_true")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--db-path", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="ignora o guard de intrusao (so o dono/depuracao)")
    ap.add_argument("--guard", action="store_true",
                    help="so checa o texto contra o vocabulario de intrusao")
    ns = ap.parse_args()
    if ns.db_path:
        print(live_db_path())
        return 0
    if ns.guard:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from agent_guard import scan as _scan
        r = _scan(ns.text)
        if r["clean"]:
            print("limpo: nenhum termo de intrusao")
            return 0
        print(f"MARCADO: {len(r['hits'])} termo(s): "
              + ", ".join(h["termo"] for h in r["hits"]))
        return 1
    if not ns.session:
        print("ERRO: --session obrigatorio", file=sys.stderr)
        return 2
    try:
        if ns.abort:
            st, out = abort(ns.url, ns.session)
        else:
            st, out = deliver(ns.url, ns.session, ns.text, note=ns.note,
                               force=ns.force)
    except RuntimeError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    print(f"{st} {out}")
    return 0 if st < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
