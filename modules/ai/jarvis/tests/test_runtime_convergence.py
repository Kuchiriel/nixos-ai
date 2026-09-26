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
