"""Self-heal — a "ia de bordo que conserta" (Fase 5 do roadmap).

Ciclo completo, fechando o auto-aprendizado:
  1. **Detectar** — roda `doctor_report()` (health dos serviços por HTTP).
  2. **Reparar** — para cada serviço `down`, restart via systemctl — mas só se
     estiver na ALLOWLIST (nunca restart de serviços arbitrários) e fora do
     cooldown (anti-loop: se foi reiniciado há pouco e continua down, reporta
     em vez de tentar de novo).
  3. **Auditar** — registra cada ação em `~/.local/state/jarvis/heal-audit.jsonl`
     (quem/quando/o quê/resultado — rastreável, reversível por geração Nix).
  4. **Aprender** — grava uma lição na memória episódica (formato experience
     buffer do legado) para o agente não repetir o erro e saber o fix.

Ações são reversíveis (rollback = 1 geração Nix) e auditáveis — o requisito
de segurança do self-improve.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.core.config import Config
from jarvis.core.doctor import doctor_report
from jarvis.core.logging import get_logger

# Componente do doctor → serviço systemd. Só o que é seguro/útil reiniciar.
SERVICE_MAP: dict[str, dict[str, str]] = {
    "llama_cpp": {"service": "llama-cpp-server", "scope": "system"},
    "llama_cpp_embeddings": {"service": "llama-cpp-embeddings", "scope": "system"},
    "qdrant": {"service": "qdrant", "scope": "system"},
}
ALLOWLIST = tuple(v["service"] for v in SERVICE_MAP.values())

DEFAULT_COOLDOWN_SECONDS = 300.0  # 5 min entre restarts do mesmo serviço
DEFAULT_MAX_RESTARTS = 5  # máximo de restarts por serviço antes de desistir
STATE_DIR_ENV = "JARVIS_STATE_DIR"


@dataclass
class HealAction:
    component: str
    service: str
    scope: str
    action: str  # restart | report_only
    ok: bool = False
    detail: str = ""
    skipped_reason: str = ""


@dataclass
class HealReport:
    overall: str = "ok"
    actions: list[HealAction] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)


def state_dir(cfg: Config | None = None) -> Path:
    base = os.environ.get(STATE_DIR_ENV) or (cfg.state_dir if cfg else None)
    p = Path(base) if base else Path.home() / ".local" / "state" / "jarvis"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _last_restart(state: Path, service: str) -> float:
    f = state / "heal-restarts.json"
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return float(data.get(service, 0.0))
        except (OSError, ValueError):
            return 0.0
    return 0.0


def _record_restart(state: Path, service: str) -> None:
    f = state / "heal-restarts.json"
    data: dict[str, Any] = {}
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    data[service] = time.time()
    f.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _append_audit(state: Path, entry: dict[str, Any]) -> None:
    f = state / "heal-audit.jsonl"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _restart_service(service: str, scope: str) -> tuple[bool, str]:
    """Restart via systemctl (system ou --user). Sem shell — lista explícita."""
    cmd = ["systemctl", "restart", service] if scope == "system" else ["systemctl", "--user", "restart", service]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"falha ao executar restart: {exc}"
    if proc.returncode == 0:
        return True, "restart OK"
    return False, (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:200]


def _alert(service: str, component: str, detail: str, *, healed: bool) -> None:
    """Notifica o usuário (notify-send + som) — best-effort, nunca quebra o heal."""
    try:
        from jarvis.core.feedback import notify, play_sound

        if healed:
            notify("✅ JARVIS", f"{service} restaurado", urgency="normal")
            play_sound("success")
        else:
            notify(
                "⚠️ JARVIS",
                f"{service} down — restart falhou",
                urgency="critical",
            )
            play_sound("error")
        # avisa no Telegram (se configurado) — o usuário acompanha do celular
        try:
            from jarvis.providers.telegram import send_notification

            send_notification(
                f"✅ {service} restaurado"
                if healed
                else f"⚠️ {service} down — restart falhou: {detail}"
            )
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def _alert_recovery(service: str, component: str) -> None:
    """Notifica quando um serviço que estava down volta ao normal."""
    try:
        from jarvis.core.feedback import notify, play_sound
        notify("✅ JARVIS", f"{service} está operacional novamente", urgency="low")
        play_sound("success")
        try:
            from jarvis.providers.telegram import send_notification
            send_notification(f"✅ {service} está operacional novamente")
        except Exception:  # noqa: BLE001 — notificação é best-effort
            pass
    except Exception:  # noqa: BLE001 — notificação é best-effort
        pass


def _learn_lesson(service: str, component: str, detail: str) -> None:
    """Grava a lição na memória episódica (nunca falha o heal por causa disso)."""
    try:
        from jarvis.core.memory import EpisodicMemory

        EpisodicMemory().remember_lesson(
            task=f"serviço {service} ficou down",
            error_pattern=f"doctor: {component} down — {detail}",
            fix="restart automático do serviço via systemctl",
        )
    except Exception:  # noqa: BLE001 — memória é best-effort
        pass


def _load_previous_state(state: Path) -> dict[str, str]:
    """Carrega estado anterior dos componentes (para detectar recovery)."""
    try:
        state_file = state / "component_states.json"
        if state_file.exists():
            return json.loads(state_file.read_text())
    except Exception:  # noqa: BLE001 — estado é best-effort
        pass
    return {}


def _save_previous_state(state: Path, states: dict[str, str]) -> None:
    """Salva estado dos componentes."""
    try:
        state_file = state / "component_states.json"
        state_file.write_text(json.dumps(states))
    except Exception:  # noqa: BLE001 — estado é best-effort
        pass


def _restart_count(state: Path, service: str) -> int:
    f = state / "heal-restart-counts.json"
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return int(data.get(service, 0))
        except (OSError, ValueError):
            return 0
    return 0


def _record_restart_count(state: Path, service: str) -> int:
    f = state / "heal-restart-counts.json"
    data: dict[str, Any] = {}
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    count = int(data.get(service, 0)) + 1
    data[service] = count
    f.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return count


def _verify_service_up(service: str, scope: str, timeout_s: float = 10.0) -> bool:
    """Verifica se o serviço subiu após restart (com polling curto)."""
    import time as _time
    deadline = _time.time() + timeout_s
    while _time.time() < deadline:
        try:
            cmd = ["systemctl", "is-active", service] if scope == "system" else ["systemctl", "--user", "is-active", service]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if proc.stdout.strip() == "active":
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        _time.sleep(1.0)
    return False


def heal_once(cfg: Config | None = None, *, cooldown: float = DEFAULT_COOLDOWN_SECONDS, alerts: bool = True, max_restarts: int = DEFAULT_MAX_RESTARTS) -> HealReport:
    """Detecta + repara. Retorna o relatório completo."""
    log = get_logger("heal")
    cfg = cfg or Config()
    state = state_dir(cfg)
    report = doctor_report(cfg)
    report_inst = HealReport(overall=report.get("overall", "ok"), checks=report.get("checks", []))

    # Carrega estado anterior para detectar recovery
    prev_states = _load_previous_state(state)
    curr_states = {}

    for check in report.get("checks", []):
        comp = check.get("name", "")
        status = check.get("status", "ok")
        curr_states[comp] = status

        # Se estava down e agora está ok → notifica recovery
        if prev_states.get(comp) == "down" and status == "ok":
            if alerts:
                _alert_recovery(comp, comp)

        if status != "down":
            continue
        spec = SERVICE_MAP.get(comp)
        if not spec:
            report_inst.actions.append(
                HealAction(component=comp, service="?", scope="?", action="report_only", skipped_reason="sem serviço mapeado")
            )
            continue
        service, scope = spec["service"], spec["scope"]
        if service not in ALLOWLIST:
            report_inst.actions.append(
                HealAction(component=comp, service=service, scope=scope, action="report_only", skipped_reason="fora da allowlist")
            )
            continue

        last = _last_restart(state, service)
        restart_count = _restart_count(state, service)

        # Verifica cooldown
        if time.time() - last < cooldown:
            report_inst.actions.append(
                HealAction(
                    component=comp, service=service, scope=scope, action="report_only",
                    skipped_reason=f"cooldown ({cooldown:.0f}s) — restart recente ainda não resolveu",
                )
            )
            continue

        # Verifica limite de restarts
        if restart_count >= max_restarts:
            report_inst.actions.append(
                HealAction(
                    component=comp, service=service, scope=scope, action="report_only",
                    skipped_reason=f"max restarts ({max_restarts}) atingido — serviço persistentemente down",
                )
            )
            continue

        ok, detail = _restart_service(service, scope)
        log.info("heal_restart", detail={
            "component": comp, "service": service, "ok": ok, "detail": detail,
            "restart_count": restart_count + 1,
        })

        # Verificação pós-restart: confirma que o serviço subiu
        if ok:
            verified = _verify_service_up(service, scope)
            if not verified:
                ok = False
                detail = "restart executou mas serviço não confirmou como ativo"
                log.warn("heal_verify_failed", detail={"component": comp, "service": service})

        if ok:
            _record_restart(state, service)
            # Sucesso: zera contador de restarts
            try:
                state / "heal-restart-counts.json"
                counts_file = state / "heal-restart-counts.json"
                if counts_file.exists():
                    data = json.loads(counts_file.read_text(encoding="utf-8"))
                    data[service] = 0
                    counts_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
        else:
            _record_restart_count(state, service)

        _append_audit(state, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "component": comp,
            "service": service,
            "action": "restart",
            "ok": ok,
            "detail": detail,
            "restart_count": restart_count + 1,
        })
        if alerts:
            _alert(service, comp, detail, healed=ok)
        if ok:
            _learn_lesson(service, comp, detail)
        report_inst.actions.append(HealAction(component=comp, service=service, scope=scope, action="restart", ok=ok, detail=detail))

    if any(a.action == "restart" and not a.ok for a in report_inst.actions):
        report_inst.overall = "down"
    elif any(a.action == "restart" for a in report_inst.actions):
        report_inst.overall = "healed"
    elif any(a.action == "report_only" for a in report_inst.actions):
        report_inst.overall = "degraded"

    # Salva estado atual para detectar recovery na próxima iteração
    if curr_states:
        _save_previous_state(state, curr_states)

    return report_inst


def heal_report(cfg: Config | None = None, *, cooldown: float = DEFAULT_COOLDOWN_SECONDS, alerts: bool = True) -> dict[str, Any]:
    """Relatório em dict (JSON-friendly)."""
    r = heal_once(cfg, cooldown=cooldown, alerts=alerts)
    return {
        "overall": r.overall,
        "checks": r.checks,
        "actions": [
            {
                "component": a.component,
                "service": a.service,
                "action": a.action,
                "ok": a.ok,
                "detail": a.detail,
                **( {"skipped_reason": a.skipped_reason} if a.skipped_reason else {}),
            }
            for a in r.actions
        ],
    }


def main_heal(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis heal [--watch] [--cooldown S] [--json]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis heal", description="Detecta serviços down e repara (restart allowlist)")
    parser.add_argument("--watch", action="store_true", help="loop contínuo (daemon): verifica a cada N segundos")
    parser.add_argument("--interval", type=float, default=60.0, help="intervalo do watch em segundos (default 60)")
    parser.add_argument("--cooldown", type=float, default=DEFAULT_COOLDOWN_SECONDS, help="cooldown entre restarts (default 300s)")
    parser.add_argument("--no-alerts", action="store_true", help="não notifica o usuário (notify-send/som)")
    parser.add_argument("--json", action="store_true", help="saída JSON pura")
    args = parser.parse_args(argv)

    if args.watch:
        print(f"heal watch: verificando a cada {args.interval:.0f}s (ctrl-c para parar)")
        while True:
            report = heal_report(cooldown=args.cooldown, alerts=not args.no_alerts)
            if args.json:
                print(json.dumps(report, ensure_ascii=False))
            else:
                print(f"[{time.strftime('%H:%M:%S')}] overall={report['overall']} "
                      f"restarts={sum(1 for a in report['actions'] if a['action'] == 'restart')}")
            time.sleep(args.interval)

    report = heal_report(cooldown=args.cooldown, alerts=not args.no_alerts)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Heal — overall: {report['overall']}")
        for a in report["actions"]:
            status = "✅" if (a["action"] == "restart" and a["ok"]) else ("⏭️" if a["action"] == "report_only" else "❌")
            print(f"  {status} {a['component']:<22} {a['action']:<12} {a.get('detail') or a.get('skipped_reason', '')}")
        for c in report["checks"]:
            mark = "✓" if c["status"] == "ok" else ("⚠" if c["status"] == "degraded" else "✗")
            print(f"  {mark} {c['name']:<22} {c['status']:<9} {c.get('detail', '')[:60]}")
    return 0 if report["overall"] in ("ok", "healed") else 2
