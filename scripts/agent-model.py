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
# (27/11, medido) O timeout POR TENTATIVA tem de caber no orcamento do
# CHAMADOR. O provider-guard roda este script com
# `subprocess.run(..., timeout=420)` e passa --max-tries 2: com 300 s por
# tentativa o pior caso interno era 600 s, e o guard ABORTAVA o processo em
# 420 s -> "troca falhou: Command ... timed out after 420 seconds" (medido
# nas notas de 25/11 e 27/11). Agora o orcamento do guard e o teto: cada
# tentativa fica abaixo de (420 - folga) / max_tries. 180 s por tentativa
# deixa 2 folgas de 30 s e cabe em 360 s < 420 s.
TIMEOUT = int(os.environ.get("AGENTS_MODEL_ATTEMPT_TIMEOUT", "180"))

# Orcamento total do CHAMADOR (o provider-guard): o script inteiro nao pode
# passar dele, senao o guard mata a rotacao antes do fim.
CALLER_BUDGET = int(os.environ.get("AGENTS_MODEL_BUDGET", "420"))

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


def vram_free_mib() -> int:
    """VRAM livre agora (MiB). Medido: 6.141 MiB no total da casa."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return -1


def endpoint_up(endpoint: str) -> bool:
    """O servidor local deste endpoint responde de verdade?"""
    if not endpoint:
        return False
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{endpoint}/v1/models")
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.getcode() == 200
    except Exception:
        return False


REGISTRY_FILE = Path("/etc/jarvis/model-registry.json")


def registry_endpoint(mid: str) -> str:
    """A porta do endpoint local deste id (fonte: /etc/jarvis/model-registry.json).

    (15/11) O available_models() do team nao traz o `endpoint`; o registry da
    casa tem ("bonsai": 8080, "jarvis-mtp-lora": 8092, ...).
    """
    try:
        if REGISTRY_FILE.is_file():
            data = json.loads(REGISTRY_FILE.read_text())
            for key in (mid, mid.split("/")[-1]):
                m = (data.get("models") or {}).get(key) or {}
                ep = m.get("endpoint")
                if ep:
                    return str(ep)
    except Exception:
        pass
    return ""


def apply_vram_rule(order: list[str]) -> tuple[list[str], list[str]]:
    """A receita do transcript (15/11) aplicada a escolha de modelo.

    Medido na casa: 6.141 MiB de VRAM; o MTP segura 3.874, os embeddings 446
    e o whisper 934 -> **102 MiB livres**. Um segundo modelo local NAO cabe.

    * local pedido que NAO esta no ar:
        - VRAM livre (idle)  -> a API do mesmo tier vai na frente e o swap
          fica como acao sugerida (llama-swap.sh);
        - VRAM ocupada       -> a API cobre; o local vai para o fim da fila.
    * local no ar -> fica como esta (barato, sem latencia).
    """
    notas: list[str] = []
    free = vram_free_mib()
    head: list[str] = []
    tail: list[str] = []
    for mid in order:
        ep = registry_endpoint(mid)
        if not ep:
            head.append(mid)
            continue
        if endpoint_up(ep):
            head.append(mid)
            continue
        if free >= 2000:
            notas.append(f"{mid}: local NAO esta no ar e ha VRAM livre ({free} MiB) "
                         f"-> a API do mesmo tier vai na frente; "
                         f"swap sugerido: bash scripts/llama-swap.sh --free "
                         f"&& bash scripts/llama-swap.sh --wait-model <alias>")
            tail.append(mid)
        else:
            notas.append(f"{mid}: local NAO esta no ar e a VRAM esta ocupada "
                         f"({free} MiB livres) -> a API cobre este tier")
            tail.append(mid)
    return head + tail, notas


def _catalog_id(model: dict | None) -> str:
    """O id do modelo NO CATALOGO (a chave que o cooldown usa).

    (27/11, medido) A sessao devolve `providerID` = o PROVIDER e `id` = o id
    do modelo DENTRO desse provider. O catalogo usa o caminho COMPLETO:
    `nvidia/google/gemma-4-31b-it`; a sessao devolve `gemma-4-31b-it` com
    providerID `nvidia`. Concatenar daria `nvidia/gemma-4-31b-it`, que nunca
    casa com a entrada do catalogo -> o modelo que caiu continuava sendo a
    1a tentativa da rotacao e a remocao dele era um no-op.

    Aqui devolvemos o id do catalogo REAL: procuramos a entrada cujo
    caminho termina com o id da sessao (e pertence ao mesmo provider).
    """
    if not isinstance(model, dict):
        return ""
    mid = str(model.get("id") or "")
    if not mid:
        return ""
    provider = str(model.get("providerID") or "")
    if "/" in mid:
        return mid
    # o catalogo e a fonte da verdade do id completo
    for m in registry_models():
        cid = str(m.get("id") or
                  f"{m.get('provider_id','')}/{m.get('model_id','')}".strip("/"))
        if not cid:
            continue
        # o catalogo tem `google/gemma-4-31b-it` e a sessao devolve
        # `gemma-4-31b-it`: compara o ULTIMO segmento do caminho
        if cid.split("/")[-1] != mid:
            continue
        if provider and not cid.startswith(provider + "/"):
            # mesmo id em outro provider: nao e o nosso
            continue
        return cid
    return f"{provider}/{mid}" if provider else mid


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
    ordenado = head + tail
    # (15/11) A REGRA DA VRAM (a receita do transcript): local que nao esta
    # no ar nao briga pela VRAM — a API do mesmo tier responde.
    try:
        ordenado, _notas = apply_vram_rule(ordenado)
    except Exception:
        pass
    return ordenado


def run_turn(session: str, text: str, model: str, timeout: int | None = None) -> tuple[int, str]:
    cmd = ["opencode", "run", "-s", session, "-m", model, text]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout or TIMEOUT)
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
                    "vram_livre_mib": vram_free_mib(),
                    "local_no_ar": (endpoint_up(registry_endpoint(mid))
                                    if registry_endpoint(mid) else None),
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
    current_id = _catalog_id(current)
    candidates = choose_models(current_id, args.model == "auto", args.model)
    candidates = [m for m in candidates if m and not in_cooldown(m)]
    # (27/11, medido) A ROTACAO NAO PODE TENTAR PRIMEIRO O MODELO QUE
    # ACABOU DE FALHAR. Este script e chamado pelo provider-guard justamente
    # porque o modelo ATUAL caiu (429, EOL, quota): o `choose_models` punha o
    # modelo corrente no topo da lista, entao a 1a tentativa era o modelo
    # MORTO de novo. Com --max-tries 2 sobrava so 1 tentativa real, e se ela
    # falhasse o guard reportava 'todos os modelos tentados falharam'.
    # Medido: para a sessao ses_e0cc94944ffenbIgskVV0Cv3K7 (modelo
    # nvidia/google/gemma-4-31b-it, EOL), o 1o candidato era o proprio
    # gemma-4-31b-it. Agora o modelo que falhou vai para o FIM.
    if current_id and current_id in candidates:
        candidates.remove(current_id)
        candidates.append(current_id)
    if not candidates:
        print(json.dumps({"ok": False, "error": "nenhum modelo disponivel (tudo em cooldown)"},
                         ensure_ascii=False))
        return 2

    tried = []
    max_tries = max(1, args.max_tries)
    # (27/11, medido) Cada tentativa tem de caber no orcamento do CHAMADOR
    # (o guard usa 420 s). O timeout por tentativa e calculado aqui, em vez
    # de ser um valor fixo, para que N tentativas nunca estourem o orcamento:
    # budget / tentativas, com uma folga para o processo em si.
    folga = 30
    por_tentativa = max(30, (CALLER_BUDGET - folga) // max_tries)
    por_tentativa = min(por_tentativa, TIMEOUT)
    for model in candidates[:max_tries]:
        rc, out = run_turn(args.run, text, model, timeout=por_tentativa)
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
