#!/usr/bin/env python3
"""agent-model — troca o modelo de um agente em runtime e cai no proximo
provider quando o atual leva rate-limit (429/timeout).

POR QUE (14/11, crouton-alpha): o dono autorizou ("pode mudar o /model
deles se quiser") e o pedido noturno foi: se der rate limit, mudar de
modelo e seguir. O que existe na casa:
  - team.available_models(): lista cooldown-aware (o guard de provider
    escreve ~/.local/state/jarvis/provider-cooldown.json);
  - a API do opencode: o PATCH /api/session/<id> NAO troca o modelo do
    processo TUI em execucao (medido: PATCH 204 e a resposta seguinte
    saiu no modelo antigo).
O caminho que FUNCIONA (medido): `opencode run -s <sess> -m <model>` —
  roda UM turno na sessao existente, headless, sem roubar a tela.

USO:
  agent-model.py --list                       # modelos disponiveis agora
  agent-model.py --status <sessao>            # modelo atual da sessao
  agent-model.py --run <sessao> "texto"       # roda o turno, cai se 429
  agent-model.py --run <sessao> "texto" --model nvidia/minimaxai/minimax-m3.1-flash
  agent-model.py --run <sessao> "texto" --model auto   # escolhe por tarefa
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get("JARVIS_STATE_DIR", str(HOME / ".local/state/jarvis")))
COOLDOWN = STATE / "provider-cooldown.json"
SERVE = os.environ.get("AGENTS_OC_URL", "http://100.121.100.103:4599")
ENVFILE = HOME / ".config/opencode/server.env"
TIMEOUT = 300

# Ordem de fallback: cloud primeiro (capacidade), local por ultimo.
FALLBACK_ORDER = [
    "nvidia/",
    "openrouter/",
    "opencode/",
    "groq/",
    "cerebras/",
    "together/",
    "openai/",
    "anthropic/",
    "google/",
    "local/",
]

RATE_PAT = re.compile(r"(429|rate.?limit|too many requests|quota|overloaded|503|timeout|timed out)", re.I)


def password() -> str:
    pw = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not pw and ENVFILE.is_file():
        for line in ENVFILE.read_text().splitlines():
            if line.startswith("OPENCODE_SERVER_PASSWORD="):
                pw = line.split("=", 1)[1].strip().strip("\"'")
                break
    return pw


def _headers() -> dict:
    return {"Content-Type": "application/json",
            "Authorization": "Basic " + _b64(f"opencode:{password()}")}


def _b64(s: str) -> str:
    import base64
    return base64.b64encode(s.encode()).decode()


def session_model(session: str) -> dict:
    try:
        req = urllib.request.Request(f"{SERVE}/api/session/{session}", headers=_headers())
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read() or b"{}")
        d = d.get("data", d)
        return {"model": d.get("model") or {}, "title": d.get("title") or ""}
    except Exception as exc:  # noqa: BLE001
        return {"model": {}, "error": str(exc)}


def registry_models() -> list[dict]:
    """Modelos do registry da casa (fonte unica), com cooldown aplicado."""
    src = HOME / "projects/nixos-ai/modules/ai/jarvis/src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from jarvis.core.team import available_models  # type: ignore
        return available_models()
    except Exception:
        pass
    # fallback: lista do proprio opencode
    try:
        out = subprocess.run(["opencode", "models"], capture_output=True, text=True, timeout=60)
        models = []
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if "/" in line:
                pid, mid = line.split("/", 1)
                models.append({"provider_id": pid, "model_id": mid, "id": line})
        return models
    except Exception:
        return []


def in_cooldown(model_id: str, minutes: int = 10) -> bool:
    try:
        if not COOLDOWN.is_file():
            return False
        data = json.loads(COOLDOWN.read_text())
        stamp = float(data.get(model_id, 0) or 0)
        return stamp > 0 and (time.time() - stamp) < minutes * 60
    except Exception:
        return False


def mark_cooldown(model_id: str) -> None:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        data = json.loads(COOLDOWN.read_text()) if COOLDOWN.is_file() else {}
        data[model_id] = time.time()
        COOLDOWN.write_text(json.dumps(data, indent=1))
    except Exception:
        pass


def choose_models(current: str | None, auto: bool, explicit: str | None) -> list[str]:
    """Ordem de tentativa: o atual, o pedido, e depois o fallback por provider."""
    order: list[str] = []
    if explicit and explicit != "auto":
        order.append(explicit)
    if current:
        order.append(current)
    if auto:
        try:
            src = HOME / "projects/nixos-ai/modules/ai/jarvis/src"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from jarvis.core.team import model_for_task  # type: ignore
            mid, _why = model_for_task("")
            if mid:
                order.append(mid)
        except Exception:
            pass
    for m in registry_models():
        mid = m.get("id") or f"{m.get('provider_id','')}/{m.get('model_id','')}".strip("/")
        if mid and mid not in order:
            order.append(mid)
    # ordena por provider preference (cloud -> local), preservando o que foi pedido
    def rank(mid: str) -> int:
        for i, pref in enumerate(FALLBACK_ORDER):
            if mid.startswith(pref):
                return i
        return len(FALLBACK_ORDER)
    head = order[:2] if (explicit or current) else []
    tail = sorted([m for m in order if m not in head], key=rank)
    return head + tail


def run_turn(session: str, text: str, model: str) -> tuple[int, str]:
    cmd = ["opencode", "run", "-s", session, "-m", model, text]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status")
    ap.add_argument("--run")
    ap.add_argument("--model")
    ap.add_argument("--max-tries", type=int, default=3)
    ap.add_argument("message", nargs="*")
    args = ap.parse_args()

    if args.list:
        models = registry_models()
        out = []
        for m in models:
            mid = m.get("id") or f"{m.get('provider_id','')}/{m.get('model_id','')}".strip("/")
            out.append({"model": mid, "cooldown": in_cooldown(mid),
                        "tier": m.get("tier"), "note": m.get("note")})
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    if args.status:
        print(json.dumps(session_model(args.status), ensure_ascii=False))
        return 0

    if not args.run:
        ap.print_help()
        return 1

    text = " ".join(args.message).strip()
    if not text:
        print("falta a mensagem", file=sys.stderr)
        return 1

    current = (session_model(args.run).get("model") or {})
    current_id = ""
    if current:
        cur = current.get("id") or ""
        current_id = f"{current.get('providerID','')}/{cur}".lstrip("/") if cur else ""
    candidates = choose_models(current_id, args.model == "auto", args.model)
    candidates = [m for m in candidates if m and not in_cooldown(m)]
    if not candidates:
        print(json.dumps({"ok": False, "error": "nenhum modelo disponivel (tudo em cooldown)"},
                         ensure_ascii=False))
        return 2

    tried = []
    for model in candidates[: max(1, args.max_tries)]:
        rc, out = run_turn(args.run, text, model)
        tried.append({"model": model, "rc": rc})
        if rc == 0 and not RATE_PAT.search(out or ""):
            print(json.dumps({"ok": True, "model": model, "session": args.run,
                              "output": (out or "").strip()[-1200:], "tried": tried},
                             ensure_ascii=False))
            return 0
        # rate-limit/erro de provider: marca cooldown e tenta o proximo
        mark_cooldown(model)
        tried[-1]["rate_limited"] = True
    print(json.dumps({"ok": False, "session": args.run, "tried": tried,
                      "error": "todos os modelos tentados falharam"}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
