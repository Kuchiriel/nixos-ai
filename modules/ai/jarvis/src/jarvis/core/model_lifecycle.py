"""Lifecycle do router llama-server — ensure(model) idempotente.

Sem SIGTERM, sem segundo processo: o router nativo (--models-preset)
faz unload/load sob demanda; aqui só orquestramos via HTTP:

  already active → no-op
  different      → lock → POST /models/load → poll /v1/models até
                    status==loaded + id match → unlock + report

Identidade (anti false-green): /health ok NÃO basta — exigimos a entrada
do modelo com status loaded no /v1/models (o router distingue
unloaded/loading/loaded/failed).
"""

from __future__ import annotations

import fcntl
import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError


class ModelSwitchError(RuntimeError):
    """Falha em alguma fase do ensure (fase identificada em .phase)."""

    def __init__(self, phase: str, detail: str):
        super().__init__(f"[{phase}] {detail}")
        self.phase = phase


@dataclass
class SwitchReport:
    requested: str
    previous: str | None
    selected: str
    switched: bool
    startup_latency_s: float = 0.0
    identity_verified: bool = False
    reason: dict = field(default_factory=dict)


def _http(base_url: str, path: str, payload: dict | None = None,
          timeout: float = 30.0) -> dict | list:
    base = base_url.rstrip("/")
    # Callers passam llm_base_url (com /v1); router admin vive na raiz.
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _models_data(base_url: str, timeout: float = 30.0) -> list[dict]:
    data = _http(base_url, "/v1/models", timeout=timeout)
    if isinstance(data, dict):
        return data.get("data", [])
    return []


def active_model(base_url: str, timeout: float = 30.0) -> str | None:
    """ID do modelo residente (status loaded) ou None.

    Servidor single-model (sem status): o único id conta como ativo.
    """
    for m in _models_data(base_url, timeout):
        status = (m.get("status") or {}).get("value")
        if status is None or status == "loaded":
            return m.get("id")
    return None


def _lock_path() -> Path:
    from jarvis.core.config import get_config
    d = Path(get_config().state_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / "model-switch.lock"


def _wait_settled(base_url: str, budget_s: float, poll_s: float) -> None:
    """Espera nenhum modelo em loading/downloading (router ocupado).

    Best-effort: esgota o budget em silêncio — quem chamou decide retry.
    """
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        try:
            states = [(m.get("status") or {}).get("value")
                      for m in _models_data(base_url)]
        except Exception:
            return
        if not any(s in ("loading", "downloading") for s in states):
            return
        time.sleep(poll_s)


def ensure_model(
    model_id: str,
    base_url: str = "http://127.0.0.1:8080",
    *,
    load_timeout_s: float = 300.0,
    lock_timeout_s: float = 330.0,
    poll_interval_s: float = 2.0,
) -> SwitchReport:
    """Garante o modelo residente. Idempotente e serializado (flock).

    Timeouts separados por fase (§15): lock, load+poll, health. Request
    concorrente p/ outro modelo espera o lock (não intercala A/B).
    """
    t0 = time.monotonic()
    try:
        current = active_model(base_url)
    except Exception as e:
        raise ModelSwitchError("discover", f"/v1/models inacessível: {e}") from e
    if current == model_id:
        return SwitchReport(requested=model_id, previous=current,
                            selected=model_id, switched=False,
                            identity_verified=True,
                            reason={"noop": "already active"})

    lockf = _lock_path().open("w")
    waited = 0.0
    while True:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if waited >= lock_timeout_s:
                lockf.close()
                raise ModelSwitchError(
                    "lock", f"lock ocupado após {lock_timeout_s}s") from None
            time.sleep(0.5)
            waited += 0.5
    try:
        # Re-checa sob lock (outro processo pode ter trocado enquanto
        # esperávamos — evita load redundante e corrida A/B).
        try:
            current = active_model(base_url)
        except Exception as e:
            raise ModelSwitchError("discover", f"re-check falhou: {e}") from e
        if current == model_id:
            return SwitchReport(requested=model_id, previous=current,
                                selected=model_id, switched=False,
                                identity_verified=True,
                                reason={"noop": "switched while waiting lock"})
        attempts = 0
        while True:
            attempts += 1
            try:
                _http(base_url, "/models/load", {"model": model_id}, timeout=30.0)
                break
            except HTTPError as e:
                # 500 "model limit reached": outro load em andamento
                # (router max N ou autoload de um chat concorrente) —
                # transitório: espera assentar e tenta de novo (1x).
                # 404: preset desconhecido ou servidor single-model.
                if e.code == 500 and attempts == 1:
                    _wait_settled(base_url, budget_s=120.0,
                                  poll_s=poll_interval_s)
                    continue
                raise ModelSwitchError(
                    "load", f"POST /models/load rejeitado (HTTP {e.code}: "
                    f"{e.reason}; 404=preset desconhecido/single-model, "
                    f"500=router ocupado; ativo={current})") from e
            except Exception as e:
                raise ModelSwitchError(
                    "load", f"POST /models/load falhou ({e}); "
                    f"servidor single-model? ativo={current}") from e
        deadline = time.monotonic() + load_timeout_s
        while time.monotonic() < deadline:
            for m in _models_data(base_url):
                st = (m.get("status") or {}).get("value")
                if m.get("id") == model_id and (st is None or st == "loaded"):
                    lat = time.monotonic() - t0
                    # /health confirma servindo (loaded + healthy = usável).
                    try:
                        _http(base_url, "/health", timeout=10.0)
                    except Exception as e:
                        raise ModelSwitchError(
                            "health", f"{model_id} loaded mas /health falhou: {e}") from e
                    return SwitchReport(
                        requested=model_id, previous=current, selected=model_id,
                        switched=True, startup_latency_s=lat,
                        identity_verified=True,
                        reason={"load": "router", "previous": current})
                if m.get("id") == model_id and st == "failed":
                    raise ModelSwitchError(
                        "load", f"router marcou {model_id} como 'failed'") from None
                # "unloaded"/"sleeping" durante a transição são normais
                # (ainda não carregou / dormiu por idle) — só o deadline
                # decide (fase readiness).
            time.sleep(poll_interval_s)
        raise ModelSwitchError(
            "readiness", f"{model_id} não ficou loaded em {load_timeout_s}s") from None
    finally:
        try:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        finally:
            lockf.close()
