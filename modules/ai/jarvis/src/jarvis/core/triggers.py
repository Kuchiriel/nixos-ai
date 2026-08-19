"""Motor de Triggers — automações declarativas por gatilhos do sistema.

Permite definir regras como:
  - "quando disco > 90%, notificar no Telegram"
  - "a cada 30min, rodar doctor e alertar se degradado"
  - "quando CPU > 80% por 5min, reportar"

Cada trigger tem:
  - name: identificador único
  - event: tópico do event bus que dispara (ou "poll" para checagem periódica)
  - condition: callable que retorna True se a ação deve executar
  - action: callable que executa a ação (notificação, restart, etc.)
  - cooldown: segundos mínimos entre execuções (anti-loop)
  - idempotente: se True, não executa se a condição não mudou desde a última vez

Persistência: triggers são definidos em código (declarativo), não em JSON dinâmico.
Estado de execução (último run, última condição) fica em memória + JSONL de audit.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Trigger:
    """Um gatilho declarativo."""
    name: str
    description: str
    condition: Callable[[], bool]
    action: Callable[[], Any]
    cooldown_s: float = 300.0  # 5 min default
    idempotent: bool = True  # não executa se condição não mudou
    enabled: bool = True


@dataclass
class TriggerState:
    """Estado de execução de um trigger."""
    last_run: float = 0.0
    last_condition: bool = False
    run_count: int = 0
    last_error: str = ""


class TriggerEngine:
    """Motor de triggers com cooldown e idempotência.

    Exemplo:
        engine = TriggerEngine(state_dir=Path("~/.local/state/jarvis"))
        engine.register(Trigger(
            name="disk_alert",
            description="Alerta quando disco > 90%",
            condition=lambda: _disk_usage() > 90,
            action=lambda: notify("⚠️ Disco cheio"),
            cooldown_s=3600,
        ))
        engine.run_all()  # checa todos os triggers
    """

    def __init__(self, state_dir: Path | None = None) -> None:
        self._triggers: dict[str, Trigger] = {}
        self._states: dict[str, TriggerState] = {}
        self._state_dir = state_dir
        self._load_states()

    def register(self, trigger: Trigger) -> None:
        """Registra um trigger."""
        self._triggers[trigger.name] = trigger
        if trigger.name not in self._states:
            self._states[trigger.name] = TriggerState()

    def run_all(self) -> list[dict[str, Any]]:
        """Executa todos os triggers habilitados. Retorna relatório."""
        report: list[dict[str, Any]] = []
        for name, trigger in self._triggers.items():
            if not trigger.enabled:
                continue
            result = self._run_one(trigger)
            report.append(result)
        self._save_states()
        return report

    def run_one(self, name: str) -> dict[str, Any] | None:
        """Executa um trigger específico."""
        trigger = self._triggers.get(name)
        if trigger is None:
            return None
        result = self._run_one(trigger)
        self._save_states()
        return result

    def _run_one(self, trigger: Trigger) -> dict[str, Any]:
        """Executa um trigger com verificação de cooldown e idempotência."""
        state = self._states.setdefault(trigger.name, TriggerState())
        now = time.time()

        # Cooldown
        if now - state.last_run < trigger.cooldown_s:
            return {
                "name": trigger.name,
                "action": "skipped",
                "reason": f"cooldown ({trigger.cooldown_s:.0f}s)",
            }

        # Checa condição
        try:
            condition_met = trigger.condition()
        except Exception as exc:  # noqa: BLE001
            state.last_error = str(exc)
            return {
                "name": trigger.name,
                "action": "error",
                "error": f"condition failed: {exc}",
            }

        # Idempotência: não executa se condição não mudou
        if trigger.idempotent and condition_met == state.last_condition:
            return {
                "name": trigger.name,
                "action": "skipped",
                "reason": f"condition unchanged ({condition_met})",
            }

        # Executa ação
        if condition_met:
            try:
                trigger.action()
                state.last_run = now
                state.last_condition = True
                state.run_count += 1
                state.last_error = ""
                return {
                    "name": trigger.name,
                    "action": "executed",
                    "condition": True,
                    "run_count": state.run_count,
                }
            except Exception as exc:  # noqa: BLE001
                state.last_error = str(exc)
                return {
                    "name": trigger.name,
                    "action": "error",
                    "error": f"action failed: {exc}",
                }

        # Condição não atendida — atualiza estado
        state.last_condition = False
        return {
            "name": trigger.name,
            "action": "skipped",
            "reason": "condition not met",
        }

    def status(self) -> list[dict[str, Any]]:
        """Status de todos os triggers."""
        result = []
        for name, trigger in self._triggers.items():
            state = self._states.get(name, TriggerState())
            result.append({
                "name": name,
                "description": trigger.description,
                "enabled": trigger.enabled,
                "cooldown_s": trigger.cooldown_s,
                "last_run": state.last_run,
                "run_count": state.run_count,
                "last_error": state.last_error,
            })
        return result

    # --- persistência ---

    def _load_states(self) -> None:
        if self._state_dir is None:
            return
        path = self._state_dir / "trigger-states.json"
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for name, data in raw.items():
                self._states[name] = TriggerState(
                    last_run=data.get("last_run", 0.0),
                    last_condition=data.get("last_condition", False),
                    run_count=data.get("run_count", 0),
                    last_error=data.get("last_error", ""),
                )
        except (OSError, json.JSONDecodeError):
            pass

    def _save_states(self) -> None:
        if self._state_dir is None:
            return
        self._state_dir.mkdir(parents=True, exist_ok=True)
        path = self._state_dir / "trigger-states.json"
        data = {}
        for name, state in self._states.items():
            data[name] = {
                "last_run": state.last_run,
                "last_condition": state.last_condition,
                "run_count": state.run_count,
                "last_error": state.last_error,
            }
        try:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Triggers pré-definidos para o JARVIS
# ---------------------------------------------------------------------------

def _disk_usage_pct() -> float:
    """Retorna % de uso do disco /."""
    import shutil
    usage = shutil.disk_usage("/")
    return usage.used / usage.total * 100


def _load_avg() -> float:
    """Retorna load average 1min."""
    import os
    try:
        return os.getloadavg()[0]
    except (OSError, IndexError):
        return 0.0


def create_default_triggers(
    *,
    notify_fn: Callable[[str], Any] | None = None,
    doctor_fn: Callable[[], dict[str, Any]] | None = None,
    state_dir: Path | None = None,
) -> TriggerEngine:
    """Cria o engine com os triggers padrão do JARVIS.

    Args:
        notify_fn: função de notificação (ex: send_notification do Telegram)
        doctor_fn: função que retorna doctor_report
        state_dir: diretório de estado para persistir triggers
    """
    engine = TriggerEngine(state_dir=state_dir)

    # Trigger 1: Disco > 90%
    def _disk_alert_condition() -> bool:
        return _disk_usage_pct() > 90

    def _disk_alert_action() -> None:
        pct = _disk_usage_pct()
        msg = f"⚠️ Disco {pct:.0f}% cheio — execute clean.sh ou nix-collect-garbage"
        if notify_fn:
            notify_fn(msg)

    engine.register(Trigger(
        name="disk_alert",
        description="Alerta quando disco > 90%",
        condition=_disk_alert_condition,
        action=_disk_alert_action,
        cooldown_s=3600,  # 1 hora
    ))

    # Trigger 2: Doctor degradado
    def _doctor_alert_condition() -> bool:
        if doctor_fn is None:
            return False
        try:
            report = doctor_fn()
            return report.get("overall") in ("degraded", "down")
        except Exception:  # noqa: BLE001
            return False

    def _doctor_alert_action() -> None:
        if doctor_fn is None:
            return
        try:
            report = doctor_fn()
            overall = report.get("overall", "ok")
            down = [c["name"] for c in report.get("checks", []) if c["status"] == "down"]
            degraded = [c["name"] for c in report.get("checks", []) if c["status"] == "degraded"]
            parts = []
            if down:
                parts.append(f"DOWN: {', '.join(down)}")
            if degraded:
                parts.append(f"DEGRADED: {', '.join(degraded)}")
            msg = f"🩺 Doctor: {overall} — {'; '.join(parts)}"
            if notify_fn:
                notify_fn(msg)
        except Exception:  # noqa: BLE001
            pass

    engine.register(Trigger(
        name="doctor_alert",
        description="Alerta quando doctor detecta serviços down/degraded",
        condition=_doctor_alert_condition,
        action=_doctor_alert_action,
        cooldown_s=600,  # 10 min
    ))

    # Trigger 3: CPU alta
    def _cpu_alert_condition() -> bool:
        return _load_avg() > 4.0

    def _cpu_alert_action() -> None:
        load = _load_avg()
        msg = f"⚠️ CPU load alto: {load:.1f}"
        if notify_fn:
            notify_fn(msg)

    engine.register(Trigger(
        name="cpu_alert",
        description="Alerta quando load 1min > 4.0 por 5min",
        condition=_cpu_alert_condition,
        action=_cpu_alert_action,
        cooldown_s=300,  # 5 min
    ))

    return engine
