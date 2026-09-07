"""Motor de fast paths declarativos — o RiveScript do JARVIS, em Python puro.

Decisão de arquitetura (pesquisa 08/2026): o RiveScript não está no nixpkgs
(quebraria a tese declarativa do host) e o padrão 2026 é "Agent Skills"
(SKILL.md declarativo — ClawNix/OpenClaw/Claude Code; arXiv 2606.06923 mede
ganho de acurácia). A síntese: regras declarativas em arquivos de dados que
**o LLM e o humano podem editar** (expandir capacidades sem tocar código),
executadas por um motor Python puro e testável.

Modelo (no espírito do RiveScript do legado em AI_SYSTEM/orchestrator/brain):
  - triggers com wildcards (`*` = 1+ palavras, `[*]` = 0+ palavras)
  - wildcard numérico `#` (dígitos) para aritmética/percentuais
  - alternativas `(a|b|c)` e opcionais `[x]`
  - arrays de sinônimos `! array nome = a b c` referenciados por `@nome`
    (absorvem variações de acento/idioma: memória/memoria, book/livro)
  - responses com `<call>module action <star1> <star2></call>` (macro)
  - `{topic=nome}` para entrar num contexto; `{topic=random}` para sair
  - prioridade: regras com mais tokens literais antes das genéricas

Normalização de entrada (robustez — o legado dependia de frases inteiras):
  - minúsculas, pontuação final ignorada, espaços colapsados
  - prefixos de chamada/filler removidos: "jarvis,", "hey jarvis", "ei",
    "opa", "ok", "por favor", "pode", "você pode", "fala", "fale"
  - O matching continua ANCORADO (a frase inteira normalizada tem que casar
    com o trigger): isso garante que fast path NUNCA rouba um pedido real
    que deveria ir para o LLM (um trigger só dispara se a frase inteira
    casar, não por substring).

Formato (YAML-like simples, sem dependência): regras vivem em arquivos
`*.rules` declarativos, versionados no repo (dados, não código).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Tokens de trigger, por ordem de especificidade (findall pega o mais longo à esquerda):
#   [*]          wildcard opcional (0+ palavras)
#   [x|y]        opcional (alternativas)
#   (a|b)        alternativas obrigatórias
#   @nome        array de sinônimos
#   #            número
#   *            wildcard (1+ palavras)
#   \S+          literal
_TRIGGER_TOKEN_RE = re.compile(
    r"\[\*\]|\[[^\]]+\]|\([^)]+\)|@[a-z0-9_]+|#|\*|\S+"
)

# Prefixos de chamada/filler que são removidos da entrada antes do matching.
# Só no INÍCIO e só como prefixo: o restante ainda precisa casar inteiro.
_NAME_PREFIX_RE = re.compile(
    r"^(?:(?:hey|ei|opa|ok|olá|oi|eh|psiu)\s+)?(?:jarvis|jávis)\b[,!\s:]*",
    re.IGNORECASE,
)
_FILLER_PREFIX_RE = re.compile(
    r"^(?:(?:por favor|pfv|pf|pode|você pode|voce pode|você consegue|voce consegue|fala|fale|querido|mano|amigo)\s*[,!\s]*)+",
    re.IGNORECASE,
)


def _escape_alternatives(inner: str) -> list[str]:
    """Divide alternativas `a|b` e escapa cada uma."""
    out = []
    for alt in inner.split("|"):
        out.append(re.escape(alt.strip()))
    return out


def _expand_alts(inner: str, arrays: dict[str, list[str]]) -> list[str]:
    """Divide alternativas e expande `@array` dentro delas (ex.: `[@livro]`).

    Ordena por comprimento DESCENDENTE: em `(ler|leia|le|lê|leio)`, a
    alternativa `le` não pode roubar o prefixo de `leio`.
    """
    out = []
    for alt in inner.split("|"):
        alt = alt.strip()
        if alt.startswith("@") and alt[1:] in arrays:
            out.extend(re.escape(a.strip()) for a in arrays[alt[1:]])
        else:
            out.append(re.escape(alt))
    return sorted(out, key=len, reverse=True)


def _specificity(tokens: list[str]) -> int:
    """Pontuação de especificidade (espírito do RiveScript):

    literal 3 (palavra fixa) > número 2 (`#`) ≈ alternativas/arrays 2 >
    opcional 1 (`[x]`) > wildcard 0 (`*`, `[*]`).

    Garante que `quanto é # * #` vença `[*] quanto é [*]` quando os dois
    casam (mesmos literais, mas `#` restringe mais que `[*]`).
    """
    n = 0
    for tok in tokens:
        if tok == "#":
            n += 2
        elif tok in ("*", "[*]"):
            continue
        elif tok.startswith("(") or tok.startswith("@"):
            n += 2
        elif tok.startswith("["):
            n += 1
        elif re.fullmatch(r"[a-zà-ÿ0-9]+(?:[ -][a-zà-ÿ0-9]+)*", tok):
            n += 3
    return n


def compile_trigger(trigger: str, arrays: dict[str, list[str]] | None = None) -> re.Pattern[str]:
    r"""Converte trigger RiveScript-like em regex (token a token).

    Suporta:
      `*`        wildcard 1+ palavras → `(.+)`
      `[*]`      wildcard 0+ palavras → `(.*?)`
      `#`        número (ex.: 2, 2.5, 2,5) → `(\d+(?:[.,]\d+)?)`
      `(a|b)`    alternativas obrigatórias (grupo não-capturante)
      `[x|y]`    opcionais (grupo não-capturante, casável com vazio)
      `@nome`    array de sinônimos (`! array nome = a b c`) → `(a|b|c)`
      literal    texto fixo

    Tokens são unidos com `\s*` flexível, então opcionais não quebram o
    matching (bug da primeira versão).
    """
    arrays = arrays or {}
    tokens = _TRIGGER_TOKEN_RE.findall(trigger.strip().lower())
    parts: list[str] = []
    for token in tokens:
        if token == "*":
            # lazy: em triggers com dois `*` (ex.: matemática), o segundo
            # número não é engolido pelo primeiro wildcard
            parts.append(r"(.+?)")
        elif token == "[*]":
            parts.append(r"(.*?)")
        elif token == "#":
            parts.append(r"(\d+(?:[.,]\d+)?)")
        elif token.startswith("[") and token.endswith("]"):
            alts = _expand_alts(token[1:-1], arrays)
            parts.append(r"(?:" + r"\s*|".join(alts) + r"\s*)?")
        elif token.startswith("(") and token.endswith(")"):
            alts = _expand_alts(token[1:-1], arrays)
            parts.append(r"(?:" + r"\s*|".join(alts) + r"\s*)")
        elif token.startswith("@"):
            name = token[1:]
            alts = [re.escape(a.strip()) for a in arrays.get(name, [name])]
            alts.sort(key=len, reverse=True)
            parts.append(r"(?:" + r"\s*|".join(alts) + r"\s*)")
        else:
            parts.append(re.escape(token))
    pattern = r"\s*".join(parts)
    return re.compile(rf"^{pattern}\s*$", re.IGNORECASE)


@dataclass
class Rule:
    trigger: str
    response: str
    topic: str = "random"  # topic onde a regra é válida
    priority: int = 0
    arrays: dict[str, list[str]] | None = None

    # compilado
    _regex: re.Pattern[str] = field(default=None, repr=False)  # type: ignore[assignment]
    specificity: int = 0

    def __post_init__(self) -> None:
        tokens = _TRIGGER_TOKEN_RE.findall(self.trigger.strip().lower())
        self.specificity = _specificity(tokens)
        self._regex = compile_trigger(self.trigger, self.arrays)


@dataclass
class RuleMatch:
    rule: Rule
    stars: list[str] = field(default_factory=list)
    response: str = ""
    next_topic: str = "random"


def _normalize(text: str) -> str:
    """Normaliza a entrada para o matching: minúsculas, sem pontuação final,
    sem prefixos de chamada/filler. NÃO remove filler do final (um pedido
    real com 'por favor' no fim não pode virar um trigger curto)."""
    low = text.strip().lower()
    # pontuação final (?, !, .) não deve quebrar o matching
    low = re.sub(r"[?!.]+$", "", low).strip()
    low = _NAME_PREFIX_RE.sub("", low)
    prev = None
    while prev != low:
        prev = low
        low = _FILLER_PREFIX_RE.sub("", low)
    low = re.sub(r"\s+", " ", low).strip()
    # vírgulas/dois-pontos soltos que sobraram do prefixo
    low = re.sub(r"^[,:;\s]+", "", low)
    return low


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
            ! array nome = a b c
            [topic audiobook]
            leia [o livro] * → <call>audiobook read <star></call>{topic=audiobook}
        """
        fp = cls()
        current_topic = topic
        arrays: dict[str, list[str]] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("! array "):
                _, _, rest = line.partition("! array ")
                name, _, values = rest.partition("=")
                arrays[name.strip().lower()] = [
                    v.strip().lower() for v in values.split() if v.strip()
                ]
                continue
            if line.startswith("[topic "):
                current_topic = line[len("[topic ") : -1].strip()
                continue
            if "→" in line:
                trigger, _, response = line.partition("→")
                fp.add(trigger.strip(), response.strip(), topic=current_topic, arrays=arrays)
        return fp

    @classmethod
    def from_file(cls, path: str | Path) -> "FastPaths":
        return cls.from_text(Path(path).read_text(encoding="utf-8"))

    def add(
        self,
        trigger: str,
        response: str,
        *,
        topic: str = "random",
        priority: int = 0,
        arrays: dict[str, list[str]] | None = None,
    ) -> None:
        self._rules.append(Rule(trigger, response, topic=topic, priority=priority, arrays=arrays))

    def register(self, name: str, handler: Callable[[list[str]], str]) -> None:
        """Registra um macro executável: <call>nome arg1 arg2</call>."""
        self._handlers[name] = handler

    # --- matching ---

    def match(self, text: str) -> RuleMatch | None:
        """Encontra a melhor regra: topic atual primeiro, depois globais.

        Ordenação por especificidade (espírito do RiveScript): mais tokens
        literais vencem, depois prioridade explícita, depois trigger mais
        longo. Isso garante que `quanto é # + #` não perca para
        `[*] quanto é [*]` e que regras genéricas nunca roubem específicas.
        """
        low = _normalize(text)
        if not low:
            return None
        # 1) regras do topic atual (contexto explícito tem prioridade)
        for rule in sorted(
            (r for r in self._rules if r.topic == self._topic),
            key=lambda r: (-r.priority, -r.specificity, -len(r.trigger)),
        ):
            m = rule._regex.match(low)
            if m:
                return self._expand(rule, m.groups())
        # 2) regras globais (random) — específicas antes de genéricas
        for rule in sorted(
            (r for r in self._rules if r.topic == "random"),
            key=lambda r: (-r.specificity, -r.priority, -len(r.trigger)),
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
        # <star1>, <star2>, ... (multi-wildcard) e <star> (compat)
        response = re.sub(
            r"<star(\d)>",
            lambda mm: stars[int(mm.group(1)) - 1] if int(mm.group(1)) <= len(stars) else "",
            response,
        )
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
# Regras default — portadas/enriquecidas do RiveScript do legado
# (AI_SYSTEM/orchestrator/brain/core/{audiobook,fast_paths}.rive)
# ---------------------------------------------------------------------------

DEFAULT_RULES = """\
# Fast paths do JARVIS — inspirado no RiveScript do legado
# (AI_SYSTEM/orchestrator/brain). Formato:
#   ! array nome = a b c          → sinônimos (acentos/idiomas)
#   trigger → resposta            → regra; trigger pode usar:
#       * = 1+ palavras | [*] = 0+ palavras | # = número
#       (a|b) = alternativas | [x] = opcional | @nome = array
#   <call>macro args</call> executa código; {topic=nome} troca de contexto.
#
# SEGURANÇA: o matching é ANCORADO (a frase inteira normalizada tem que
# casar). Trigger curto como `cpu` só casa a frase EXATAMENTE "cpu" — nunca
# "explique como funciona uma cpu" (isso vai pro LLM). Comandos com efeito
# não entram aqui: passam pelo agente com aprovação.

# --- arrays de sinônimos (acentos/variações PT-BR/EN) ---
! array ler = ler leia le lê leio
! array livro = livro book audiobook audio áudio
! array memoria = memoria memória memòria mémoria ram
! array cpu = cpu processador
! array disco = disco hd armazenamento storage
! array hora = hora horas hòras hóras
! array sao = sao são sào sáo é e eh
! array dia = dia data
! array qual = qual quais quàl quál

[topic random]
# --- AUDIOBOOK: iniciar / listar / escanear (entra no tópico) ---
@ler [o] [@livro] * → <call>audiobook read <star></call>{topic=audiobook}
read [the] [book] * → <call>audiobook read <star></call>{topic=audiobook}
quais livros [tenho|tem|existem] → <call>audiobook list</call>
meus livros → <call>audiobook list</call>
lista [de] livros → <call>audiobook list</call>
biblioteca → <call>audiobook list</call>
meus ebooks → <call>audiobook list</call>
acervo [de livros] → <call>audiobook list</call>
tem na biblioteca → <call>audiobook list</call>
o que tem para ler → <call>audiobook list</call>
procura [por] livros → <call>audiobook scan</call>
procura [por] ebooks → <call>audiobook scan</call>
busca [por] livros → <call>audiobook scan</call>
index [my] books → <call>audiobook scan</call>
pausa [a leitura] → <call>audiobook pause</call>{topic=audiobook}
continua [a leitura] → <call>audiobook resume</call>{topic=audiobook}
para de ler → <call>audiobook stop</call>{topic=random}

# --- AUDIOBOOK tópico: comandos curtos (só valem dentro do contexto) ---
[topic audiobook]
para → <call>audiobook pause</call>{topic=audiobook}
pare → <call>audiobook pause</call>{topic=audiobook}
pausa → <call>audiobook pause</call>{topic=audiobook}
stop → <call>audiobook pause</call>{topic=audiobook}
continua → <call>audiobook resume</call>{topic=audiobook}
continue → <call>audiobook resume</call>{topic=audiobook}
resume → <call>audiobook resume</call>{topic=audiobook}
proximo → <call>audiobook next</call>{topic=audiobook}
próximo → <call>audiobook next</call>{topic=audiobook}
próximo [capítulo|capitulo] → <call>audiobook next</call>{topic=audiobook}
next → <call>audiobook next</call>{topic=audiobook}
anterior → <call>audiobook prev</call>{topic=audiobook}
capítulo anterior → <call>audiobook prev</call>{topic=audiobook}
capitulo anterior → <call>audiobook prev</call>{topic=audiobook}
previous → <call>audiobook prev</call>{topic=audiobook}
onde estou → <call>audiobook status</call>{topic=audiobook}
status → <call>audiobook status</call>{topic=audiobook}

[topic random]
# --- VOZ (TTS): só regras com "voz"/"voice" (específicas, não roubam pedidos) ---
(mude|muda|mudar|troque|trocar|altere|alterar) [a] voz [para] * → <call>voice set <star></call>
(mude|muda|mudar|troque|trocar|altere|alterar) [para] [a] voz * → <call>voice set <star></call>
use [a] voz * → <call>voice set <star></call>
use voice * → <call>voice set <star></call>
(change|switch) [the] voice to * → <call>voice set <star></call>
listar vozes → <call>voice list</call>
quais vozes [tem|existem] → <call>voice list</call>
fale mais rápido → <call>voice rate up</call>
fale mais devagar → <call>voice rate down</call>
fala mais rápido → <call>voice rate up</call>
fala mais devagar → <call>voice rate down</call>

# --- SISTEMA (read-only, zero LLM, resposta em ms) ---
# Nota: regras de memória/disco DEVEM vir antes do trigger genérico do
# doctor ("memória") para o roteador não roubar o pedido.
uso [de|do] @cpu → <call>sys ps aux --sort=-%cpu</call>
status [do|da] @cpu → <call>sys ps aux --sort=-%cpu</call>
@cpu → <call>sys ps aux --sort=-%cpu</call>
uso [de|da] @memoria → <call>sys free -h</call>
uso da memória → <call>sys free -h</call>
qual o uso de @memoria → <call>sys free -h</call>
qual é o uso de @memoria → <call>sys free -h</call>
como está o uso de @memoria → <call>sys free -h</call>
como está o uso de ram → <call>sys free -h</call>
quanta @memoria [tem|está usando|livre] → <call>sys free -h</call>
quanto de @memoria [tem|está usando|livre] → <call>sys free -h</call>
@memoria [do sistema] → <call>sys free -h</call>
a @memoria → <call>sys free -h</call>
ram [livre|usada|em uso] → <call>sys free -h</call>
espaço em disco → <call>sys df -h /</call>
espaço no disco → <call>sys df -h /</call>
disco [cheio|livre|em uso] → <call>sys df -h /</call>
quanto de disco [tem|livre] → <call>sys df -h /</call>
uso de disco → <call>sys df -h /</call>
@disco → <call>sys df -h /</call>
quanto tempo [o] [sistema] [está] ligado → <call>sys uptime</call>
uptime → <call>sys uptime</call>
qual kernel → <call>sys uname -r</call>
versão do kernel → <call>sys uname -r</call>
processos [ativos|rodando] → <call>sys ps aux --sort=-%mem</call>
@temp → <call>sys cat /sys/class/thermal/thermal_zone0/temp</call>
temperatura → <call>sys cat /sys/class/thermal/thermal_zone0/temp</call>

# --- HORA E DATA (date é read-only e está na allowlist) ---
que @hora @sao → <call>sys date +%H:%M</call>
me diz [as] @hora → <call>sys date +%H:%M</call>
@qual [é|são] [as] @hora → <call>sys date +%H:%M</call>
what time is it → <call>sys date +%H:%M</call>
what [is] the time → <call>sys date +%H:%M</call>
que @dia [é] [hoje] → <call>sys date +%d/%m/%Y</call>
que @dia @sao hoje → <call>sys date +%d/%m/%Y</call>
qual [é] [a] @dia [de hoje] → <call>sys date +%d/%m/%Y</call>
what date is it → <call>sys date +%d/%m/%Y</call>
what [is] the date → <call>sys date +%d/%m/%Y</call>

# --- MATEMÁTICA simples (zero LLM; # = número). O operador é `*`
# (capturado) e o avaliador é ast-safe; expressões sem números não casam. ---
quanto é # * # → <call>math <star1> <star2> <star3></call>
quanto fica # * # → <call>math <star1> <star2> <star3></call>
qual é # * # → <call>math <star1> <star2> <star3></call>
what is # * # → <call>math <star1> <star2> <star3></call>

# --- SCREENSHOT (captura local via grim; análise visual vai pro LLM) ---
[*] (tire|tira|tirar|capture|captura|capturar) [*] (print|screenshot|print da tela|captura de tela|foto da tela) [*] → <call>screenshot</call>
screenshot → <call>screenshot</call>
print [da tela] → <call>screenshot</call>
captura de tela → <call>screenshot</call>
capturar a tela → <call>screenshot</call>

# --- SAUDAÇÕES (resposta instantânea; só casam frase EXATA) ---
(ola|olá) → Olá! 👋
oi → Oi! 👋
e aí → E aí! 👋
e ai → E aí! 👋
bom dia → Bom dia! ☀️
boa tarde → Boa tarde! 🌤️
boa noite → Boa noite! 🌙
hello → Hello! 👋
hi → Hi! 👋
hey → Hey! 👋
"""