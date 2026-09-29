"""Harbor adapter — mapeamento instruction→runtime→context+ATIF (F10).

Sem harbor instalado (imports guarded) e sem LLM: FakeSession prova o
mapeamento; teste de presença prova a interface BaseAgent (name/version/
setup/run) casando com o guia custom-agents.
"""
import asyncio
import json as jsonlib

from jarvis.runtime import harbor_agent as ha


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, timeout=5):
        return FakeResponse({"data": [{"id": "m"}]})

    def post(self, url, json=None, timeout=120, **kw):
        self.calls += 1
        if self.calls == 1:
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{
                       "id": "c1", "type": "function",
                       "function": {"name": "execute_shell",
                                   "arguments": jsonlib.dumps(
                                       {"cmd": "echo hello"})}}]}
        else:
            msg = {"role": "assistant", "content": "done"}
        return FakeResponse({"choices": [{"message": msg}]})


class Ctx:
    """Espelho fiel do AgentContext real (harbor 0.23.0)."""

    def __init__(self):
        self.n_input_tokens = 0
        self.n_cache_tokens = 0
        self.n_output_tokens = 0
        self.cost_usd = 0.0
        self.model_usage = {}
        self.rollout_details = {}
        self.metadata = {}


class StrictCtx:
    """Como pydantic: atributo desconhecido = erro (regressão 28/09)."""

    def __init__(self):
        self.n_input_tokens = 0
        self.n_cache_tokens = 0
        self.n_output_tokens = 0
        self.cost_usd = 0.0
        self.model_usage = {}
        self.rollout_details = {}
        self.metadata = {}

    def __setattr__(self, name, value):
        if name.startswith("_") or name in self.__dict__ or name in (
                "n_input_tokens", "n_cache_tokens", "n_output_tokens",
                "cost_usd", "model_usage", "rollout_details", "metadata"):
            object.__setattr__(self, name, value)
        else:
            raise ValueError(f'"{type(self).__name__}" object has no field "{name}"')


def test_interface_matches_harbor_guide(tmp_path, monkeypatch) -> None:
    """name/version/setup/run com as assinaturas do guia custom-agents."""
    import inspect
    assert ha.JarvisHarborAgent.name() == "jarvis-kernel"
    assert ha.JarvisHarborAgent.SUPPORTS_ATIF is True
    sig = inspect.signature(ha.JarvisHarborAgent.run)
    assert list(sig.parameters) == ["self", "instruction", "environment",
                                    "context"]
    agent = ha.JarvisHarborAgent(logs_dir=tmp_path)
    asyncio.run(agent.setup(environment=None))
    assert agent.version() == "1.0.0"


def test_run_maps_runtime_to_context(tmp_path, monkeypatch) -> None:
    """instruction → runtime.run(FakeSession) → context + trajectory.json."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    import jarvis.runtime.agent_runtime as _rt

    real = _rt.AgentRuntime

    class RT(real):
        def __init__(self, *a, **k):
            super().__init__(*a, http_session=FakeSession(), **k)

    monkeypatch.setattr(_rt, "AgentRuntime", RT)
    agent = ha.JarvisHarborAgent(logs_dir=tmp_path)
    ctx = Ctx()
    asyncio.run(agent.run("do the thing", environment=None, context=ctx))
    assert ctx.metadata.get("turns", 0) >= 1
    traj = jsonlib.loads((tmp_path / "trajectory.json").read_text())
    assert traj["agent"] == "jarvis-kernel"
    assert "verdict" in traj and "steps" in traj
    sess = jsonlib.loads((tmp_path / "session.json").read_text())
    assert sess["task"] == "do the thing"


def test_run_survives_strict_context(tmp_path, monkeypatch) -> None:
    """Regressão 28/09 (A-cell real): context pydantic rejeita campo
    desconhecido — o adapter não pode matar o trial antes do verifier,
    e UNVERIFIED não levanta."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    import jarvis.runtime.agent_runtime as _rt

    real = _rt.AgentRuntime

    class RT(real):
        def __init__(self, *a, **k):
            super().__init__(*a, http_session=FakeSession(), **k)

    monkeypatch.setattr(_rt, "AgentRuntime", RT)
    agent = ha.JarvisHarborAgent(logs_dir=tmp_path)
    ctx = StrictCtx()
    asyncio.run(agent.run("do the thing", environment=None, context=ctx))
    assert ctx.metadata.get("verdict")
    assert "turns" in ctx.metadata


class FakeExecResult:
    def __init__(self, stdout="", stderr="", return_code=0):
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code


class FakeEnv:
    """Container fake: exec/upload async como o Harbor real."""

    def __init__(self):
        self.files = {"/app/src.txt": b"abc 123 \t\n"}
        self.cmds = []

    async def exec(self, command, timeout_sec=None):
        self.cmds.append(command)
        if command.startswith("base64 -- "):
            import base64 as _b64
            path = command[len("base64 -- "):].strip().strip("'\"")
            if path in self.files:
                return FakeExecResult(
                    stdout=_b64.b64encode(self.files[path]).decode())
            return FakeExecResult(stderr="not found", return_code=1)
        if command.startswith("ls -la -- "):
            return FakeExecResult(stdout="total 4\n-rw-r--r-- 1 root root 10 src.txt")
        if command.startswith("cat "):
            path = command[4:].strip()
            if path in self.files:
                return FakeExecResult(stdout=self.files[path].decode())
            return FakeExecResult(stderr="no such file", return_code=1)
        return FakeExecResult(stdout="ok")

    async def upload_file(self, source_path, target_path):
        with open(source_path, "rb") as f:
            self.files[target_path] = f.read()


def test_container_bridge_routes_into_env(tmp_path) -> None:
    """28/09 (A-cell): read/write/shell do agente operam DENTRO do
    container, não no host."""
    import jarvis.runtime.harbor_agent as _ham

    # A bridge tem loop próprio em thread dedicada: chamadas sync nunca
    # bloqueiam o loop do chamador (deadlock pago 28/09 no Harbor real,
    # que awaita agent.run() na thread do loop).
    env = FakeEnv()
    bridge = _ham._ContainerBridge(env)
    raw, _err = bridge.read("/app/src.txt")
    assert raw == b"abc 123 \t\n"
    assert bridge.read("/app/inexistente.txt")[0] is None
    cls = _ham._container_agent_class(env)
    cls._bridge = bridge
    out = cls._exec_read_file({"path": "/app/src.txt"})
    assert out.startswith("# /app/src.txt")
    assert "harness note" in out
    assert "src.txt" in cls._exec_list({"path": "/app"})
    assert "wrote" in cls._exec_write(
        "write_file", {"path": "/app/o.txt", "content": "x"})
    assert env.files["/app/o.txt"] == b"x"


def test_container_read_flags_binary() -> None:
    """29/09 (task2-bin): binário ilegível virava 'trailer' e o modelo
    copiava lixo. Agora o observation diz BINÁRIO + aponta shell."""
    import jarvis.runtime.harbor_agent as _ham

    class BinEnv(FakeEnv):
        def __init__(self):
            super().__init__()
            self.files["/app/b.bin"] = bytes(range(256))

    env = BinEnv()
    bridge = _ham._ContainerBridge(env)
    cls = _ham._container_agent_class(env)
    cls._bridge = bridge
    out = cls._exec_read_file({"path": "/app/b.bin"})
    assert "BIN" in out and "cp" in out
    assert "trailer" not in out


def test_bridge_warns_write_without_read() -> None:
    """29/09 (task3): modelo escreveu conteúdo imaginado sem ler o fonte.
    Redirect p/ dado nunca lido, sem leitura no cmd = RECUSADO;
    com leitura no cmd ou script novo = permitido."""
    import jarvis.runtime.harbor_agent as _ham

    class ShEnv(FakeEnv):
        async def exec(self, command, timeout_sec=None):
            self.cmds.append(command)
            return FakeExecResult(stdout="", stderr="", return_code=0)

    env = ShEnv()
    bridge = _ham._ContainerBridge(env)
    r = bridge.sh("echo hello > /app/line2.txt")
    assert r.return_code == 1 and "refused" in (r.stderr or "")
    assert "/app/line2.txt" not in " ".join(env.cmds)
    r2 = bridge.sh("cat /app/data.txt > /app/line2.txt")
    assert r2.return_code == 0
    r3 = bridge.sh("echo x > /app/run.sh")
    assert r3.return_code == 0


def test_bridge_counters_and_grounding() -> None:
    """29/09 (completion container-aware): a ponte conta execs/writes;
    COMPLETED sem nenhum exec no container = UNVERIFIED honesto."""
    import jarvis.runtime.harbor_agent as _ham

    env = FakeEnv()
    bridge = _ham._ContainerBridge(env)
    assert bridge.n_exec == 0 and bridge.n_writes == 0
    bridge.sh("cat /app/src.txt")
    assert bridge.n_exec == 1
    cls = _ham._container_agent_class(env)
    cls._bridge = bridge
    cls._exec_write("write_file", {"path": "/app/o.txt", "content": "x"})
    assert bridge.n_writes == 1 and bridge.written == ["/app/o.txt"]

    # Refusal não conta como exec (nada tocou o container).
    bridge2 = _ham._ContainerBridge(FakeEnv())
    r = bridge2.sh("echo hello > /app/line2.txt")
    assert r.return_code == 1
    assert bridge2.n_exec == 0
    assert "ONE shell command" in (r.stderr or "")

    # Gate: prosa-only COMPLETED → UNVERIFIED; com exec mantém.
    class Sess:
        termination = "COMPLETED"
        turns = 3
        model_id = "bonsai"
        verified = False
        missing = []
    ctx = Ctx()
    _ham.JarvisHarborAgent._fill_context(
        ctx, Sess(), 1.0,
        grounding={"n_exec": 0, "n_writes": 0,
                   "downgraded": "completed-without-container-exec"},
        verdict="UNVERIFIED")
    assert ctx.metadata["verdict"] == "UNVERIFIED"
    assert ctx.metadata["grounding"]["n_exec"] == 0
    ctx2 = Ctx()
    _ham.JarvisHarborAgent._fill_context(ctx2, Sess(), 1.0)
    assert ctx2.metadata["verdict"] == "COMPLETED"
    assert "grounding" not in ctx2.metadata
