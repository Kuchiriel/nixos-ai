"""Roteador de intenções do JARVIS — a inteligência de usar o caminho mais barato.

Filosofia herdada do legado (Manjaro/AI_SYSTEM): SLMs roteados + caminhos
rápidos determinísticos (RiveScript para audiobook) para extrair o máximo
do mínimo. Em vez de mandar tudo para o LLM, classificamos a intenção e
roteamos para o handler que resolve com o menor custo:

  1. `doctor` — pedidos de status/saúde do sistema → determinístico, zero LLM
  2. `nixos`  — pedidos de packages/options do nixpkgs → mcp-nixos (MCP read-only),
                consulta real sem alucinação e sem LLM
  3. `rag`    — pedidos sobre o código indexado → busca híbrida (dense+sparse)
  4. `agent`  — tudo mais (raciocínio, ações, conversa) → LLM + tools

A cascata é por custo: só sobe para o LLM quando nenhum caminho barato resolve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.rules import DEFAULT_RULES, FastPaths

# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

# Rota SYSTEM/DOCTOR — pedidos de diagnóstico/status do sistema
_DOCTOR_TRIGGERS: tuple[str, ...] = (
    "status do sistema", "saúde do sistema", "health check", "healthcheck",
    "como está o sistema", "tudo funcionando", "serviços ativos",
    "qual serviço", "está rodando", "quais serviços", "diagnóstico",
    "verificar o sistema", "checar o sistema", "disco cheio", "espaço em disco",
    "memória", "processador", "uptime", "system status", "check services",
    "is everything ok", "how is the system", "doctor", "estão rodando",
    "serviços rodando", "services running", "services up", "checar",
    "verificar", "status", "ok?",
)

# Rota NIXOS — pedidos de packages/options do nixpkgs (via mcp-nixos)
_NIXOS_TRIGGERS: tuple[str, ...] = (
    "pacote", "package", "opção do nixos", "opcao do nixos", "nixos option",
    "nixpkgs", "option", "services.", "programs.", "nix option", "opção de",
    "atributo do nixpkgs", "qual o pacote", "qual a opção", "existe no nixos",
    "no nixos", "no nixpkgs", "habilitar o serviço", "enable option",
    "como habilitar", "configurar o nixos",
)

# Rota RAG — pedidos sobre código indexado
_RAG_TRIGGERS: tuple[str, ...] = (
    "no código", "no repo", "no repositório", "no codigo", "onde está",
    "onde fica", "qual arquivo", "qual função", "procura no código",
    "busca no código", "como funciona o", "implementação de", "onde é usado",
    "onde é definido", "search the code", "find in code", "which file",
    "where is", "in the repo", "in the codebase", "código-fonte", "codigo-fonte",
    "arquivo", "classe", "função que", "funcao que", "indexado",
)

# Expressões de fallback técnico: extensões de arquivo forçam RAG
_RAG_EXT_RE = re.compile(r"\.(py|nix|rs|go|ts|js|lua|sh|cpp|c|h|md|toml|json)\b", re.IGNORECASE)


@dataclass
class Route:
    """Decisão do roteador: qual handler e com que contexto."""

    handler: str  # fastpath | doctor | nixos | rag | agent
    reason: str = ""
    query: str = ""
    confidence: float = 0.0
    hints: dict[str, Any] = field(default_factory=dict)


# Fast paths declarativos (singleton, com handlers de exemplo)
_fast_paths: FastPaths | None = None


def get_fast_paths() -> FastPaths:
    """Fast paths com handlers de exemplo (audiobook/voz)."""
    global _fast_paths
    if _fast_paths is not None:
        return _fast_paths
    fp = FastPaths.from_text(DEFAULT_RULES)

    def _audio(args: list[str]) -> str:
        from jarvis.core.audiobook import dispatch
        return dispatch(args)

    def _voice(args: list[str]) -> str:
        action = args[0] if args else ""
        return f"[voz {action}] {' '.join(args[1:]) or ''}"

    def _sys(args: list[str]) -> str:
        """Executa comando read-only da allowlist e devolve a saída.

        Zero LLM (resposta em ms). Seguro: só comandos da allowlist do
        agente (diagnóstico); comandos com efeito passam pelo agente com
        aprovação — nunca direto por fast path.
        """
        cmd = " ".join(args).strip()
        if not cmd:
            return "(comando vazio)"
        from jarvis.core.agent import command_allowed, run_shell

        if not command_allowed(cmd):
            return f"comando não permitido em fast path: {cmd} (use /agent com aprovação)"
        try:
            res = run_shell(cmd, timeout=15)
        except Exception as exc:  # noqa: BLE001
            return f"erro: {exc}"
        out = res.stdout if res.returncode == 0 else res.stderr
        return (out or f"(exit {res.returncode})").strip()[:1500]

    fp.register("audiobook", _audio)
    fp.register("voice", _voice)
    fp.register("sys", _sys)
    _fast_paths = fp
    return fp


def _match_any(text: str, triggers: tuple[str, ...]) -> tuple[bool, str]:
    for t in triggers:
        if t in text:
            return True, t
    return False, ""


def route_request(text: str) -> Route:
    """Classifica um pedido e escolhe a rota mais barata que resolve."""
    low = text.lower().strip()
    if not low:
        return Route("agent", "pedido vazio", text, 0.0)

    # 0. FASTPATH — o mais barato de todos (regras declarativas, zero LLM)
    fp = get_fast_paths()
    match = fp.match(low)
    if match is not None:
        return Route("fastpath", f"regra declarativa: '{match.rule.trigger}'", text, 1.0)

    # 1. DOCTOR — o mais barato (zero LLM), mas NÃO rouba comandos diretos:
    #    "quanto de memória tem?" é um fast path sys (free -h), não um
    #    pedido de saúde geral. Fast path tem precedência sobre doctor.
    ok, trigger = _match_any(low, _DOCTOR_TRIGGERS)
    if ok and fp.match(low) is None:
        return Route("doctor", f"gatilho de diagnóstico: '{trigger}'", text, 0.9)

    # 2. NIXOS — consulta real via mcp-nixos (zero LLM, sem alucinação)
    ok, trigger = _match_any(low, _NIXOS_TRIGGERS)
    if ok:
        return Route("nixos", f"gatilho de nixpkgs: '{trigger}'", text, 0.85)

    # 3. RAG — código indexado (zero LLM para recuperação)
    ok, trigger = _match_any(low, _RAG_TRIGGERS)
    if ok or _RAG_EXT_RE.search(low):
        reason = f"gatilho de código: '{trigger}'" if ok else "extensão de arquivo no pedido"
        return Route("rag", reason, text, 0.8)

    # 4. AGENT — tudo mais (LLM + tools)
    return Route("agent", "sem caminho barato — LLM com tools", text, 0.5)


# ---------------------------------------------------------------------------
# Execução das rotas
# ---------------------------------------------------------------------------


def handle_fastpath(query: str) -> dict[str, Any]:
    """Executa a rota fastpath: regra declarativa + resposta com macro."""
    fp = get_fast_paths()
    response = fp.respond(query)
    return {"route": "fastpath", "response": response, "topic": fp.topic()}


def handle_doctor(cfg: Any = None) -> dict[str, Any]:
    """Executa a rota doctor (diagnóstico de saúde)."""
    from jarvis.core.doctor import doctor_report

    return doctor_report(cfg)


def handle_nixos(query: str, cfg: Any = None, mcp_bin: str | None = None) -> dict[str, Any]:
    """Executa a rota nixos: consulta o mcp-nixos com os termos do pedido.

    Extrai o termo mais provável (package/option) do texto; sem matching,
    faz uma busca ampla. Retorna o texto do MCP + metadados.
    """
    from jarvis.core.config import get_config
    from jarvis.providers.mcp import MCPClient, MCPError, parse_command

    cfg = cfg or get_config()
    binary = mcp_bin or cfg.mcp_nixos_bin
    command, args = parse_command(binary)

    term = _extract_nix_term(query)
    if term:
        action = "info"
        source = "nixos"
        ttype = "option" if ("." in term or term.startswith("services.")) else "package"
    else:
        action = "search"
        source = "nixos"
        ttype = "packages"
        term = _strip_stopwords(query)

    try:
        with MCPClient(command, args, name="jarvis-router") as client:
            out = client.call_tool("nix", {
                "action": action,
                "query": term,
                "source": source,
                "type": ttype,
            })
        return {
            "route": "nixos",
            "query": term,
            "action": action,
            "type": ttype,
            "result": out,
            "error": None,
        }
    except (MCPError, OSError) as exc:
        return {"route": "nixos", "query": term, "action": action, "type": ttype,
                "result": "", "error": str(exc)}


def handle_rag(query: str, cfg: Any = None, top_k: int = 5) -> dict[str, Any]:
    """Executa a rota rag: busca híbrida no código indexado."""
    from jarvis.core.rag import HybridSearch

    search = HybridSearch(cfg)
    hits = search.search(query, top_k=top_k)
    return {
        "route": "rag",
        "query": query,
        "hits": [
            {"path": h.path, "score": round(h.score, 4), "symbols": h.payload.get("symbols", [])}
            for h in hits
        ],
    }


def handle_agent(query: str, cfg: Any = None, *, approve: bool = False,
                 mcp_bin: str | None = None, state_dir=None,
                 approver=None) -> dict[str, Any]:
    """Executa a rota agent: LLM com tools (execute_shell + mcp-nixos)."""
    from jarvis.core.agent import Agent
    from jarvis.core.config import get_config

    cfg = cfg or get_config()
    audit = (state_dir or cfg.ensure_state_dir()) / "agent-audit.jsonl"
    mcp_servers = {}
    binary = mcp_bin or cfg.mcp_nixos_bin
    if binary:
        mcp_servers["nixos"] = binary
    agent = Agent(cfg, approve=approve, approver=approver,
                  audit_path=audit, mcp_servers=mcp_servers)
    result = agent.run(query)
    return {
        "route": "agent",
        "response": result.final_response,
        "commands_run": result.commands_run,
        "commands_denied": result.commands_denied,
    }


# ---------------------------------------------------------------------------
# Helpers de extração
# ---------------------------------------------------------------------------

_OPTION_RE = re.compile(r"(?:services|programs|hardware|boot|networking|users|security|virtualisation)\.[a-z0-9_.-]+", re.IGNORECASE)
_PACKAGE_RE = re.compile(r"\b(?:pacote|package|atributo)\s+([a-z0-9_.-]+)", re.IGNORECASE)

# Preposições/stopwords que podem virar falso positivo após "pacote"
_PACKAGE_SKIP = {"do", "da", "de", "o", "a", "os", "as", "para", "por", "com", "no", "na"}


def _extract_nix_term(text: str) -> str | None:
    m = _OPTION_RE.search(text)
    if m:
        return m.group(0)
    m = _PACKAGE_RE.search(text)
    if m:
        candidate = m.group(1)
        # "qual o pacote do ripgrep" → "do" não é o pacote; procura a próxima palavra
        if candidate in _PACKAGE_SKIP:
            after = re.search(r"\b(?:do|da|de)\s+([a-z0-9_.-]+)", text[m.end() - len(candidate):])
            if after:
                return after.group(1)
        return candidate
    return None


_STOPWORDS = {"o", "a", "os", "as", "um", "uma", "de", "do", "da", "no", "na",
              "para", "por", "com", "em", "qual", "quais", "como", "que", "é",
              "existe", "no", "nixos", "nixpkgs", "pacote", "package", "opção",
              "opcao", "option", "me", "diga", "fale", "procure", "busque",
              "use", "usar", "ferramenta", "nix", "the", "a", "an", "for",
              "of", "in", "is", "what", "which", "package", "option"}


def _strip_stopwords(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9_.-]+", text.lower()) if w not in _STOPWORDS]
    return " ".join(words[:8]) or text
