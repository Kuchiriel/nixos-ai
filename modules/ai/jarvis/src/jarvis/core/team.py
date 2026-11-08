"""team.py — a equipe: quem pega o quê, com que personalidade e com que modelo.

POR QUE ESTE MÓDULO (dono, 07/11)
----------------------------------
O dono quer um TIME de IAs (várias de noite, com nomes e personalidades)
trabalhando nos projetos e na vida pessoal — e não um agente sozinho. Isso
exige três decisões que hoje estão espalhadas (ou não existem):

  1. **PERSONALIDADE POR TAREPA (MBTI fluido)**: a personalidade não é
     rótulo fixo — ela acompanha o trabalho. Base medida: o paper
     "Personality-Guided Code Generation" (arXiv 2411.00006) mostra que
     alinhar a personalidade COM A TAREFA aumenta o pass rate (+3,94% na
     média com a descrição completa do tipo; até +12,9%), e o
     "MBTI-in-Thoughts" (arXiv 2509.04343, ETH) mostra que o priming
     produz desvios de comportamento REPRODUZÍVEIS — o que permite um
     time com papéis distintos. "Structured Personality Control and
     Adaptation" (arXiv 2601.10025) dá o mecanismo do "fluido": persona
     base + compensação temporária pela tarefa.
  2. **MODELO POR TAREPA**: o catálogo de modelos é grande (local + API) e
     o recurso é escasso (VRAM de 6 GB, 1 LLM por vez; free tier com
     rate gate). A escolha é feita pela DIFICULDADE (o registry já tem
     `select_model_for_task`) e pela DISPONIBILIDADE (rate limit em curso).
  3. **IDENTIDADE**: cada agente se identifica (o bloco IDENTITY do harness
     é a única fonte — o AGENTS.md é explícito: nunca adivinhar). O roster
     carrega o modelo; o bus mostra; afleet sabe quem é quem.

NÃO É UM ORQUESTRADOR AUTÔNOMO: isto escolhe e prepara. Quem executa é o
opencode (sessão real, tools, MCP, skills), o watcher (wake) e o bus
(auditabilidade). A regra do AGENTS.md continua valendo: nada heavy sem
checar RAM/VRAM, 1 LLM por vez, e nunca digitar no input do humano.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# ── 1. perfis de tarefa → (persona, MBTI, porque) ───────────────────────
# O alinhamento tarefa×personalidade é o que o paper mediu; os tipos são
# escolhidos pelo que o papel FAZ (não pelo gosto):
#   ISTP — depurar/executar: prático, resolve no fait
#   INTJ — arquitetura/estratégia: Systems Thinking (o paper do harness)
#   INTP — pesquisa/investigar: análise de hipóteses
#   ENTJ — coordenar/planejar:指挥 + foco no objetivo
#   INFJ — documentar/explicar:写入理解 (contexto e intenção)
#   ESTJ — operação/rotina: execução e disciplina
#   ENTP — criar/explorar alternativas: divergent thinking
TASK_PROFILES: dict[str, tuple[str, str, str]] = {
    "debug": ("ISTP", "debug", "execução prática: reproduzir, medir, corrigir"),
    "arquitetura": ("INTJ", "architect", "systems thinking: padrão, consequência, prazo"),
    "pesquisa": ("INTP", "researcher", "hipótese, evidência, contra-exemplo"),
    "coord": ("ENTJ", "supervisor", "organizar o time e fechar o que está aberto"),
    "documentacao": ("INFJ", "technical_writer", "contexto e intenção para quem lê depois"),
    "operacao": ("ESTJ", "devops_engineer", "rotina, disciplina, serviço de pé"),
    "criacao": ("ENTP", "cto", "alternativas e trade-offs (divergent thinking)"),
}

# Ordem de conferência (a primeira que casa vence).
# MEDIDO 07/11: o `\\b` no FIM do grupo matava os PREFIXOS ("arquitetar"
# nao casa com "arquitet\\b") — a tarefa caia no tipo errado. Agora cada
# raiz aceita sufixo (\\w*) e o limite fica so no comeco.
TASK_PATTERNS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("debug", (r"\b(bug\w*|erro\w*|exception\w*|traceback\w*|falha\w*|quebr\w*|regress\w*|stack\w*|debug\w*)\b", "deprec")),
    ("arquitetura", (r"\b(arquitet\w*|design\w*|refactor\w*|modelo de dados|schema\w*|scaling\w*)\b", "deprec")),
    ("pesquisa", (r"\b(pesquis\w*|investig\w*|benchmark\w*|paper\w*|arxiv\w*|medid\w*|experiment\w*|rags?)\b", "deprec")),
    ("documentacao", (r"\b(doc\w*|readme\w*|ag\.md|manual\w*|tutorial\w*|explic\w*|escrev\w*)\b", "deprec")),
    ("operacao", (r"\b(deploy\w*|servi\w*|systemd\w*|monitor\w*|alert\w*|backup\w*|manuten\w*|liveness\w*|health\w*)\b", "deprec")),
    ("criacao", (r"\b(criar\w*|idei\w*|proposta\w*|novo feature\w*)\b", "deprec")),
    ("coord", (r"\b(coorden\w*|organiz\w*|prioriz\w*|divid\w*|equipe\w*|time\w*|agentes?\w*)\b", "deprec")),
)

# ── 2. o modelo: catálogo do registry + tier + rate limit ───────────────
def registry_models() -> list[dict[str, Any]]:
    """Os modelos do registry (models.nix é a fonte da verdade).

    O registry é o do ROUTER llama-server (:8080) — os modelos LOCAIS
    (bonsai, qwen3-4b, o MTP, o 35B...). Os modelos de API (nvidia, groq,
    gemini…) são outra lista: a do opencode (providers no opencode.json) e
    a do free-providers.json (o cascade). As duas entram na escolha, com
    o peso da sombra do local/privado.
    """
    out: list[dict[str, Any]] = []
    try:
        from jarvis.core.model_registry import registry_or_none

        reg = registry_or_none()
        if reg is not None:
            for mid in reg.ids():
                e = reg.get(mid)
                out.append(
                    {
                        "id": mid,
                        "provider_id": "local",
                        "model_id": mid,
                        "tier": getattr(e, "tier", "") or "",
                        "capability": len(getattr(e, "capabilities", ()) or ()),
                        "vram_mb": getattr(e, "vram_mb", 0) or 0,
                        "local": True,
                    }
                )
    except Exception:
        pass
    # Os providers de API (a fonte do cascade): provider/model + tier.
    try:
        import json

        path = Path(__file__).resolve().parents[4] / "free-providers.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for pname, p in (data.get("providers") or {}).items():
            for mm in (p.get("models") or []):
                mid = mm.get("id") or mm.get("name") or ""
                if not mid:
                    continue
                out.append(
                    {
                        "id": f"{pname}/{mid}",
                        "provider_id": pname,
                        "model_id": mid,
                        "tier": "api",
                        "capability": 0,
                        "local": False,
                    }
                )
    except Exception:
        pass
    return out


def available_models(include_local: bool = True) -> list[dict[str, Any]]:
    """Os modelos que dá para usar AGORA (filtra cooldown de rate limit)."""
    out = []
    for m in registry_models():
        mid = f"{m.get('provider_id', '')}/{m.get('model_id', '')}".strip("/")
        if not include_local and mid.startswith("local"):
            continue
        if _in_cooldown(mid):
            continue
        out.append(m)
    return out


def _in_cooldown(model_id: str, minutes: int = 10) -> bool:
    """O provider caiu em 429/tempo limite há pouco? (o guard avisa por log)"""
    try:
        log = Path(
            os.environ.get("JARVIS_STATE_DIR", "~/.local/state/jarvis")
        ).expanduser() / "provider-cooldown.json"
        if not log.is_file():
            return False
        import json
        import time

        data = json.loads(log.read_text(encoding="utf-8"))
        stamp = float(data.get(model_id, 0) or 0)
        return stamp > 0 and (time.time() - stamp) < minutes * 60
    except Exception:
        return False


def model_for_task(text: str, models: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """(modelo, porque) para a tarefa. Difficulty-first, cooldown-aware."""
    models = models if models is not None else available_models()
    # Defesa em profundidade: mesmo com a lista ja filtrada, NUNCA escolher
    # um modelo em cooldown (o guard do provider avisa; trocar e obrigatorio).
    vivos = [m for m in models
             if not _in_cooldown(m.get("id") or
                                f"{m.get('provider_id','')}/{m.get('model_id','')}")]
    if vivos:
        models = vivos
    if not models:
        return "", "sem modelo disponível (registry vazio ou tudo em cooldown)"
    kind, _profile = classify(text)
    hard = kind in ("debug", "arquitetura", "pesquisa", "coord")
    scored: list[tuple[float, str, str]] = []
    for m in models:
        mid = m.get("id") or f"{m.get('provider_id', '')}/{m.get('model_id', '')}".strip("/")
        if not mid:
            continue
        score = 0.0
        # Local = barato e PRIVADO: ganha quando a tarefa não é pesada.
        if m.get("local") or mid.startswith("local"):
            score += 2.0 if not hard else 0.5
        # Capacidade declarada (o registry mede): ajuda, mas não decide.
        cap = float(m.get("capability") or m.get("score") or 0)
        score += min(cap, 10.0) / 10.0
        if hard and cap >= 7:
            score += 1.5
        # Free tier com rate gate: entra depois (o gate segura, mas 429 atrasa).
        if "free" in str(m.get("tier", "")):
            score -= 0.3
        scored.append((score, mid, str(m.get("tier") or "")))
    scored.sort(reverse=True)
    if not scored:
        return "", "nenhum modelo com id"
    best = scored[0]
    return best[1], (
        f"tipo={kind}; escolhido por dificuldade+capacidade+disponibilidade "
        f"(tier={best[2] or '-'}, score={best[0]:.2f})"
    )


# ── 3. a pessoa: personality + agent + model para a tarefa ──────────────
def classify(text: str) -> tuple[str, tuple[str, str, str]]:
    """(tipo_da_tarefa, (mbti, persona_id, porque))"""
    low = (text or "").lower()
    for kind, (pattern, _flag) in TASK_PATTERNS:
        if re.search(pattern, low, re.I):
            return kind, TASK_PROFILES[kind]
    return "operacao", TASK_PROFILES["operacao"]


def persona_for_task(text: str) -> tuple[str, str, str]:
    """(mbti, persona_id, porque) — a personalidade que acompanha a tarefa."""
    kind, (mbti, pid, why) = classify(text)
    return mbti, pid, f"{kind}: {why}"


def assign(text: str, agents: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """O plano: quem pega, com que personalidade, com que modelo.

    `agents` = a lista viva (comms.live_agents()). Escolhe o agente com
    MENOS escopo declarado (o mais livre), ou o mais próximo da lane da
    tarefa; a personalidade vem do tipo da tarefa; o modelo do catálogo
    disponível (cooldown-aware).
    """
    from jarvis.core import comms

    agents = agents if agents is not None else comms.live_agents()
    mbti, pid, why = persona_for_task(text)
    model, mwhy = model_for_task(text)
    busy = [a for a in agents if a.get("busy")]
    free = [a for a in agents if not a.get("busy")]
    pick = None
    if free:
        # menos escopo declarado = mais livre para o trabalho novo
        pick = sorted(free, key=lambda a: len(a.get("files") or []))[0]
    elif agents:
        pick = agents[0]
    return {
        "task": (text or "")[:160],
        "kind": classify(text)[0],
        "persona": {"mbti": mbti, "id": pid, "why": why},
        "model": {"id": model, "why": mwhy},
        "agent": {
            "name": (pick or {}).get("codename") or (pick or {}).get("name") or "",
            "session": (pick or {}).get("session") or "",
            "free": bool(free),
        },
        "note": (
            "A personalidade é do TIPO da tarefa (MBTI fluido) e vai no system "
            "prompt via o estado da persona (jarvis_persona / /mood); o modelo "
            "é escolhido pelo registry respeitando cooldown de rate limit."
        ),
    }


def assign_text(text: str) -> str:
    """O plano em texto (para o Telegram e para o relatório da madrugada)."""
    a = assign(text)
    p, m, ag = a["persona"], a["model"], a["agent"]
    return (
        f"PLANO — {a['kind']}\n"
        f"  agente:    {ag['name'] or '(ninguem livre)'} "
        f"({'livre' if ag['free'] else 'todos ocupados'})\n"
        f"  persona:   {p['mbti']} ({p['id']}) — {p['why']}\n"
        f"  modelo:    {m['id'] or '(nenhum disponivel)'} — {m['why']}"
    )
