"""Linter estrutural da convergência p/ o Agent Runtime Kernel (ADR-005).

Filosofia (mesma de test_architecture_invariants.py): falhar ALTO quando a
arquitetura divergir do contrato, nunca passar silenciosamente com drift.

Fase 1: trava o estado ATUAL fragmentado com tetos explícitos. Cada fase da
reconstrução APERTA estes tetos (3 loops → 2 → 1). TARGET marcado em cada teste.
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
JARVIS = SRC / "jarvis"

# Arquivos que hoje contêm loop cognitivo próprio (for-range sobre turnos).
# TARGET F8: só jarvis/runtime/agent_runtime.py.
_COGNITIVE_LOOPS = {
    "jarvis/core/agent.py": "Agent.run",
    "jarvis/cli/dev.py": "_run_agent_loop",
    "nightwatch/harness.py": "Harness.execute_task",
}


def _has_turn_loop(path: Path) -> bool:
    text = path.read_text()
    return "for turn in range(" in text or "for attempt in range(" in text


def test_cognitive_loops_are_known_and_bounded() -> None:
    """Teto: nenhum NOVO loop cognitivo pode surgir sem atualizar este teste.

    TARGET: 1 (runtime/agent_runtime.py). Hoje: 3. Se este teste falha porque
    um 4º arquivo ganhou loop de turnos, a reconstrução REGREDIU.
    """
    found = {rel for rel in _COGNITIVE_LOOPS if _has_turn_loop(SRC / rel)}
    assert found == set(_COGNITIVE_LOOPS), (
        f"loops cognitivos mudaram: {found} — atualizar plano de convergência")
    assert len(found) == 3, f"esperado 3 loops na Fase 1, achado {len(found)}"


def test_llm_chokepoint_is_single_client() -> None:
    """Todo loop cognitivo chama o LLM via LLMClient (nunca backend direto).

    TARGET: 1 call-site (runtime). Hoje: agent+dev+harness via LLMClient —
    o choke point EXISTE, precisa ser PRESERVADO durante a extração.
    """
    import re
    users: set[str] = set()
    for rel in list(_COGNITIVE_LOOPS) + ["jarvis/core/router.py", "jarvis/core/rag.py",
                                         "jarvis/core/memory.py", "jarvis/core/vault.py"]:
        text = (SRC / rel).read_text()
        if "LLMClient" in text:
            users.add(rel)
    # os 3 loops + 3 providers legítimos usam LLMClient; router delega p/
    # MCPClient/HybridSearch e NUNCA toca LLM direto (verificado 26/09).
    # backend direto = 0 em todos os loops.
    for rel in _COGNITIVE_LOOPS:
        text = (SRC / rel).read_text()
        assert "LlamaCppBackend(" not in text and "PrismMLBackend(" not in text, (
            f"{rel} instancia backend LLM direto — choke point violado")
    assert users == {"jarvis/core/agent.py", "jarvis/cli/dev.py", "nightwatch/harness.py",
                      "jarvis/core/rag.py", "jarvis/core/memory.py",
                      "jarvis/core/vault.py"}, f"usuários de LLMClient mudaram: {users}"


def test_registry_covers_both_dialects() -> None:
    """ToolRegistry cobre a UNIÃO dos dialetos (nada se perde na leitura)."""
    from jarvis.core import devtools
    from jarvis import mcp_server
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    dev_names = {e["function"]["name"] for e in devtools.DEV_TOOLS}
    mcp_names = {e["name"] for e in mcp_server.JARVIS_TOOLS}
    from jarvis.runtime.registry import _CANONICAL_ALIASES

    def canon(n: str) -> str:
        return _CANONICAL_ALIASES.get(n, n.removeprefix("jarvis_"))

    for n in dev_names:
        assert canon(n) in reg.tools, f"DEV_TOOLS.{n} fora do registry"
    for n in mcp_names:
        assert canon(n) in reg.tools, f"JARVIS_TOOLS.{n} fora do registry"


def test_known_divergences_are_tracked() -> None:
    """Lista FECHADA de divergências SILENT (TARGET: vazia — atingido na F4).

    F2 mergeou str_replace no transporte (alias declarado). F4 mergeou o
    EXECUTOR de semantic_search (devtools delega p/ HybridSearch — o caminho
    com RRF+rerank) e declarou limit→top_k. Critério: obrigatórios
    normalizados iguais = transporte, não fork. Qualquer NOVA entrada = falha.
    """
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    silent = {d.canonical for d in reg.dialect_report()}
    assert silent == set(), f"silent regrediu: {silent}"
    assert set(reg.declared_aliases()) == {"str_replace", "semantic_search"}


def test_semantic_search_delegates_to_hybrid() -> None:
    """F4: executor único — devtools.semantic_search USA HybridSearch.

    Estrutural (anti-drift: reintroduzir Qdrant próprio quebra) +
    comportamental (mapeamento HybridHit → contrato preservado).
    """
    import inspect
    from jarvis.core import devtools
    from jarvis.core import rag

    src = inspect.getsource(devtools.semantic_search)
    assert "HybridSearch" in src, "executor paralelo reintroduzido"
    assert "QdrantStore" not in src, "fachada paralela reintroduzida"

    real_hs = rag.HybridSearch

    class Hit:
        def __init__(self, path, score, payload):
            self.path = path
            self.score = score
            self.payload = payload

    class FakeHS:
        def __init__(self, *a, **k):
            pass

        def search(self, query, *, top_k=5):
            assert query == "q" and top_k == 3
            return [Hit("a.py", 0.91234, {"content": "x" * 500}),
                    Hit("", 0.5, {"book": "b", "kind": "k"})]

    rag.HybridSearch = FakeHS
    try:
        out = devtools.semantic_search("q", top_k=3)
    finally:
        rag.HybridSearch = real_hs
    assert out["ok"] is True and out["total"] == 2 and out["query"] == "q"
    assert out["results"][0] == {"text": "x" * 300, "score": 0.912,
                                 "source": "a.py"}
    assert out["results"][1]["source"] == "b"  # book antes de kind
    assert devtools.semantic_search("") == {"ok": False, "error": "Empty query"}
    assert devtools.semantic_search("   ")["ok"] is False


def test_resolve_translates_str_replace() -> None:
    """Transporte MCP → canônico: renames sem esmagar chaves existentes."""
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    canon, targs = reg.resolve("jarvis_str_replace", {
        "path": "f", "old_string": "A", "new_string": "B"})
    assert canon == "str_replace"
    assert targs == {"path": "f", "old": "A", "new": "B"}
    # explícito canônico vence alias (nunca esmaga)
    _, t2 = reg.resolve("jarvis_str_replace", {
        "path": "f", "old": "X", "old_string": "A", "new_string": "B"})
    assert t2["old"] == "X" and t2["new"] == "B"
    # desconhecido passa intacto (executor decide o erro)
    c3, t3 = reg.resolve("jarvis_nope", {"a": 1})
    assert (c3, t3) == ("nope", {"a": 1})


def test_mcp_str_replace_roundtrip(tmp_path) -> None:
    """REGRESSÃO F2: jarvis_str_replace via MCP estava MORTO (KeyError/
    args-ausentes — o executor esperava old/new, o transporte enviava
    old_string/new_string). Prova viva no caminho real."""
    import json
    from jarvis.mcp_server import call_tool

    f = tmp_path / "mcp.txt"
    f.write_text("AAA-BBB", encoding="utf-8")
    out = json.loads(call_tool("jarvis_str_replace", {
        "path": str(f), "old_string": "AAA", "new_string": "CCC"}))
    assert out.get("ok") is True, out
    assert f.read_text(encoding="utf-8") == "CCC-BBB"


def test_single_schema_emission() -> None:
    """Uma emissão de schema: 1 entrada por ferramenta canônica, sem prefixo."""
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    emitted = reg.to_openai_tools()
    names = [e["function"]["name"] for e in emitted]
    assert len(names) == len(set(names)), "schema emitido tem duplicata"
    assert not any(n.startswith("jarvis_") for n in names), (
        "schema canônico não usa prefixo jarvis_")
    assert len(names) == len(reg.tools)


# ---------------------------------------------------------------------------
# F5: contrato único de completion (vocabulário de veredito)
# ---------------------------------------------------------------------------

def test_verdict_vocabulary_is_closed() -> None:
    """5 palavras, nem uma a mais (TARGET atingido na F5).

    Todo DONE/SKIP/FAIL do sistema — Agent, dev, Nightwatch — fala VERIFIED/
    UNVERIFIED/STUCK/FAILED/DEFERRED. Inventar 'SUCCESS'/'DONE'/'COMPLETED'
    como veredito = falha aqui.
    """
    from jarvis.core.completion import (
        VERDICTS, verdict_for_outcome, verdict_for_task_status)
    from nightwatch.task_queue import Task, TaskStatus

    assert VERDICTS == {"VERIFIED", "UNVERIFIED", "STUCK", "FAILED",
                        "DEFERRED"}
    # todo TaskStatus mapeia (nenhum ciclo de vida sem veredito)
    for st in TaskStatus:
        v = verdict_for_task_status(st.value)
        assert v in VERDICTS, f"{st.value} sem veredito"
    assert verdict_for_task_status("COMPLETED") == "VERIFIED"
    assert verdict_for_task_status("ABANDONED") == "DEFERRED"
    assert verdict_for_task_status("IN_PROGRESS") == "UNVERIFIED"
    # outcomes do supervisor
    assert verdict_for_outcome("completed").status == "VERIFIED"
    assert verdict_for_outcome("evidence_failed").status == "UNVERIFIED"
    assert verdict_for_outcome("loop").status == "STUCK"
    assert verdict_for_outcome("paused").status == "DEFERRED"
    assert verdict_for_outcome("whatever").status == "FAILED"
    # propriedade computada (sem persistência: asdict não a inclui)
    t = Task(id="t", project="p", description="d")
    t.status = TaskStatus.COMPLETED.value
    assert t.verdict == "VERIFIED"
    assert "verdict" not in t.to_dict()
    t.status = TaskStatus.ABANDONED.value
    assert t.verdict == "DEFERRED"


def test_no_invented_verdict_semantics() -> None:
    """Ninguém redefine semântica de DONE fora de completion.py."""
    import re
    allowed_files = {"completion.py", "task_queue.py", "agent.py", "dev.py",
                     "main.py", "harness.py"}
    bad: list[str] = []
    for p in list((SRC / "jarvis").rglob("*.py")) + list((SRC / "nightwatch").rglob("*.py")):
        if p.name in allowed_files:
            continue
        try:
            text = p.read_text()
        except Exception:
            continue
        for m in re.finditer(
                r'verdict\s*=\s*["\']([A-Z_]+)["\']', text):
            if m.group(1) not in ("VERIFIED", "UNVERIFIED", "STUCK",
                                   "FAILED", "DEFERRED"):
                bad.append(f"{p.name}: {m.group(0)}")
    assert bad == [], f"semântica de veredito inventada: {bad}"


# ---------------------------------------------------------------------------
# F6: choke point único de seleção de modelo
# ---------------------------------------------------------------------------

def test_model_selection_chokepoint() -> None:
    """Toda seleção p/ execução passa pelo funil do runtime (TARGET: 1+n
    adapters declarados). Hoje: só Agent.run. dev usa perfil (registry) e
    nightwatch usa gate de RAM — quando selectionarem, entram aqui e este
    teste é atualizado junto (nunca por fora)."""
    import re
    funnel: set[str] = set()
    bypass: set[str] = set()
    for p in list((SRC / "jarvis").rglob("*.py")):
        if p.name in ("model_policy.py", "policy.py"):
            continue
        try:
            text = p.read_text()
        except Exception:
            continue
        rel = p.relative_to(SRC).as_posix()
        if re.search(r"(?<![\w.])select_model_for_task\(", text):
            funnel.add(rel)
        if re.search(r"(?<![\w.])select_model\(", text):
            bypass.add(rel)
    assert funnel == {"jarvis/core/agent.py"}, (
        f"funil com callers inesperados: {funnel}")
    assert bypass == set(), (
        f"seleção direta fora do funil: {bypass}")


def test_dead_routing_policy() -> None:
    """provider_registry.route() tem 0 callers (DEPRECATED F6).

    Se alguém religar fallback cloud, este teste força a passar pelo funil
    do runtime + revisão de ADR — nunca ressuscitar silenciosamente."""
    import re
    callers: list[str] = []
    for p in list((SRC / "jarvis").rglob("*.py")):
        if p.name in ("provider_registry.py",):
            continue
        try:
            text = p.read_text()
        except Exception:
            continue
        for m in re.finditer(r"(?<![\w.])route_for_persona\(|(?<![\w.])route\(",
                             text):
            if "test_dead_routing" in text[max(0, m.start() - 200):m.start()]:
                continue
            callers.append(f"{p.relative_to(SRC)}: {m.group(0)}")
    callers = [c for c in callers if "test_runtime_convergence" not in c]
    assert callers == [], f"política morta religada: {callers}"


def test_funnel_preserves_decision() -> None:
    """O funil não decide — delega e carimba provenance."""
    from jarvis.runtime.policy import select_model_for_task

    seen: list = []
    mid, reason = select_model_for_task(
        {"capabilities": ["tools"]}, caller="probe",
        emit=lambda e, **k: seen.append((e, k)))
    assert isinstance(mid, str) and mid
    assert isinstance(reason, dict)
    assert seen and seen[0][0] == "model_selected"
    assert seen[0][1]["detail"]["caller"] == "probe"
    assert seen[0][1]["detail"]["model"] == mid


def test_registry_dispatch_executes(tmp_path) -> None:
    """Transporte genérico: dispatch resolve + executa (volta None p/
    conceito sem executor devtools)."""
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    f = tmp_path / "d.txt"
    f.write_text("AAA", encoding="utf-8")
    import json
    out = json.loads(reg.dispatch(
        "jarvis_str_replace",
        {"path": str(f), "old_string": "AAA", "new_string": "BBB"}))
    assert out.get("ok") is True
    assert f.read_text(encoding="utf-8") == "BBB"
    assert reg.dispatch("jarvis_nope", {}) is None
    # metadados §6 presentes
    t = reg.tools["str_replace"]
    assert t.handler.startswith("devtools:")
    assert t.verify == "world:file-exists"
    assert reg.tools["read_file"].verify == "none"


def test_for_task_filters_by_capability() -> None:
    """Disclosure estrutural: com capabilities, só elas; sem, tudo."""
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    all_names = {t.name for t in reg.for_task()}
    assert "read_file" in all_names and "execute_shell" in all_names
    ro = {t.name for t in reg.for_task(capabilities=["filesystem.read"])}
    assert "read_file" in ro and "execute_shell" not in ro
    assert reg.for_task(capabilities=["nope"]) == []


# ---------------------------------------------------------------------------
# F9: identidade única (PersonaRegistry) + matriz canônica
# ---------------------------------------------------------------------------

def test_persona_matrix_canonical() -> None:
    """CAPABILITY_TOOLS só fala canônico (F9): toda entrada existe no
    ToolRegistry, sem prefixo jarvis_, sem fantasma (rag_search→
    semantic_search, read_ai_conversation removido). E toda capability
    usada por personas existe na matriz (cap órfã = persona sem tools)."""
    from jarvis.core.persona import CAPABILITY_TOOLS, PersonaRegistry
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    have = set(reg.tools)
    for cap, names in CAPABILITY_TOOLS.items():
        for n in names:
            assert not n.startswith("jarvis_"), (
                f"dialeto morto na matriz: {cap} -> {n}")
            assert n in have, f"fantasma na matriz: {cap} -> {n}"
    caps_used: set[str] = set()
    for p in PersonaRegistry().list_all():
        caps_used.update(getattr(p, "tools", []) or [])
    orphans = caps_used - set(CAPABILITY_TOOLS)
    assert orphans == set(), f"capabilities órfãs em personas: {orphans}"


def test_single_identity_in_dev_mode() -> None:
    """F9: /mode com roleDefinition SUBSTITUI a persona (nunca empilha).

    Estrutural: o handler usa _rebuild_system("") no caminho com role
    (uma identidade) e preserva a persona no caminho só-instruções.
    """
    import inspect
    from jarvis.cli import dev as _devmod

    src = inspect.getsource(_devmod)
    assert "def _rebuild_system" in src
    # caminho role: rebuild sem persona + bloco MODE
    assert '_rebuild_system("")' in src, "modo-role voltou a empilhar"
    # caminho instruções: rebuild COM persona + framing MODE
    assert "_rebuild_system(_persona_block(active_persona))" in src


# ---------------------------------------------------------------------------
# F7: fronteira supervisor/loop + runtime único
# ---------------------------------------------------------------------------

def test_supervisor_does_not_own_the_loop() -> None:
    """Nightwatch é supervisor: consome contratos, nunca o loop do Agent.

    Trava: harness.py não importa Agent (nem constrói); o único compositor
    do loop é runtime/agent_runtime.py. Quando o supervisor chamar
    runtime.run (F7b, com prova em bateria), este teste ganha o caller.
    """
    import re
    harness = (SRC / "nightwatch/harness.py").read_text()
    assert "from jarvis.core.agent import" not in harness, (
        "supervisor importando o loop — fronteira violada")
    assert re.search(r"(?<![\w.])Agent\(", harness) is None, (
        "supervisor construindo Agent — usar runtime.run (F7b)")

    composers: set[str] = set()
    for p in list((SRC / "jarvis").rglob("*.py")):
        if p.name in ("agent.py", "agent_runtime.py"):
            continue
        try:
            text = p.read_text()
        except Exception:
            continue
        if re.search(r"(?<![\w.])Agent\(", text):
            composers.add(p.relative_to(SRC).as_posix())
    tests_ok = {c for c in composers if "/tests/" in c or "test_" in c}
    # F8: todos os compositores migrados p/ runtime.run (router, main CLI,
    # 2 benchmarks). Novo Agent() fora do runtime = falha.
    assert composers - tests_ok == set(), (
        f"compositor do loop fora do runtime: {composers - tests_ok}")


def test_no_tool_nudge_once_then_accept(monkeypatch) -> None:
    """A/B 29/09: texto final sem nenhuma tool na sessão ganhava RC 0
    direto. Agora: 1 nudge limitado, depois aceita (Q&A em texto continua
    funcionando)."""
    import jarvis.cli.dev as _dev

    calls = {"n": 0}

    def _fake_call(messages, tools, profile, debug=False):
        calls["n"] += 1
        return {"choices": [{"message": {"role": "assistant",
                                         "content": "done.",
                                         "tool_calls": None}}]}

    monkeypatch.setattr(_dev, "_call_llm", _fake_call)
    msgs: list = [{"role": "system", "content": "s"},
                  {"role": "user", "content": "diga done"}]
    ok = _dev._run_agent_loop(msgs, [], {"name": "tiny"}, approve=True,
                              max_turns=5)
    assert ok is True
    assert calls["n"] == 2, "1 nudge + resposta final"
    systems = [m.get("content", "") for m in msgs if m.get("role") == "system"]
    assert any("not used ANY tool" in s for s in systems)


def test_friction_without_success_is_honest_rc(monkeypatch) -> None:
    """29/09: texto final após nudge COM EVIDÊNCIA (claim), zero tools com
    sucesso = RC 1 (antes: RC 0 desonesto). Q&A puro segue RC 0."""
    import jarvis.cli.dev as _dev

    answers = {"n": 0}

    def _fake_call(messages, tools, profile, debug=False):
        answers["n"] += 1
        text = ("done." if answers["n"] != 2
                else "o arquivo /tmp/x.txt foi criado com sucesso")
        return {"choices": [{"message": {"role": "assistant",
                                         "content": text,
                                         "tool_calls": None}}]}

    monkeypatch.setattr(_dev, "_call_llm", _fake_call)
    msgs: list = [{"role": "system", "content": "s"},
                  {"role": "user", "content": "crie o arquivo /tmp/x.txt"}]
    ok = _dev._run_agent_loop(msgs, [], {"name": "tiny"}, approve=True,
                              max_turns=6)
    assert ok is False, "claim falso + zero tools = não entregue"
    # Q&A puro: no-tool nudge dispara, mas sem evidência de trabalho
    # pendente o RC segue 0.
    answers["n"] = 0

    def _fake_qa(messages, tools, profile, debug=False):
        return {"choices": [{"message": {"role": "assistant",
                                         "content": "olá, tudo bem.",
                                         "tool_calls": None}}]}

    monkeypatch.setattr(_dev, "_call_llm", _fake_qa)
    msgs2: list = [{"role": "system", "content": "s"},
                   {"role": "user", "content": "oi"}]
    ok2 = _dev._run_agent_loop(msgs2, [], {"name": "tiny"}, approve=True,
                               max_turns=5)
    assert ok2 is True, "Q&A puro segue RC 0"


def test_writes_ok_tracks_shell_redirects_and_cp(monkeypatch) -> None:
    """29/09: claim-checker só via write_file — shell (`>`, `cp`)
    passava batido. Alvos de redirect + destino de cp entram no rastreio."""
    import jarvis.cli.dev as _dev

    script = [
        {"choices": [{"message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "function": {
                "name": "execute_shell",
                "arguments": '{"cmd": "sed -n 2p /a.txt > /b.txt"}'}}]}}]},
        {"choices": [{"message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c2", "function": {
                "name": "execute_shell",
                "arguments": '{"cmd": "cp /b.txt /c.txt"}'}}]}}]},
        {"choices": [{"message": {"role": "assistant",
                                  "content": "done.",
                                  "tool_calls": None}}]},
    ]
    state = {"n": 0}

    def _fake_call(messages, tools, profile, debug=False):
        r = script[min(state["n"], 2)]
        state["n"] += 1
        return r

    monkeypatch.setattr(_dev, "_call_llm", _fake_call)
    monkeypatch.setattr(_dev, "_execute_tool_call",
                        lambda *a, **k: ("ok", ""))
    monkeypatch.setattr(_dev, "_validated_output",
                        lambda *a, **k: a[2] if len(a) > 2 else "ok")
    msgs: list = [{"role": "system", "content": "s"},
                  {"role": "user", "content": "go"}]
    ok = _dev._run_agent_loop(msgs, [], {"name": "tiny"}, approve=True,
                              max_turns=6)
    # "done." vazio após shell-only: verdict-nudge suspeita (conservador) —
    # o que importa aqui é o rastreio, não o RC.
    assert ok is False
    assert "/b.txt" in _dev._run_agent_loop._writes_ok
    assert "/c.txt" in _dev._run_agent_loop._writes_ok


def test_write_guard_refuses_unread_overwrite(tmp_path, monkeypatch) -> None:
    """29/09 (missão): write_file full em arquivo existente nunca lido =
    RECUSADO; após read_file = permitido; criação livre."""
    import jarvis.cli.dev as _dev

    src = tmp_path / "data.txt"
    src.write_text("aaa\n")
    monkeypatch.chdir(tmp_path)
    _dev._run_agent_loop._reads_ok = []

    out, _ = _dev._execute_tool_call(
        "write_file", {"path": "data.txt", "content": "x"}, approve=True)
    assert out.startswith("ERROR") and "never" in out
    assert src.read_text() == "aaa\n"

    _dev._execute_tool_call("read_file", {"path": "data.txt"}, approve=True)
    out2, _ = _dev._execute_tool_call(
        "write_file", {"path": "data.txt", "content": "x"}, approve=True)
    assert not out2.startswith("ERROR")
    out3, _ = _dev._execute_tool_call(
        "write_file", {"path": "novo.txt", "content": "x"}, approve=True)
    assert not out3.startswith("ERROR")


def test_prose_only_detection_and_fence_escalation(monkeypatch) -> None:
    """29/09 (R1-distill): modelo sem template de tool responde pedindo o
    arquivo. 1º nudge genérico; 2º turno vira superfície bash-first."""
    import jarvis.cli.dev as _dev

    assert _dev._looks_like_prose_only(
        "Por favor, me envie o arquivo input.csv") is True
    assert _dev._looks_like_prose_only(
        "```bash\ncat a.txt\n```") is False
    assert _dev._looks_like_prose_only("resposta curta") is False

    script = [
        "Preciso que voce me envie o arquivo.",
        "Preciso que voce me envie o arquivo.",
    ]
    state = {"n": 0}

    def _fake_call(messages, tools, profile, debug=False):
        r = script[min(state["n"], 1)]
        state["n"] += 1
        return {"choices": [{"message": {"role": "assistant",
                                         "content": r, "tool_calls": None}}]}

    monkeypatch.setattr(_dev, "_call_llm", _fake_call)
    msgs: list = [{"role": "system", "content": "s"},
                  {"role": "user", "content": "conserta o csv"}]
    _dev._run_agent_loop(msgs, [], {"name": "default"}, approve=True,
                         max_turns=4)
    systems = [m.get("content", "") for m in msgs if m.get("role") == "system"]
    assert any("ONE fenced block" in s for s in systems)
    assert _dev._run_agent_loop._fence_hinted == 1


def test_repeated_error_nudge_inspects_data(monkeypatch) -> None:
    """29/09 (R1-distill): mesmo comando falha 2x → 1 nudge manda
    inspecionar o dado real em vez de repetir (bounded 1x)."""
    import jarvis.cli.dev as _dev

    script = [
        {"choices": [{"message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": "c1", "function": {
                        "name": "execute_shell",
                        "arguments": '{"cmd": "python3 process.py input.csv"}'}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": "c2", "function": {
                        "name": "execute_shell",
                        "arguments": '{"cmd": "python3 process.py input.csv"}'}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "done.",
                                  "tool_calls": None}}]},
    ]
    state = {"n": 0}

    def _fake_call(messages, tools, profile, debug=False):
        r = script[min(state["n"], 2)]
        state["n"] += 1
        return r

    monkeypatch.setattr(_dev, "_call_llm", _fake_call)
    monkeypatch.setattr(_dev, "_execute_tool_call",
                        lambda *a, **k: ("ERROR: IndexError: list index", None))
    msgs: list = [{"role": "system", "content": "s"},
                  {"role": "user", "content": "roda o script"}]
    _dev._run_agent_loop(msgs, [], {"name": "default"}, approve=True,
                         max_turns=6)
    systems = [m.get("content", "") for m in msgs if m.get("role") == "system"]
    assert any("SAME error" in s for s in systems)
    assert _dev._run_agent_loop._err_nudged == 1


def test_to_text_history_flattens_tool_protocol() -> None:
    """29/09 (R1-distill): template deepseek-v3 degenera com role='tool'.
    Achatar vira conversa legível (observação como texto)."""
    import jarvis.cli.dev as _dev

    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "rode"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "execute_shell",
                                      "arguments": '{"cmd": "cat a"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "alpha\nbeta"},
        {"role": "assistant", "content": "pronto"},
    ]
    flat = _dev._to_text_history(msgs)
    assert all(m["role"] in ("system", "user", "assistant") for m in flat)
    assert not any(m.get("tool_calls") for m in flat)
    a = flat[2]
    assert a["role"] == "assistant"
    assert "commands run" in a["content"] and "cat a" in a["content"]
    assert "output of c1" in a["content"] and "alpha" in a["content"]
    assert flat[-1]["content"] == "pronto"


def test_sed_in_is_allowed_but_hard_never_still_blocks(tmp_path, monkeypatch) -> None:
    """29/09 (missão): `sed -i` é a correção legítima e estava fora do
    allowlist. Liberado; HARD-NEVER e jail continuam valendo."""
    from jarvis.core.security import (DEFAULT_ALLOWED_PREFIXES,
                                      command_allowed, command_forbidden)

    assert any(p.startswith("sed -i") for p in DEFAULT_ALLOWED_PREFIXES)
    assert command_allowed("sed -i 's/a/b/' data.txt") is True
    assert command_forbidden("rm -rf /nix/store/x") is not None
    assert command_forbidden("sed -i 's/a/b/' /nix/store/x") is not None


def test_error_nudge_injects_real_content(tmp_path, monkeypatch) -> None:
    """29/09: o nudge de erro repetido anexa o conteúdo real do arquivo
    citado (modelo que só repete comando não tem o dado)."""
    import jarvis.cli.dev as _dev

    (tmp_path / "input.csv").write_text("id,val\n1,10\n5;50\n")
    monkeypatch.chdir(tmp_path)

    script = [
        {"choices": [{"message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": "c1", "function": {
                        "name": "execute_shell",
                        "arguments": '{"cmd": "python3 process.py input.csv"}'}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": "c2", "function": {
                        "name": "execute_shell",
                        "arguments": '{"cmd": "python3 process.py input.csv"}'}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "fim.",
                                  "tool_calls": None}}]},
    ]
    state = {"n": 0}

    def _fake_call(messages, tools, profile, debug=False):
        r = script[min(state["n"], 2)]
        state["n"] += 1
        return r

    monkeypatch.setattr(_dev, "_call_llm", _fake_call)
    monkeypatch.setattr(_dev, "_execute_tool_call",
                        lambda *a, **k: ("ERROR: IndexError", None))
    msgs: list = [{"role": "system", "content": "s"},
                  {"role": "user", "content": "roda o script"}]
    _dev._run_agent_loop(msgs, [], {"name": "default"}, approve=True,
                         max_turns=6)
    systems = [m.get("content", "") for m in msgs if m.get("role") == "system"]
    assert any("REAL CONTENT" in s and "5;50" in s for s in systems), \
        "conteudo real do input tem que chegar no nudge"


def test_zero_width_does_not_break_tool_parse() -> None:
    """29/09 (missão MoE): tokenizer emite U+200B após `<` nas tags
    Hermes — o parser falhava e a resposta virava vazia."""
    import jarvis.cli.dev as _dev

    raw = ("pronto<tool_call>\n<function=write_file>\n"
           "<parameter=content>550</parameter>\n"
           "<parameter=path>total.txt</parameter>\n"
           "</function>\n</tool_call>")
    acts = _dev._parse_text_actions(raw)
    assert acts == [{"name": "write_file",
                     "arguments": {"content": "550", "path": "total.txt"}}]
    assert _dev._strip_zero_width("a<b") == "a<b"


def test_sampling_comes_from_registry_not_greedy(monkeypatch) -> None:
    """29/09: o REPL hardcodava temperature 0.0 e descartava o sampling
    medido que já vivia no registry. Greedy é anti-padrão em reasoning
    (DeepSeek-R1/Qwen3 pedem 0.6-1.0)."""
    import jarvis.cli.dev as _dev

    monkeypatch.delenv("JARVIS_SAMPLING", raising=False)
    s = _dev._sampling_for_model("jarvis-fast")
    assert s.get("temperature") == 0.7, s
    assert s.get("top_p") == 0.8 and s.get("top_k") == 20, s
    assert s.get("presence_penalty") == 1.5, s
    # Bonsai não é greedy por acidente também.
    assert _dev._sampling_for_model("bonsai").get("temperature") == 0.5
    # A/B explícito para experimento.
    monkeypatch.setenv("JARVIS_SAMPLING", "greedy")
    assert _dev._sampling_for_model("jarvis-fast") == {"temperature": 0.0}
    monkeypatch.setenv("JARVIS_SAMPLING", "default")
    assert _dev._sampling_for_model("jarvis-fast") == {"temperature": 0.0}
    # Idempotente no payload: top_p etc. não vazam min_p/repetition.
    prof = {"temperature": 0.7, "top_p": 0.8, "top_k": 20,
            "presence_penalty": 1.5, "min_p": 0.0, "repetition_penalty": 1.0}
    extra = {k: prof[k] for k in ("top_p", "top_k", "presence_penalty")
             if prof.get(k) is not None}
    assert "min_p" not in extra and "repetition_penalty" not in extra


def test_verdict_nudge_fires_in_english(monkeypatch) -> None:
    """29/09 (mission-kit): o filtro de artefato casava só PT-BR. Em EN o
    mundo diz "doesn't exist yet" e o nudge nunca disparava — segurança
    desligada quando o dono escreve em inglês."""
    from jarvis.core.completion import CompletionVerdict
    import jarvis.cli.dev as _dev

    calls = {"n": 0}

    def _fake_call(messages, tools, profile, debug=False):
        calls["n"] += 1
        if calls["n"] == 1:
            tc = [{"id": "c1", "type": "function",
                   "function": {"name": "read_file",
                                "arguments": '{"path": "spec.txt"}'}}]
            return {"choices": [{"message": {"role": "assistant",
                                             "content": "", "tool_calls": tc}}]}
        return {"choices": [{"message": {
            "role": "assistant", "tool_calls": None,
            "content": "The sum is 6."}}]}

    class _FakeCC:
        @staticmethod
        def check_completion(messages):
            return CompletionVerdict(
                "UNVERIFIED", [],
                ["prompt requires answer.txt which doesn't exist yet "
                 "— create it if it's a deliverable"])

    import jarvis.core.completion as _comp
    monkeypatch.setattr(_comp, "check_completion",
                        _FakeCC.check_completion)
    monkeypatch.setattr(_dev, "_call_llm", _fake_call)
    monkeypatch.setattr(_dev, "_execute_tool_call",
                        lambda *a, **k: ("spec contents", None))
    msgs: list = [{"role": "system", "content": "s"},
                  {"role": "user", "content": "sum the DATA line, write "
                                              "the number to answer.txt"}]
    _dev._run_agent_loop(msgs, [], {"name": "small"}, approve=True,
                         max_turns=5)
    systems = [m.get("content", "") for m in msgs if m.get("role") == "system"]
    assert any("NOT satisfied" in s or "answer.txt" in s for s in systems), \
        "nudge de veredito TEM que disparar com texto EN"
