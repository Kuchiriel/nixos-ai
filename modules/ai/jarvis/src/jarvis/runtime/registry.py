"""ToolRegistry único — Fase 1 (ADR-005).

NÃO muda comportamento: lê os schemas existentes (DEV_TOOLS + JARVIS_TOOLS),
normaliza num único registro e MEDE a divergência entre dialetos.

`dialect_report()` é a worklist da Fase 2 (convergência de schema): cada
divergência listada aqui precisa desaparecer (merge) ou virar alias declarado.
Os testes em test_runtime_convergence.py travam o estado atual — qualquer
NOVA divergência falha alto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Canonical name = DEV_TOOLS name (sem prefixo jarvis_). MCP names com prefixo
# jarvis_ mapeiam p/ o canônico; o que não mapeia é superfície exclusiva.
_CANONICAL_ALIASES = {
    "jarvis_execute": "execute_shell",
    "jarvis_read_file": "read_file",
    "jarvis_write_file": "write_file",
    "jarvis_str_replace": "str_replace",
    "jarvis_remember": "remember",
    "jarvis_recall": "recall",
    "jarvis_lessons": "lessons",
    "jarvis_rag_search": "semantic_search",
    "jarvis_rag_index": "rag_index",
    "jarvis_vault_list": "vault_list",
    "jarvis_vault_write": "vault_write",
    "jarvis_web_search": "web_search",
    "jarvis_persona": "persona",
}

# Canônico → chave do handle_dev_tool quando divergem.
_HANDLER_KEYS = {"command": "jarvis_command"}

# Contrato de verificação v1 por capability (§6): como o runtime confirma
# o efeito (world = estado do mundo; self-report = ok do próprio retorno).
_VERIFY_BY_CAPABILITY = {
    "filesystem.write": "world:file-exists",
    "system.execute": "self-report",
    "system.verify": "self-report",
    "system.nix": "self-report",
    "safety.transform": "self-report",
    "data.build": "self-report",
    "interaction.act": "policy-gate",
}

# Alias de PARÂMETROS por ferramenta canônica (transporte → canônico).
# Declarado aqui = divergência CONHECIDA, traduzida no transporte (Fase 2).
# O que diverge e NÃO está aqui = SILENT (o linter falha).
PARAM_ALIASES: dict[str, dict[str, str]] = {
    # MCP declara old_string/new_string; executor canônico usa old/new.
    # Contrato externo MCP congelado → tradução na borda, não no schema.
    "str_replace": {"old_string": "old", "new_string": "new"},
    # MCP declara limit; executor canônico usa top_k (mesmo conceito).
    "semantic_search": {"limit": "top_k"},
}

# capability / mutation / approval inferidos por nome canônico.
# approval: none | policy | always. mutation: a tool altera mundo persistente.
_TOOL_POLICY: dict[str, tuple[str, bool, str]] = {
    "read_file": ("filesystem.read", False, "none"),
    "list_directory": ("filesystem.read", False, "none"),
    "code_search": ("filesystem.read", False, "none"),
    "semantic_search": ("knowledge.retrieve", False, "none"),
    "rag_index": ("knowledge.write", True, "none"),
    "recall": ("memory.read", False, "none"),
    "lessons": ("memory.read", False, "none"),
    "remember": ("memory.write", True, "none"),
    "vault_list": ("memory.read", False, "none"),
    "vault_write": ("memory.write", True, "none"),
    "write_file": ("filesystem.write", True, "policy"),
    "str_replace": ("filesystem.write", True, "policy"),
    "sanitize_secrets": ("safety.transform", True, "none"),
    "build_json_dataset": ("data.build", True, "none"),
    "run_tests": ("system.verify", True, "none"),
    "run_linter": ("system.verify", True, "none"),
    "execute_shell": ("system.execute", True, "policy"),
    "jarvis_command": ("system.execute", True, "policy"),
    "load_skill": ("session.config", False, "none"),
    "persona": ("session.config", False, "none"),
    "human_click": ("interaction.act", True, "always"),
    "human_type": ("interaction.act", True, "always"),
    "human_key": ("interaction.act", True, "always"),
    "browser": ("interaction.act", True, "policy"),
    "capture_screen": ("interaction.observe", False, "none"),
    "observe_screen": ("interaction.observe", False, "none"),
    "nix_eval": ("system.nix", False, "none"),
    "nix_check": ("system.verify", False, "none"),
    "nix_search": ("system.nix", False, "none"),
    "read_chatgpt": ("knowledge.retrieve", False, "none"),
    "web_search": ("knowledge.retrieve", False, "none"),
    "vault_sync_obsidian": ("memory.write", True, "policy"),
    "vault_sync_hackmd": ("memory.write", True, "policy"),
    "vault_search_obsidian": ("memory.read", False, "none"),
    "vault_status": ("memory.read", False, "none"),
}


@dataclass
class Tool:
    """Um conceito de ferramenta, independente do dialeto que a declara."""

    name: str  # canônico
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    capability: str = "misc"
    mutation: bool = False
    approval: str = "policy"  # none | policy | always
    providers: list[str] = field(default_factory=list)  # dialetos que declaram
    aliases: list[str] = field(default_factory=list)  # nomes alternativos
    # §6: executor + contrato de verificação (transporte genérico).
    handler: str = ""  # "devtools:<nome>" ou "mcp:<nome>" (executor dedicado)
    verify: str = ""  # "world:file-exists" | "world:compiles" | "none"...


@dataclass
class DialectDivergence:
    """Um ponto onde dois dialetos discordam sobre o mesmo conceito."""

    canonical: str
    kind: str  # name | params | required | capability | missing
    detail: str


class ToolRegistry:
    """Registro único construído das fontes existentes (read-only)."""

    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}
        self.divergences: list[DialectDivergence] = []

    # -- construção ------------------------------------------------------
    @classmethod
    def build_default(cls) -> ToolRegistry:
        from jarvis.core import devtools
        from jarvis import mcp_server

        reg = cls()
        for entry in devtools.DEV_TOOLS:
            fn = entry.get("function", {})
            reg._add(
                name=str(fn.get("name", "")),
                description=str(fn.get("description", "")),
                parameters=dict(fn.get("parameters", {})),
                provider="devtools",
            )
        for entry in mcp_server.JARVIS_TOOLS:
            reg._add(
                name=str(entry.get("name", "")),
                description=str(entry.get("description", "")),
                parameters=dict(entry.get("inputSchema", {})),
                provider="mcp",
            )
        return reg

    def _add(self, *, name: str, description: str,
             parameters: dict[str, Any], provider: str) -> None:
        if not name:
            return
        # Canônico = sem prefixo jarvis_ (1 dialeto na emissão; forma prefixada
        # vira alias). Aliases explícitos cobrem os mapeamentos não-triviais.
        canonical = _CANONICAL_ALIASES.get(name, name.removeprefix("jarvis_"))
        tool = self.tools.get(canonical)
        if tool is None:
            cap, mut, appr = _TOOL_POLICY.get(canonical, ("misc", False, "policy"))
            tool = self.tools[canonical] = Tool(
                name=canonical, description=description, parameters=parameters,
                capability=cap, mutation=mut, approval=appr)
        if provider not in tool.providers:
            tool.providers.append(provider)
        if name != canonical and name not in tool.aliases:
            tool.aliases.append(name)
        if provider == "devtools":
            tool.handler = f"devtools:{_HANDLER_KEYS.get(canonical, canonical)}"
        if not tool.verify:
            tool.verify = _VERIFY_BY_CAPABILITY.get(tool.capability, "none")
        # mede divergência de params entre dialetos do mesmo conceito
        if provider == "mcp" and "devtools" in tool.providers:
            # F4: compara OBRIGATÓRIOS normalizados. Params opcionais de
            # escopo do transporte (collection, allow_multiple) não são fork
            # — o executor único decide; renames vivem em PARAM_ALIASES.
            alias = PARAM_ALIASES.get(canonical, {})
            dev_req = set(tool.parameters.get("required", []))
            mcp_req = {alias.get(p, p)
                       for p in parameters.get("required", [])}
            if dev_req != mcp_req:
                dev_params = set(tool.parameters.get("properties", {}))
                mcp_raw = set(parameters.get("properties", {}))
                self.divergences.append(DialectDivergence(
                    canonical=canonical, kind="params",
                    detail=f"devtools={sorted(dev_params)} vs mcp={sorted(mcp_raw)}"))

    # -- consultas --------------------------------------------------------
    def names(self) -> list[str]:
        return sorted(self.tools)

    def for_task(self, _task_context: str = "",
                 capabilities: list[str] | None = None) -> list[Tool]:
        """Progressive disclosure estrutural (§7): com capabilities, só as
        ferramentas dessas capabilities; sem filtro, tudo (F2+ = seleção
        por tarefa via modelo fica p/ quando o runtime decidir)."""
        tools = [self.tools[n] for n in self.names()]
        if capabilities is None:
            return tools
        want = set(capabilities)
        return [t for t in tools if t.capability in want]

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Emissão única de schema (o que o LLM recebe — 1 dialeto)."""
        out = []
        for name in self.names():
            t = self.tools[name]
            out.append({"type": "function", "function": {
                "name": t.name, "description": t.description,
                "parameters": t.parameters or {"type": "object", "properties": {}},
            }})
        return out

    def dialect_report(self) -> list[DialectDivergence]:
        return list(self.divergences)

    def declared_aliases(self) -> dict[str, dict[str, str]]:
        """Renames transporte→canônico declarados (Fase 2+)."""
        return {k: dict(v) for k, v in PARAM_ALIASES.items()}

    def dispatch(self, name: str, args: dict[str, Any] | None) -> str | None:
        """Transporte genérico: resolve + executa via executor declarado.

        Retorna None quando o conceito não tem executor devtools (o
        transporte cai p/ handlers dedicados). Erro 'Unknown tool' do
        executor também vira None (nunca exceção no transporte).
        """
        import json

        from jarvis.core.devtools import handle_dev_tool  # lazy: sem ciclo
        canonical, targs = self.resolve(name, args)
        key = _HANDLER_KEYS.get(canonical, canonical)
        out = handle_dev_tool(key, targs)
        try:
            data = json.loads(out) if isinstance(out, str) else {}
        except Exception:
            return out
        if isinstance(data, dict) and str(
                data.get("error", "")).startswith("Unknown tool"):
            return None
        return out

    def resolve(self, name: str, args: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
        """Transporte → (nome canônico, args canônicos).

        Aplica alias de nome + renames declarados. Chave desconhecida passa
        intacta (o executor decide o erro, nunca o transporte).
        """
        canonical = _CANONICAL_ALIASES.get(name, name.removeprefix("jarvis_"))
        translated = dict(args or {})
        for alias, canon_arg in PARAM_ALIASES.get(canonical, {}).items():
            if alias in translated and canon_arg not in translated:
                translated[canon_arg] = translated.pop(alias)
        return canonical, translated
