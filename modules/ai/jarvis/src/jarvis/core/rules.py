"""Motor de fast paths declarativos — o RiveScript do JARVIS, em Python puro.

Decisão de arquitetura (pesquisa 08/2026): o RiveScript não está no nixpkgs
(quebraria a tese declarativa do host) e o padrão 2026 é "Agent Skills"
(SKILL.md declarativo — ClawNix/OpenClaw/Claude Code; arXiv 2606.06923 mede
ganho de acurácia). A síntese: regras declarativas em arquivos de dados que
**o LLM e o humano podem editar** (expandir capacidades sem tocar código),
executadas por um motor Python puro e testável.

Modelo (no espírito do RiveScript do legado):
  - triggers com wildcards (`*`) e alternativas (`|`)
  - responses com `<call>module action <star></call>` (macro)
  - `{topic=nome}` para entrar num contexto; `{topic=random}` para sair
  - prioridade: regras específicas antes de genéricas (carregadas por ordem)

Formato (YAML-like simples, sem dependência): regras vivem em arquivos
`*.rules` declarativos, versionados no repo (dados, não código).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Rule:
    trigger: str
    response: str
    topic: str = "random"  # topic onde a regra é válida
    priority: int = 0

    # compilado
    _regex: re.Pattern[str] = field(default=None, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._regex = compile_trigger(self.trigger)


_TRIGGER_TOKEN_RE = re.compile(r"\[[^\]]+\]|\([^)]+\)|\*|\S+")


def compile_trigger(trigger: str) -> re.Pattern[str]:
    r"""Converte trigger RiveScript-like em regex (token a token).

    Suporta: `*` (wildcard, 1+ palavras), `(a|b)` alternativas,
    `[opcional]`, texto literal. Tokens são unidos com `\s*` flexível, então
    opcionais não quebram o matching (bug da primeira versão).
    """
    tokens = _TRIGGER_TOKEN_RE.findall(trigger.strip().lower())
    parts: list[str] = []
    for token in tokens:
        if token == "*":
            parts.append(r"(.+)")
        elif token.startswith("[") and token.endswith("]"):
            alts = _escape_alternatives(token[1:-1])
            parts.append(r"(?:" + r"\s*|".join(alts) + r"\s*)?")
        elif token.startswith("(") and token.endswith(")"):
            alts = _escape_alternatives(token[1:-1])
            parts.append(r"(?:" + r"\s*|".join(alts) + r"\s*)")
        else:
            parts.append(re.escape(token))
    pattern = r"\s*".join(parts)
    return re.compile(rf"^{pattern}\s*$", re.IGNORECASE)


def _escape_alternatives(inner: str) -> list[str]:
    """Divide alternativas `a|b` e escapa cada uma."""
    out = []
    for alt in inner.split("|"):
        out.append(re.escape(alt.strip()))
    return out


@dataclass
class RuleMatch:
    rule: Rule
    stars: list[str] = field(default_factory=list)
    response: str = ""
    next_topic: str = "random"


class FastPaths:
    """Conjunto de regras declarativas com contexto (topics)."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self._rules: list[Rule] = rules or []
        self._topic = "random"
        self._handlers: dict[str, Callable[[list[str]], str]] = {}

    # --- construção ---

    @classmethod
    def from_text(cls, text: str, topic: str = "random") -> "FastPaths":
        """Parseia um bloco de regras no formato declarativo.

        Formato:
            # comentário
            [topic audiobook]
            leia [o livro] * → <call>audiobook read <star></call>{topic=audiobook}
        """
        fp = cls()
        current_topic = topic
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[topic "):
                current_topic = line[len("[topic ") : -1].strip()
                continue
            if "→" in line:
                trigger, _, response = line.partition("→")
                fp.add(trigger.strip(), response.strip(), topic=current_topic)
        return fp

    @classmethod
    def from_file(cls, path: str | Path) -> "FastPaths":
        return cls.from_text(Path(path).read_text(encoding="utf-8"))

    def add(self, trigger: str, response: str, *, topic: str = "random", priority: int = 0) -> None:
        self._rules.append(Rule(trigger, response, topic=topic, priority=priority))

    def register(self, name: str, handler: Callable[[list[str]], str]) -> None:
        """Registra um macro executável: <call>nome arg1 arg2</call>."""
        self._handlers[name] = handler

    # --- matching ---

    def match(self, text: str) -> RuleMatch | None:
        """Encontra a melhor regra: topic atual primeiro, depois globais."""
        low = text.strip().lower()
        # pontuação final (?, !, .) não deve quebrar o matching
        low = re.sub(r"[?!.]+$", "", low).strip()
        # 1) regras do topic atual (maior prioridade)
        for rule in sorted(
            (r for r in self._rules if r.topic == self._topic),
            key=lambda r: -r.priority,
        ):
            m = rule._regex.match(low)
            if m:
                return self._expand(rule, m.groups())
        # 2) regras globais (random) — específicas antes de genéricas
        for rule in sorted(
            (r for r in self._rules if r.topic == "random"),
            key=lambda r: (-r.priority, -len(r.trigger)),
        ):
            m = rule._regex.match(low)
            if m:
                return self._expand(rule, m.groups())
        return None

    def _expand(self, rule: Rule, groups: tuple[str, ...]) -> RuleMatch:
        stars = [g.strip() for g in groups if g is not None]
        response = rule.response
        next_topic = "random"
        m = re.search(r"\{topic=([a-z0-9_-]+)\}", response)
        if m:
            next_topic = m.group(1)
            response = response.replace(m.group(0), "")
        response = response.replace("<star>", stars[0] if stars else "")
        return RuleMatch(rule=rule, stars=stars, response=response.strip(), next_topic=next_topic)

    def respond(self, text: str) -> str | None:
        """Executa a regra: devolve a resposta (com macro resolvido) ou None."""
        match = self.match(text)
        if match is None:
            return None
        self._topic = match.next_topic
        call = re.search(r"<call>([a-z0-9_-]+)(?:\s+([^<]*))?</call>", match.response)
        if call:
            name, args_text = call.group(1), (call.group(2) or "").strip()
            args = [a.strip() for a in args_text.split()] if args_text else []
            handler = self._handlers.get(name)
            if handler:
                return handler(args)
            return f"<macro desconhecido: {name}>"
        return match.response

    def topic(self) -> str:
        return self._topic


# ---------------------------------------------------------------------------
# Exemplo de uso: audiobook (porta do audiobook.rive do legado)
# ---------------------------------------------------------------------------

DEFAULT_RULES = """\
# Fast paths do JARVIS (declarativo — editável por humano e LLM)
# Formato: trigger → resposta. Wildcards: * | alternativas: (a|b) | opcional: [x]
# <call>macro args</call> executa código; {topic=nome} troca de contexto.

# --- audiobook ---
[topic random]
leia [o] [livro] * → <call>audiobook read <star></call>{topic=audiobook}
lê [o] [livro] * → <call>audiobook read <star></call>{topic=audiobook}
ler [o] [livro] * → <call>audiobook read <star></call>{topic=audiobook}
read [the] [book] * → <call>audiobook read <star></call>{topic=audiobook}
quais livros [tenho|tem] → <call>audiobook list</call>
meus livros → <call>audiobook list</call>
procura [por] livros → <call>audiobook scan</call>
para de ler → <call>audiobook stop</call>{topic=random}
pausa [a leitura] → <call>audiobook pause</call>
continua [a leitura] → <call>audiobook resume</call>
próximo [capítulo] → <call>audiobook next</call>
capítulo anterior → <call>audiobook prev</call>

# --- voz (TTS) ---
mude [para] [a] voz * → <call>voice set <star></call>
muda [para] [a] voz * → <call>voice set <star></call>
listar vozes → <call>voice list</call>
fale mais rápido → <call>voice rate up</call>
fale mais devagar → <call>voice rate down</call>

# --- comandos de sistema (read-only, execução direta sem LLM) ---
# O macro `sys` executa comandos read-only da allowlist e devolve a saída
# (zero LLM = resposta em milissegundos). Comandos com efeito (rebuild,
# clean) passam pelo agente com aprovação — nunca direto por fast path.
# Nota: regras de memória/disco DEVEM vir antes do trigger genérico do
# doctor ("memória") para o roteador não roubar o pedido.
uso de memória → <call>sys free -h</call>
uso da memória → <call>sys free -h</call>
uso de ram → <call>sys free -h</call>
qual o uso de memória → <call>sys free -h</call>
qual é o uso de memória → <call>sys free -h</call>
como está o uso de memória → <call>sys free -h</call>
como está o uso de ram → <call>sys free -h</call>
quanta memória [tem|está usando|livre] → <call>sys free -h</call>
quanto de memória [tem|está usando|livre] → <call>sys free -h</call>
memória [do sistema] → <call>sys free -h</call>
ram [livre|usada|em uso] → <call>sys free -h</call>
espaço em disco → <call>sys df -h /</call>
disco [cheio|livre|em uso] → <call>sys df -h /</call>
quanto de disco [tem|livre] → <call>sys df -h /</call>
uso de disco → <call>sys df -h /</call>
quanto tempo [o] [sistema] [está] ligado → <call>sys uptime</call>
uptime → <call>sys uptime</call>
qual kernel → <call>sys uname -r</call>
versão do kernel → <call>sys uname -r</call>
processos [ativos|rodando] → <call>sys ps aux --sort=-%mem</call>
"""
