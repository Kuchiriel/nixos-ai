"""Mission subsystem — Telegram-driven multi-agent mission control.

Layering (the functional contract from the spec, mapped onto existing
mechanisms rather than new parallel ones):

    Telegram (interface)      jarvis/providers/telegram.py
    Authorization policy      jarvis/core/authz.py          (new)
    Project identity          jarvis/mission/projects.py    (new)
    Decomposition             jarvis/mission/planner.py     (new)
    Durable state             jarvis/mission/store.py       (new)
    Execution                 jarvis/mission/runner.py      (new)
                              -> jarvis/runtime/agent_runtime.py (canonical loop)
    Supervision/recovery      jarvis/mission/store.py (recover_interrupted)
    Verification/attribution  jarvis/mission/verify.py      (new)
    Events                    jarvis/core/eventbus.py, control_plane/notifications.py

There is deliberately NO second cognitive loop here: the runner delegates
each task to `AgentRuntime`.
"""

from jarvis.mission.models import (
    AcceptanceCriterion,
    FailureClass,
    Mission,
    MissionState,
    MissionTask,
    TaskState,
)
from jarvis.mission.store import MissionStore
from jarvis.mission.projects import ResolvedProject, resolve, scoped_files
from jarvis.mission.planner import build_mission, decompose_heuristic
from jarvis.mission.runner import MissionRunner, RunOutcome
from jarvis.mission.verify import VerificationResult, verify_task

__all__ = [
    "AcceptanceCriterion",
    "FailureClass",
    "Mission",
    "MissionState",
    "MissionTask",
    "MissionStore",
    "MissionRunner",
    "RunOutcome",
    "ResolvedProject",
    "TaskState",
    "VerificationResult",
    "build_mission",
    "decompose_heuristic",
    "resolve",
    "scoped_files",
    "verify_task",
]