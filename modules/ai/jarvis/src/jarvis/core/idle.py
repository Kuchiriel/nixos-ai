"""Modo idle do JARVIS — auto-manutenção quando o sistema está ocioso.

Fechamento do ciclo "ia de bordo que não fica parada": quando o usuário e a
máquina estão ociosos, o JARVIS roda self-knowledge (benchmark, regressão,
eval-rag) em segundo plano — o que alimenta o self-improve (o agente propõe
melhorias com base nos números, aprovadas via Telegram).

Mecanismos (pesquisados — ver assessment 4a):
  - **Detecção**: carga do sistema (sempre confiável) + `loginctl` IdleHint
    (quando o logind responde; se pendurado/ausente → desconhecido → decide
    pela carga). O worker NUNCA trava esperando o logind (timeout curto).
  - **Yield automático**: o serviço roda com CPUWeight=1/Nice=19/IO-idle —
    quando o usuário (ou um jogo) precisa de CPU, o kernel preempta o fundo.
    Não há necessidade de detectar jogo/Steam explicitamente.
  - **Heartbeat**: cada tarefa grava `state_dir/idle/<tarefa>.json` com o
    último run — a fila escolhe a tarefa mais atrasada (padrão do artigo
    "10 things I learned..." — corretude de aplicação, não só systemd).

O timer systemd (services/jarvis-idle.nix) roda `jarvis idle-worker --once`
a cada poucos minutos; o worker decide e executa NO MÁXIMO uma tarefa por
execução.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jarvis.core.config import Config, get_config


# ---------------------------------------------------------------------------
# Tarefas de self-knowledge (baratas, sem efeito colateral)
# ---------------------------------------------------------------------------

@dataclass
class IdleTask:
    name: str
    run: Callable[[], dict[str, Any]]
    min_interval_min: int  # intervalo mínimo entre execuções


def _task_benchmark() -> dict[str, Any]:
    from jarvis.core.benchmark import bench_report

    report = bench_report()
    return {
        "rotas": {r.get("route", "?"): r.get("ms") for r in report.get("resultados", [])},
        "total_ms": report.get("total_ms"),
    }


def _task_regression() -> dict[str, Any]:
    from jarvis.core.regression import main_regression

    code = main_regression(["--json"])
    return {"exit": code, "ok": code == 0}


def _task_eval_rag() -> dict[str, Any]:
    from jarvis.core.eval_rag import main_eval_rag

    code = main_eval_rag(["--json"])
    return {"exit": code, "ok": code == 0}


IDLE_TASKS: list[IdleTask] = [
    IdleTask("benchmark", _task_benchmark, 360),      # a cada 6h
    IdleTask("regression", _task_regression, 1440),   # diário
    IdleTask("eval-rag", _task_eval_rag, 1440),       # diário
]


# ---------------------------------------------------------------------------
# Detecção de idle
# ---------------------------------------------------------------------------

def load_is_low(max_load: float = 2.0) -> bool:
    """Carga média (1min) abaixo do teto — o gate primário e confiável."""
    try:
        return os.getloadavg()[0] < max_load
    except (OSError, AttributeError):
        return True


def user_is_idle(*, user: str | None = None, timeout: float = 3.0) -> bool | None:
    """IdleHint do logind; None = desconhecido (logind fora/pendurado).

    Nunca bloqueia: subprocess com timeout curto. Com o logind pendurado
    (VM pós-upgrade sem reboot), retorna None e o worker decide pela carga.
    """
    user = user or os.environ.get("USER", "") or os.environ.get("LOGNAME", "")
    if not user:
        return None
    try:
        out = subprocess.run(
            ["loginctl", "show-user", user, "-p", "IdleHint"],
            capture_output=True, text=True, timeout=timeout, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if "IdleHint=yes" in out:
        return True
    if "IdleHint=no" in out:
        return False
    return None


def is_idle(*, max_load: float = 2.0, idle_check: bool = True) -> bool:
    """Idle = carga baixa E (usuário idle OU logind desconhecido)."""
    if not load_is_low(max_load):
        return False
    if not idle_check:
        return True
    hint = user_is_idle()
    return hint is not False  # True ou desconhecido


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class IdleWorker:
    def __init__(
        self,
        config: Config | None = None,
        tasks: list[IdleTask] | None = None,
    ) -> None:
        self._cfg = config or get_config()
        self._tasks = tasks or IDLE_TASKS

    @property
    def state_dir(self) -> Path:
        return self._cfg.state_dir / "idle"

    def _heartbeat(self, name: str) -> Path:
        return self.state_dir / f"{name}.json"

    def _last_run(self, name: str) -> float:
        try:
            data = json.loads(self._heartbeat(name).read_text(encoding="utf-8"))
            return float(data.get("last", 0.0))
        except (OSError, ValueError):
            return 0.0

    def due_tasks(self, now: float | None = None) -> list[IdleTask]:
        now = now or time.time()
        due = []
        for task in self._tasks:
            elapsed_min = (now - self._last_run(task.name)) / 60.0
            if elapsed_min >= task.min_interval_min:
                due.append(task)
        return due

    def run_once(
        self,
        *,
        force: str | None = None,
        max_load: float = 2.0,
        idle_check: bool = True,
    ) -> dict[str, Any]:
        """Executa no máximo uma tarefa. `force` ignora o gate de idle."""
        if force:
            task = next((t for t in self._tasks if t.name == force), None)
            if task is None:
                return {"ran": False, "reason": f"tarefa desconhecida: {force}"}
        else:
            if not is_idle(max_load=max_load, idle_check=idle_check):
                return {"ran": False, "reason": "sistema ocupado"}
            due = self.due_tasks()
            if not due:
                return {"ran": False, "reason": "nada devido"}
            # a tarefa mais atrasada primeiro
            task = max(due, key=lambda t: time.time() - self._last_run(t.name))

        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = task.run()
        except Exception as exc:  # noqa: BLE001 — worker nunca quebra
            result = {"exit": -1, "error": str(exc)[:200]}

        heartbeat = {
            "last": time.time(),
            "result": result,
        }
        self._heartbeat(task.name).write_text(
            json.dumps(heartbeat, ensure_ascii=False), encoding="utf-8",
        )
        self._notify(task.name, result)
        return {"ran": True, "task": task.name, "result": result}

    def _notify(self, task_name: str, result: dict[str, Any]) -> None:
        """Avisa o usuário no Telegram quando uma tarefa de self-knowledge
        conclui (silencioso sem token). Ex: '📊 benchmark: 4/5 rotas OK'."""
        try:
            from jarvis.providers.telegram import send_notification

            ok = result.get("ok", result.get("exit", 0) == 0)
            status = "✅" if ok else "⚠️"
            send_notification(
                f"{status} Modo idle: {task_name} concluído"
                f" ({'ok' if ok else 'ver heartbeats'})"
            )
        except Exception:  # noqa: BLE001 — notificação nunca quebra o worker
            pass
