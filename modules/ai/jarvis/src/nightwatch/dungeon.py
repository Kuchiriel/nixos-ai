"""dungeon.py — o A/B do jarvis-dungeon DENTRO do sistema novo (15/11).

POR QUE ESTE MODULO E NAO UM SCRIPT SOLTO
----------------------------------------
O legado (`~/projects/team/`) tinha: personas (`bots/`, `roles/`), uma fila
com dono (`queue.md`, protocolo "nobody is the router"), handoff em arquivo
(`handoff.sh` -> `handoffs/<id>.md`) e reports por tarefa. O sistema NOVO tem
TUDO isso, e mais:

  fila         -> nightwatch.task_queue.TaskQueue (persistente, por projeto,
                  com status/attempts/evidence/commit_sha)
  sandbox      -> nightwatch.project_isolation (+ worktree por lane)
  edicao segura-> nightwatch.safe_editor.SafeEditor
  avaliador    -> nightwatch.evaluator (roda os testes do projeto)
  checkpoint   -> nightwatch.checkpoint
  painel       -> scripts/agent-hub.mjs (o painel novo)
  orquestracao -> coord_roster.send_message (com o PEDIDO ORIGINAL anexado)

Entao este modulo NAO reimplementa nada: ele usa a fila do sistema para
enfileirar a task e o Harness do proprio nightwatch para executa-la. O painel
dispara este modulo; o modulo roda o sistema.

O QUE O A/B COMPARA (medido no legado)
--------------------------------------
O legado rodou o dungeon com o BONSAI e deu 8 FAIL em 10 (07/10) + 2 PASS
depois (15-16/10). O plano do agente era bom (5 etapas com dependencias),
mas a execucao era ruim: o passo 1 era "assumir que o arquivo existe" em vez
de LER, e o raciocinio saia em ingles num contexto PT-BR. O dono: "foi feito
com bonsai ainda modelo ruim em ptbr e erra muito, hoje temos qwen 4b mtp".

As 3 licoes do video que viram regra aqui:
  1. o especialista precisa ver o PEDIDO ORIGINAL -> a `description` da task
     e o pedido INTEIRO (nao um resumo);
  2. o PLANEJADOR e o elo fraco -> quem planeja tem de ter modelo forte;
  3. sandbox + checker -> o agente edita o LANE (worktree), a producao
     (~/projects/jarvis-dungeon) fica intacta, e o veredito vem do checker
     fixado ANTES (pytest test_astar.py, 4/4).

CLI:
    python3 -m nightwatch.dungeon enqueue --model mtp
    python3 -m nightwatch.dungeon run --model mtp
    python3 -m nightwatch.dungeon report
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from nightwatch.task_queue import Task, TaskQueue

# ── o hardware e o repositorio de origem ──
DUNGEON_SRC = Path(os.environ.get("JARVIS_DUNGEON_SRC", str(Path.home() / "projects/jarvis-dungeon")))
WORKSPACE = Path(os.environ.get("JARVIS_WORKSPACE_ROOT", str(Path.home() / "projects")))

# ── os dois modelos do A/B (medidos HOJE na casa) ──
MODELOS = {
    "bonsai": {"base_url": "http://127.0.0.1:8080/v1", "model": "bonsai"},
    # (15/11, dono) O MTP tem DOIS perfis (exclusivos por VRAM):
    #   mtp-code = SEM o LoRA microturn -> CODING/TESTES (o harness).
    #              MEDIDO: com o LoRA carregado o patcher de 4k tokens dava
    #              TIMEOUT — o LoRA e o classificador de VOZ (phone call).
    #   mtp-lora = COM o LoRA -> a phone call (a voz).
    "mtp": {"base_url": "http://127.0.0.1:8096/v1", "model": "jarvis-mtp-code"},
    "mtp-lora": {"base_url": "http://127.0.0.1:8092/v1", "model": "jarvis-mtp-lora"},
    "vibethinker": {"base_url": "http://127.0.0.1:8098/v1", "model": "vibethinker"},
    # (15/11) O TERCEIRO BRAÇO — a API. O transcript (Codacus) mediu: "A 4B
    # planner with one expert handles SHORT jobs with a clear answer. For LONG
    # jobs, run the biggest single model your card can hold." O A* pathfinding
    # é job LONGO (5 etapas com deps) -> o local pequeno nao fecha. Entao o A/B
    # mede os tres: 8B ternario local, 4B MTP local e o forte da API.
    # Escolhi o deepseek-v4.1-flash: 73,2% em coding agentic real (bito),
    # MIT, Terminal-Bench 42,3 (o melhor da lista API da casa).
    "api": {"base_url": "http://127.0.0.1:8095/v1", "model": "deepseek-ai/deepseek-v4.1-flash"},
}

# ── O PEDIDO ORIGINAL (a regra do video: o especialista ve o pedido inteiro) ──
TASK_TEXT = (
    "Implement A* pathfinding for enemies in src/dungeon/entities.py. "
    "The Enemy class must use heapq to compute a path to the player, "
    "recalculate the path when the target moves, and fall back to simple "
    "movement when no path is found. "
    "The unit tests in test_astar.py must pass (4/4). "
    "Read the existing code before editing it; do not assume files exist."
)

# ── O CHECKER FIXADO (escrito antes e trancado) ──
CHECKER = "pytest -x -q test_astar.py  ->  4 passed (o veredito objetivo do A/B)"

# ── o que a task tem de tocar (o alvo do patch) ──
TARGET_FILES = ["src/dungeon/entities.py"]


def lane_name(modelo: str) -> str:
    """Nome do projeto-sandbox (resolve_project_root acha em ~/projects/<nome>)."""
    return f"dungeon-{modelo}"


def lane_path(modelo: str) -> Path:
    return WORKSPACE / lane_name(modelo)


def ensure_lane(modelo: str) -> Path:
    """Cria o SANDBOX: uma COPIA do dungeon (a producao nao e tocada).

    (15/11) MEDIDO: com worktree o harness falha no retry — "Could not create
    branch for retry 1" — porque o harness cria um branch por task e o
    worktree ja tem um branch em uso (git nao deixa mexer). E o proprio video
    diz "copy the app into a sandbox, fix it there, then hand me a script".
    Entao: COPIA (o sandbox literal do video) — o agente edita a copia, a
    producao fica intacta, e o diff/commit da copia e o "script" pro dono.
    """
    lane = lane_path(modelo)
    if lane.exists():
        return lane
    if not DUNGEON_SRC.exists():
        raise SystemExit(f"dungeon nao encontrado: {DUNGEON_SRC}")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    if lane.exists():
        shutil.rmtree(lane)
    shutil.copytree(DUNGEON_SRC, lane, symlinks=True)
    shutil.rmtree(lane / ".git", ignore_errors=True)
    # o harness cria branch por task: o sandbox precisa ser um repo git
    subprocess.run(["git", "-C", str(lane), "init", "-q"], check=True, timeout=60)
    subprocess.run(["git", "-C", str(lane), "add", "-A"], check=True, timeout=120)
    subprocess.run(["git", "-C", str(lane), "-c", "user.email=lane@local",
                    "-c", "user.name=lane", "commit", "-q", "-m",
                    "sandbox: copia do jarvis-dungeon (baseline)"],
                   check=True, timeout=120)
    return lane


def enqueue(modelo: str) -> dict:
    """Enfileira a task do dungeon NA FILA DO SISTEMA (TaskQueue)."""
    if modelo not in MODELOS:
        raise SystemExit(f"modelo desconhecido: {modelo}")
    lane = ensure_lane(modelo)
    queue = TaskQueue(project=lane_name(modelo))
    task = Task(
        id=f"dungeon-ab-{modelo}",
        project=lane_name(modelo),
        description=TASK_TEXT,        # o PEDIDO ORIGINAL, inteiro
        priority=1,                   # a primeira da fila
        risk="medium",
        target_files=list(TARGET_FILES),
        acceptance_criteria=CHECKER,  # o CHECKER FIXADO
        repository=str(lane),         # o sandbox (a producao fica intacta)
        language="python",
    )
    ok = queue.add_task(task)
    return {
        "modelo": modelo,
        "lane": str(lane),
        "task_id": task.id,
        "add_task": ok,
        "fila": str(getattr(queue, "path", "") or ""),
        "nota": ("task ja estava na fila" if not ok else "task enfileirada"),
    }


def run(modelo: str, max_tasks: int = 1) -> dict:
    """Roda o HARNESS DO SISTEMA (o proprio nightwatch) contra o lane.

    Nao ha agente novo aqui: e o nightwatch de sempre, com a task da fila e o
    modelo do A/B. O `use_llm_discovery=False` garante que ele pegue a nossa
    task e nao invente outras (o scripted discovery fica ligado, mas nossa
    task tem priority=1 e o max_tasks=1).
    """
    import dataclasses

    from nightwatch.harness import Harness, HarnessConfig

    cfg_model = MODELOS[modelo]
    lane = ensure_lane(modelo)
    if modelo == "api":
        # (15/11) MEDIDO: o backend "remote" da casa (jarvis/providers/
        # llm_factory.py) pede a chave via ENV: JARVIS_LLM_BACKEND=remote +
        # JARVIS_REMOTE_BASE_URL + JARVIS_REMOTE_API_KEY (a regra da casa: a
        # chave NUNCA no codigo). Sem isso o harness batia em 401.
        import os as _os
        _os.environ["JARVIS_LLM_BACKEND"] = "remote"
        _os.environ["JARVIS_REMOTE_BASE_URL"] = cfg_model["base_url"]
        envf = _os.path.expanduser("~/.config/opencode/keys.env")
        try:
            for line in open(envf, encoding="utf-8"):
                line = line.strip()
                if line.startswith("NVIDIA_API_KEY="):
                    _os.environ["JARVIS_REMOTE_API_KEY"] = (
                        line.split("=", 1)[1].strip().strip('"'))
                    break
        except Exception:
            pass
    # o harness le o modelo do ambiente/config
    os.environ["JARVIS_LLM_BASE_URL"] = cfg_model["base_url"]
    os.environ["JARVIS_LLM_MODEL"] = cfg_model["model"]
    os.environ["JARVIS_DISABLE_THINKING"] = "1"

    pedido = {
        "project": lane_name(modelo),
        "max_tasks": max_tasks,
        "max_retries": 2,
        "llm_base_url": cfg_model["base_url"],
        "llm_model": cfg_model["model"],
        "telegram_notifications": False,
        "use_llm_discovery": False,
        "auto_approve": True,
        "projects": [lane_name(modelo)],
        "strict_projects": True,
    }
    # so passa os campos que existem nesta versao do HarnessConfig
    validos = {f.name for f in dataclasses.fields(HarnessConfig)}
    pedido = {k: v for k, v in pedido.items() if k in validos}

    harness = Harness(HarnessConfig(**pedido))
    resultado = harness.run()
    return {
        "modelo": modelo,
        "lane": str(lane),
        "resultado": str(resultado)[:600],
    }


def report() -> dict:
    """Le o veredito das DUAS filas (o que o sistema registrou)."""
    saida = {"modelos": {}}
    for modelo in MODELOS:
        queue = TaskQueue(project=lane_name(modelo))
        tasks = queue.get_tasks_by_project(lane_name(modelo))
        linhas = []
        for t in tasks:
            evidence = t.evidence[-4:] if isinstance(t.evidence, list) else []
            linhas.append({
                "id": t.id,
                "status": t.status,
                "attempts": t.attempts,
                "erro": (t.last_error or "")[:300],
                "validacao": (t.last_validation or "")[:400],
                "evidence": [str(e)[:200] for e in evidence],
            })
        saida["modelos"][modelo] = linhas
    saida["checker"] = CHECKER
    saida["pedido_original"] = TASK_TEXT
    return saida


def _reexec_com_ambiente() -> None:
    """Se o interpretador atual nao tem `requests`, re-executa no nix develop.

    (15/11) MEDIDO: o `python3` do profile (`/etc/profiles/per-user/nixos/bin/python3`)
    aponta para o python do nix store SEM `requests` -> `import nightwatch.harness`
    morre. O que tem `requests` e o `python3-*-env`. Em vez de hardcodar um
    caminho do nix store (que muda a cada build), o modulo se re-executa
    dentro do `nix develop` do repo — que e o ambiente oficial.
    """
    import importlib.util
    if importlib.util.find_spec("requests") is not None:
        return
    if os.environ.get("NIGHTWATCH_DUNGEON_REEXEC") == "1":
        raise SystemExit("nem o nix develop tem requests: ambiente quebrado")
    repo = str(Path(__file__).resolve().parents[4])
    env = dict(os.environ)
    env["NIGHTWATCH_DUNGEON_REEXEC"] = "1"
    env["PYTHONPATH"] = repo + "/modules/ai/jarvis/src" + (
        (":" + os.environ["PYTHONPATH"]) if os.environ.get("PYTHONPATH") else "")
    os.execvpe("nix", ["nix", "develop", "-c", sys.executable, "-m",
                       "nightwatch.dungeon"] + sys.argv[1:], env)


def main() -> int:
    _reexec_com_ambiente()
    ap = argparse.ArgumentParser(description="A/B do jarvis-dungeon (fila + harness do sistema novo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("enqueue", "run"):
        p = sub.add_parser(nome)
        p.add_argument("--model", required=True, choices=sorted(MODELOS))
    sub.add_parser("report")
    args = ap.parse_args()

    if args.cmd == "report":
        out = report()
    elif args.cmd == "enqueue":
        out = enqueue(args.model)
    else:
        out = run(args.model)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
