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
import time
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
    "vibethinker": {"base_url": "http://127.0.0.1:8096/v1", "model": "vibethinker"},
    "tmax": {"base_url": "http://127.0.0.1:8096/v1", "model": "tmax"},
    # (15/11) O TERCEIRO BRAÇO — a API. O transcript (Codacus) mediu: "A 4B
    # planner with one expert handles SHORT jobs with a clear answer. For LONG
    # jobs, run the biggest single model your card can hold." O A* pathfinding
    # é job LONGO (5 etapas com deps) -> o local pequeno nao fecha. Entao o A/B
    # mede os tres: 8B ternario local, 4B MTP local e o forte da API.
    # Escolhi o deepseek-v4.1-flash: 73,2% em coding agentic real (bito),
    # MIT, Terminal-Bench 42,3 (o melhor da lista API da casa).
    # (17/11) O deepseek-v4.1-flash foi EOL em 16/11 ("reached its end of
    # life", HTTP 410 medido no nv-gate). O substituto medido: nemotron-3
    # ultra 550b — respondeu em 1,4s com content preenchido (o lightning 30b
    # devolveu content VAZIO e so reasoning, que quebra o parser do harness).
    "api": {"base_url": "http://127.0.0.1:8095/v1", "model": "nvidia/nemotron-3-ultra-550b-a55b"},
    # (18/11) Quarto braço: 35B MoE via NVIDIA NIM (Nemotron 3.5 Lightning 30B).
    # Mesmo endpoint da API (:8095), modelo MoE com expert offload.
    # Teste da hipótese #15: 35B MoE expert-cache vs 8B denso.
    "api-moe": {"base_url": "http://127.0.0.1:8095/v1", "model": "nvidia/nemotron-3.5-lightning-30b-a3b"},
}

# ── O PEDIDO ORIGINAL (a regra do video: o especialista ve o pedido inteiro) ──
TASK_TEXT = (
    "Make the enemy in src/dungeon/entities.py find its way to the player "
    "even when a wall blocks the direct line: the enemy must walk AROUND an "
    "internal wall and reach the player, and must never step into a wall. "
    "Any implementation is fine (A*, BFS, a rule table) — the checker "
    "measures the BEHAVIOUR, not the API, so do not guess a specific method "
    "name. Read the existing code before editing it; do not assume files "
    "exist."
)

# ── O CHECKER FIXADO (escrito antes e trancado) ──
# (16/11) CORRIGIDO: era "pytest test_astar.py", que ASSUME a API
# (enemy._a_star(...)). Com esse checker o A/B media "o modelo adivinhou o
# nome do metodo?" e nao "o modelo implementou o comportamento?" — o MTP
# chegou a implementar o comportamento e perdia so por nome. Agora usa o
# checker AGNOSTICO da casa (scripts/dungeon-checker.py, 444): mede que o
# inimigo chega no jogador contornando a parede interna.
CHECKER = "pytest -x -q checker.py  ->  4 passed (o veredito objetivo do A/B)"

# ── o que a task tem de tocar (o alvo do patch) ──
TARGET_FILES = ["src/dungeon/entities.py"]

# ── A ESCADA (17/11, medido) ─────────────────────────────────────────────
# Por que existe: com a tarefa L3 (contornar parede = pathfinding de
# verdade) os DOIS modelos locais falhavam 100% e o A/B nao media nada —
# falha na tarefa mais dificil nao distingue 8B de 4B. A escada da um
# degrau trivial (L1), um degrau local (L2) e o teto (L3), e o score passa
# a ser uma CURVA ("onde a capacidade acaba"), nao um binario.
#
# Cada nivel tem seu CHECKER proprio, escrivinhado antes e trancado (444).
# O baseline falha L1 (nao tem o metodo), falha L2 (trava no obstaculo) e
# falha L3 (parede inteira). Nenhum nivel e "de graca".
LEVELS = {
    "L1": {
        "texto": (
            "Add a method `distance_to(self, other)` to the `Enemy` class in "
            "src/dungeon/entities.py. It must return the Manhattan distance "
            "between the enemy and the other entity: "
            "abs(self.x - other.x) + abs(self.y - other.y). "
            "Do NOT change anything else in the file: no new behaviour, no "
            "renames, no pathfinding. Read the file first; do not assume."
        ),
        "checker": "dungeon-checker-l1.py",
        "aceite": "pytest -x -q checker.py  ->  5 passed (metodo puro)",
    },
    "L2": {
        "texto": (
            "In src/dungeon/entities.py, make `Enemy.update()` walk toward the "
            "player and NEVER step into a wall. When the direct step is "
            "blocked by a short obstacle, it must try another free direction "
            "instead of standing still, so it gets around a 3-cell wall and "
            "reaches the player. A local rule is enough (no A* needed). Read "
            "the existing code before editing; do not assume files exist."
        ),
        "checker": "dungeon-checker-l2.py",
        "aceite": "pytest -x -q checker.py  ->  4 passed (desvio local)",
    },
    "L3": {
        "texto": TASK_TEXT,
        "checker": "dungeon-checker.py",
        "aceite": CHECKER,
    },
    # (19/11) SERA/H3 — chunking com verifier por subtarefa (item #18).
    # Checkers validados: pre-A* falha, A* passa 5/5 em benchmarks/lab/.
    "L2A": {
        "texto": (
            "In src/dungeon/entities.py, make `Enemy.update()` actually MOVE "
            "toward the player (the Manhattan distance must decrease each tick) "
            "and never stand still while a free step exists. Read the file "
            "first. Do not add pathfinding: this chunk is only about moving."
        ),
        "checker": "checker-chunk-a.py",
        "aceite": "pytest -x -q checker.py  ->  5 passed (chunk A: move)",
    },
    "L2B": {
        "texto": (
            "In src/dungeon/entities.py, make `Enemy.update()` NEVER step into "
            "a wall. While walking toward the player, verify the candidate "
            "cell is free before moving. Read the file first; do not assume."
        ),
        "checker": "checker-chunk-b.py",
        "aceite": "pytest -x -q checker.py  ->  5 passed (chunk B: nao parede)",
    },
    "L2C": {
        "texto": (
            "In src/dungeon/entities.py, make `Enemy.update()` get around a "
            "short 3-cell wall: when the direct step is blocked, try a free "
            "lateral direction so it reaches the player. A local rule is "
            "enough (no A*). Read the file first; do not assume."
        ),
        "checker": "checker-chunk-c.py",
        "aceite": "pytest -x -q checker.py  ->  5 passed (chunk C: contorna)",
    },
}

NIVEL_PADRAO = os.environ.get("AB_LEVEL", "L3")
if NIVEL_PADRAO not in LEVELS:
    NIVEL_PADRAO = "L3"


def nivel_info(nivel: str | None = None) -> dict:
    return LEVELS.get(nivel or NIVEL_PADRAO, LEVELS["L3"])


def lane_name(modelo: str) -> str:
    """Nome do projeto-sandbox (resolve_project_root acha em ~/projects/<nome>)."""
    return f"dungeon-{modelo}"


def lane_path(modelo: str, nivel: str | None = None) -> Path:
    # (19/11) lane POR NIVEL: antes a lane (e a fila) eram as mesmas para
    # L1/L2/L3, entao o harness executava a task que sobrou na fila — a de
    # outro nivel. Medido: alternancia exata 5 passed/5 failed no L1.
    base = lane_name(modelo)
    if nivel:
        return WORKSPACE / f"{base}-{nivel.lower()}"
    return WORKSPACE / base


def ensure_lane(modelo: str, nivel: str | None = None) -> Path:
    """Cria o SANDBOX: uma COPIA do dungeon (a producao nao e tocada).

    (15/11) MEDIDO: com worktree o harness falha no retry — "Could not create
    branch for retry 1" — porque o harness cria um branch por task e o
    worktree ja tem um branch em uso (git nao deixa mexer). E o proprio video
    diz "copy the app into a sandbox, fix it there, then hand me a script".
    Entao: COPIA (o sandbox literal do video) — o agente edita a copia, a
    producao fica intacta, e o diff/commit da copia e o "script" pro dono.
    """
    lane = lane_path(modelo, nivel)
    if lane.exists():
        return lane
    if not DUNGEON_SRC.exists():
        raise SystemExit(f"dungeon nao encontrado: {DUNGEON_SRC}")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    if lane.exists():
        shutil.rmtree(lane)
    shutil.copytree(DUNGEON_SRC, lane, symlinks=True)
    # (19/11) SERA: o repo jarvis-dungeon tem A* desde e47e976. Sem isto o
    # agente herda a solucao e o A/B mede nada. AB_PRE_ASTAR=1 restaura o
    # movimento direto do commit 3432567 (baseline que os checkers esperam).
    if os.environ.get("AB_PRE_ASTAR") == "1":
        base = subprocess.run(
            ["git", "-C", str(DUNGEON_SRC), "show", "3432567:src/dungeon/entities.py"],
            capture_output=True, text=True, timeout=30)
        if base.returncode == 0 and base.stdout.strip():
            (lane / "src/dungeon/entities.py").write_text(base.stdout, encoding="utf-8")
    shutil.rmtree(lane / ".git", ignore_errors=True)
    # o harness cria branch por task: o sandbox precisa ser um repo git
    subprocess.run(["git", "-C", str(lane), "init", "-q"], check=True, timeout=60)
    subprocess.run(["git", "-C", str(lane), "add", "-A"], check=True, timeout=120)
    subprocess.run(["git", "-C", str(lane), "-c", "user.email=lane@local",
                    "-c", "user.name=lane", "commit", "-q", "-m",
                    "sandbox: copia do jarvis-dungeon (baseline)"],
                   check=True, timeout=120)
    # (16/11) O CHECKER AGNOSTICO vai para a lane, TRANCADO (444), junto com
    # o baseline. O agente nao pode ver nem mexer no veredito — e o checker
    # mede o comportamento (o inimigo contorna a parede), nao um nome de
    # metodo especifico.
    checker_src = None
    if not (lane / "checker.py").exists():
        alvo = nivel_info(nivel)["checker"]
        for parent in Path(__file__).resolve().parents:
            cand = parent / "scripts" / alvo
            if cand.exists():
                checker_src = cand
                break
    if checker_src is not None:
        dest = lane / "checker.py"
        shutil.copy2(checker_src, dest)
        dest.chmod(0o444)
        subprocess.run(["git", "-C", str(lane), "add", "-A"], check=True, timeout=60)
        subprocess.run(["git", "-C", str(lane), "-c", "user.email=lane@local",
                        "-c", "user.name=lane", "commit", "-q", "-m",
                        "checker: o veredito objetivo (trancado)"],
                       check=True, timeout=60)
    return lane


def enqueue(modelo: str, nivel: str | None = None) -> dict:
    """Enfileira a task do dungeon NA FILA DO SISTEMA (TaskQueue)."""
    if modelo not in MODELOS:
        raise SystemExit(f"modelo desconhecido: {modelo}")
    nivel = nivel or NIVEL_PADRAO
    if nivel not in LEVELS:
        raise SystemExit(f"nivel desconhecido: {nivel}")
    info = nivel_info(nivel)
    lane = ensure_lane(modelo, nivel)
    queue = TaskQueue(project=lane_name(modelo) + (f"-{nivel.lower()}" if nivel else ""))
    # (17/11) ID UNICO POR CORRIDA. Antes era sempre "dungeon-ab-<modelo>":
    # o harness encontrava a task ANTIGA (failed, com attempts acumulados) e
    # entrava em "Recovering" — o A/B media a mesma task fracassada para
    # sempre, e o retry nunca partia de um estado limpo (medido no log).
    task = Task(
        id=f"dungeon-ab-{modelo}-{nivel}-{int(time.time())}",
        project=lane_name(modelo) + (f"-{nivel.lower()}" if nivel else ""),
        description=info["texto"],    # o PEDIDO ORIGINAL, inteiro
        priority=1,                   # a primeira da fila
        risk="medium",
        target_files=list(TARGET_FILES),
        acceptance_criteria=info["aceite"],  # o CHECKER FIXADO
        repository=str(lane),         # o sandbox (a producao fica intacta)
        language="python",
    )
    ok = queue.add_task(task)
    return {
        "modelo": modelo,
        "nivel": nivel,
        "lane": str(lane),
        "task_id": task.id,
        "add_task": ok,
        "fila": str(getattr(queue, "path", "") or ""),
        "nota": ("task ja estava na fila" if not ok else "task enfileirada"),
    }


def run(modelo: str, max_tasks: int = 1, nivel: str | None = None) -> dict:
    """Roda o HARNESS DO SISTEMA (o proprio nightwatch) contra o lane.

    Nao ha agente novo aqui: e o nightwatch de sempre, com a task da fila e o
    modelo do A/B. O `use_llm_discovery=False` garante que ele pegue a nossa
    task e nao invente outras (o scripted discovery fica ligado, mas nossa
    task tem priority=1 e o max_tasks=1).
    """
    import dataclasses

    from nightwatch.harness import Harness, HarnessConfig

    nivel = nivel or NIVEL_PADRAO
    cfg_model = MODELOS[modelo]
    lane = ensure_lane(modelo, nivel)
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
        "project": lane_name(modelo) + (f"-{nivel.lower()}" if nivel else ""),
        "max_tasks": max_tasks,
        "max_retries": 2,
        "llm_base_url": cfg_model["base_url"],
        "llm_model": cfg_model["model"],
        "telegram_notifications": False,
        "use_llm_discovery": False,
        # (19/11) MEDIDO: o scripted discovery continuava ligado e criava tasks
        # proprias (5 tasks) que TOMAVAM a precedencia da nossa -> o lab rodava
        # L3 quando mandamos L1 ("Found 5 tasks"). O lab mede UMA task do nivel;
        # descoberta livre mede outra coisa. Desliga as duas fontes.
        "use_scripted_discovery": False,
        "auto_approve": True,
        "projects": [lane_name(modelo) + (f"-{nivel.lower()}" if nivel else "")],
        "strict_projects": True,
    }
    # so passa os campos que existem nesta versao do HarnessConfig
    validos = {f.name for f in dataclasses.fields(HarnessConfig)}
    pedido = {k: v for k, v in pedido.items() if k in validos}

    harness = Harness(HarnessConfig(**pedido))
    resultado = harness.run()
    return {
        "modelo": modelo,
        "nivel": nivel,
        "lane": str(lane),
        "resultado": str(resultado)[:600],
    }


def report() -> dict:
    """Le o veredito das DUAS filas (o que o sistema registrou)."""
    saida = {"modelos": {}}
    for modelo in MODELOS:
        projeto = lane_name(modelo) + (f"-{nivel.lower()}" if nivel else "")
        queue = TaskQueue(project=projeto)
        tasks = queue.get_tasks_by_project(projeto)
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
    saida["niveis"] = sorted(LEVELS)
    saida["nivel_padrao"] = NIVEL_PADRAO
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
        p.add_argument("--level", default=NIVEL_PADRAO, choices=sorted(LEVELS),
                       help="degrau da escada (default: $AB_LEVEL ou L3)")
    sub.add_parser("report")
    args = ap.parse_args()

    if args.cmd == "report":
        out = report()
    elif args.cmd == "enqueue":
        out = enqueue(args.model, args.level)
    else:
        out = run(args.model, nivel=args.level)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
