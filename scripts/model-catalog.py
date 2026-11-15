#!/usr/bin/env python3
"""model-catalog.py — o catalogo REAL de modelos + medidor de rate-limit.

(15/11, crouton-alpha) O dono pediu: "na criacao de agente, ter uma lista
dos modelos disponiveis ... com descricao do que cada modelo e' melhor, os
fracos, fortes, ctx, mas o real que vem da API nao o default do opencode"
e um "medidor de rate limit, pq os da opencode acabam rapido, nvidia dura
muito mais porem e' mais lento ttft".

FONTES (todas reais, nada inventado):
  1. modules/ai/free-providers.json — o catalogo curado da casa: contexto
     MEDIDO no endpoint, output (teto de max_tokens), tier, capabilities,
     good_for (quando usar), status. E o cascade por camada.
  2. ~/.local/state/jarvis/provider-cooldown.json — quem caiu em 429
     recentemente (o guard de provider).
  3. http://127.0.0.1:8095/__gate/health — os CONTADORES REAIS do nv-gate
     (o proxy que protege o tier NVIDIA): requests, upstream_429, retries,
     tempo em fila, 503. E o medidor de "nvidia dura mais, mas TTFT Worse".
  4. /api/model do opencode — a lista que o opencode realmente usa (e o
     "default" que o dono diz estar errado).

saida: JSON (--pretty para humano)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
REPO = HOME / "projects/nixos-ai"
CATALOG = REPO / "modules/ai/free-providers.json"
COOLDOWN = HOME / ".local/state/jarvis/provider-cooldown.json"
GATE = "http://127.0.0.1:8095/__gate/health"
OC_MODELS = "http://100.121.100.103:4599/api/model"


def _get(url: str, timeout: int = 12, headers: dict | None = None):
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception:
        return None


def _auth() -> dict:
    pw = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not pw:
        env = HOME / ".config/opencode/server.env"
        if env.is_file():
            for line in env.read_text().splitlines():
                if line.startswith("OPENCODE_SERVER_PASSWORD="):
                    pw = line.split("=", 1)[1].strip().strip("\"'")
                    break
    import base64
    return {"Authorization": "Basic " + base64.b64encode(f"opencode:{pw}".encode()).decode()}


def load_catalog() -> dict:
    try:
        return json.loads(CATALOG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def cooldown_map() -> dict:
    try:
        data = json.loads(COOLDOWN.read_text())
        now = time.time()
        out = {}
        for k, ts in (data or {}).items():
            age = now - float(ts or 0)
            out[k] = {"since_min": round(age / 60, 1), "active": 0 < age < 3600}
        return out
    except Exception:
        return {}


def gate_stats() -> dict:
    d = _get(GATE, timeout=8) or {}
    data = d.get("data", d)
    try:
        reqs = max(1, int(data.get("requests") or 1))
        return {
            "rpm_limit": data.get("rpm"),
            "burst": data.get("burst"),
            "requests": data.get("requests"),
            "ok": data.get("ok"),
            "upstream_429": data.get("upstream_429"),
            "retries": data.get("retries"),
            "upstream_503": data.get("upstream_503"),
            "upstream_504": data.get("upstream_504"),
            "errors": data.get("errors"),
            "queued_seconds": round(float(data.get("queued_seconds") or 0), 1),
            "ctx_rejected": data.get("ctx_rejected"),
            "taxa_429_pct": round(100.0 * float(data.get("upstream_429") or 0) / reqs, 1),
        }
    except Exception:
        return {}


def opencode_models() -> list:
    d = _get(OC_MODELS, timeout=15, headers=_auth())
    if not d:
        return []
    data = d.get("data", d) if isinstance(d, dict) else d
    out = []
    for m in (data or []):
        if not isinstance(m, dict):
            continue
        out.append({
            "provider": m.get("providerID") or "",
            "id": m.get("id") or m.get("modelID") or "",
            "name": m.get("name") or "",
        })
    return out



# (15/11, dono) "redteam um modelo de api tambem, n apenas local".
# SEM LISTA FIXA: o catalogo (free-providers.json) e o registry (models.nix)
# sao a fonte da verdade. O local vem do registry (o alias que o opencode
# carrega) e a API vem do catalogo, escolhida por TIER (reasoning = mais
# inteligente) — o que o dono pediu: "o modelo ideal pra tarefa".
LOCAL_CANDIDATE_HINTS = ("local-uncensored-4b/jarvis-mtp-lora",)  # medido carregando


def local_candidates() -> list:
    """Modelos LOCAIS que o opencode carrega (registry + alias do server)."""
    out = []
    try:
        from jarvis.core.model_registry import registry_or_none
        reg = registry_or_none()
        if reg is not None:
            for mid in reg.ids():
                full = mid if "/" in mid else f"local/{mid}"
                out.append(full)
    except Exception:
        pass
    for hint in LOCAL_CANDIDATE_HINTS:
        if hint not in out:
            out.append(hint)
    return out


def api_candidates(cat: dict, tiers: tuple = ("reasoning", "general", "fast")) -> list:
    """Modelos de API do catalogo, ordenados por tier (reasoning primeiro)."""
    rows = []
    for pname, pv in (cat.get("providers") or {}).items():
        for m in (pv.get("models") or []):
            tier = m.get("tier") or ""
            if tier not in tiers:
                continue
            rows.append((tiers.index(tier), pname, m))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [f"{p}/{m.get('id')}" for _t, p, m in rows]


def redteam_candidates(cat: dict) -> list:
    """Candidatos do perfil redteam: local medido + API por tier. Sem lista fixa."""
    idx = {}
    for pname, pv in (cat.get("providers") or {}).items():
        for m in (pv.get("models") or []):
            idx[f"{pname}/{m.get('id')}"] = (pname, m)
    out = []
    for full in local_candidates():
        out.append({
            "id": full, "kind": "local", "name": full,
            "context": None, "output": None, "tier": "local",
            "good_for": "Local, sem recusa, latencia baixa (perfil slim: sem MCP/tools).",
            "status": "verified-loadable" if full in LOCAL_CANDIDATE_HINTS else "listed",
        })
    for full in api_candidates(cat)[:8]:
        pname, m = idx.get(full, (None, None))
        out.append({
            "id": full, "kind": "api",
            "name": (m or {}).get("name") or full,
            "context": (m or {}).get("context"), "output": (m or {}).get("output"),
            "tier": (m or {}).get("tier"), "good_for": (m or {}).get("good_for") or "",
            "status": (m or {}).get("status") or "listed",
        })
    return out

def build() -> dict:
    cat = load_catalog()
    cd = cooldown_map()
    providers = []
    for pname, pv in (cat.get("providers") or {}).items():
        models = []
        for m in (pv.get("models") or []):
            mid = m.get("id") or ""
            full = f"{pname}/{mid}"
            models.append({
                "id": full,
                "name": m.get("name") or mid,
                "context": m.get("context"),
                "output": m.get("output"),
                "tier": m.get("tier") or "",
                "capabilities": m.get("capabilities") or [],
                "good_for": m.get("good_for") or "",
                "status": m.get("status") or "",
                "in_cooldown": cd.get(full, {}).get("active", False),
                "cooldown_min": cd.get(full, {}).get("since_min"),
            })
        providers.append({
            "id": pname,
            "models": models,
            "n_models": len(models),
            "note": pv.get("note") or "",
        })
    return {
        "ts": int(time.time()),
        "providers": providers,
        "redteam_candidates": redteam_candidates(cat),
        "redteam_profile": {
            "mbti": "INTP",
            "persona": "redteam_researcher",
            "nota": "INTP = perfil de pesquisa/tecnico: o redteam pede evidencia, nao consolo. O jailbreak do plugin redteam.js e do dono: o agente roda com o system prompt de persona + as regras da casa.",
        },
        "cascade_layers": cat.get("cascade_layers") or {},
        "disabled_providers": cat.get("disabled_providers") or {},
        "headroom": cat.get("_headroom") or "",
        "rate_limit": {
            "nvidia_gate": gate_stats(),
            "cooldown": cd,
            "opencode_quota": "o tier opencode (Zen/j/kimi-free) tem cota curta: usar so p/ tarefa curta e medido",
        },
        "opencode_models": opencode_models(),
        "notas": [
            "ctx = contexto REAL medido no endpoint (nao o default do opencode)",
            "output = teto de max_tokens do provider",
            "nvidia: dura muito mais (o gate segura o burst) mas TTFT maior; opencode/: cota curta, acaba rapido",
        ],
    }


def main() -> int:
    data = build()
    if "--pretty" in sys.argv:
        for p in data["providers"]:
            print(f"\n{p['id']} ({p['n_models']} modelos)")
            for m in p["models"][:6]:
                cd = " [COOLDOWN]" if m["in_cooldown"] else ""
                print(f"   {m['name'][:38]:38s} ctx={m['context']} out={m['output']} tier={m['tier']}{cd}")
                if m["good_for"]:
                    print(f"      {m['good_for'][:150]}")
    else:
        print(json.dumps(data, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
