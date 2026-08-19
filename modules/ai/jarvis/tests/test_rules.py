"""Testes do motor de fast paths declarativos (core/rules.py)."""

from jarvis.core.rules import DEFAULT_RULES, FastPaths, compile_trigger
from jarvis.core.router import get_fast_paths, route_request


# ---------------------------------------------------------------------------
# compile_trigger
# ---------------------------------------------------------------------------


def test_compile_trigger_literal() -> None:
    rx = compile_trigger("pausa a leitura")
    assert rx.match("pausa a leitura")
    assert rx.match("PAUSA A LEITURA")
    assert not rx.match("pausa o filme")


def test_compile_trigger_wildcard() -> None:
    rx = compile_trigger("leia o livro *")
    assert rx.match("leia o livro hobbit")
    assert rx.match("leia o livro o senhor dos aneis")
    assert not rx.match("leia o livro")


def test_compile_trigger_optional() -> None:
    rx = compile_trigger("leia [o] [livro] *")
    assert rx.match("leia hobbit")
    assert rx.match("leia o livro hobbit")
    assert rx.match("leia livro hobbit")


def test_compile_trigger_alternatives() -> None:
    rx = compile_trigger("quais livros [tenho|tem]")
    assert rx.match("quais livros tenho")
    assert rx.match("quais livros tem")


# ---------------------------------------------------------------------------
# FastPaths (matching, topics, macros)
# ---------------------------------------------------------------------------


def test_from_text_and_match() -> None:
    fp = FastPaths.from_text(
        "# comentário\n"
        "ola mundo → <call>echo hello</call>\n"
        "tchau → até logo\n"
    )
    fp.register("echo", lambda args: f"echo:{args[0] if args else ''}")
    assert fp.respond("ola mundo") == "echo:hello"
    assert fp.respond("TCHAU") == "até logo"
    assert fp.respond("nada a ver") is None


def test_topic_context_switch() -> None:
    fp = FastPaths.from_text(
        "[topic random]\n"
        "leia o livro * → <call>audio read <star></call>{topic=audiobook}\n"
        "pausa → <call>audio pause</call>\n"
        "[topic audiobook]\n"
        "pausa → <call>audio pause</call>{topic=random}\n"
    )
    fp.register("audio", lambda args: f"audio:{args[0] if args else ''}")
    # fora do topic, "pausa" não casa (só a global de leitura)
    assert fp.respond("leia o livro hobbit") == "audio:read"
    assert fp.topic() == "audiobook"
    # dentro do topic, "pausa" casa e volta pro random
    assert fp.respond("pausa") == "audio:pause"
    assert fp.topic() == "random"


def test_star_content_passed_to_macro() -> None:
    fp = FastPaths.from_text("toca * → <call>player play <star></call>")
    fp.register("player", lambda args: f"playing:{' '.join(args)}")
    # o macro recebe [play, música, jazz] (ação + conteúdo do star)
    assert fp.respond("toca música jazz") == "playing:play música jazz"


def test_priority_specific_first() -> None:
    fp = FastPaths()
    fp.add("para", "genérico", priority=0)
    fp.add("para de ler", "específico", priority=10)
    assert fp.respond("para de ler") == "específico"


# ---------------------------------------------------------------------------
# Regras default + integração com o roteador
# ---------------------------------------------------------------------------


def test_default_rules_have_audiobook() -> None:
    fp = FastPaths.from_text(DEFAULT_RULES)
    fp.register("audiobook", lambda args: "ok")
    fp.register("voice", lambda args: "ok")
    assert fp.respond("leia o livro hobbit") == "ok"
    assert fp.respond("quais livros tenho") == "ok"
    assert fp.respond("mude para a voz feminina") == "ok"


def test_route_fastpath() -> None:
    # o roteador reconhece comandos de audiobook/voz como fastpath (zero LLM)
    for text in [
        "leia o livro hobbit",
        "pausa a leitura",
        "mude para a voz grave",
        "listar vozes",
    ]:
        assert route_request(text).handler == "fastpath", text


def test_route_fastpath_sys_commands() -> None:
    # comandos de sistema read-only respondem em ms, sem LLM; o doctor não
    # rouba pedidos que são comandos diretos (ex: "memória")
    for text in [
        "quanto de memória tem?",
        "qual o uso de memória?",
        "uso de ram",
        "uso de disco",
        "espaço em disco",
        "quanto tempo o sistema está ligado",
        "qual kernel?",
        "processos ativos",
    ]:
        assert route_request(text).handler == "fastpath", text
    # saúde geral continua no doctor
    assert route_request("como está a saúde do sistema?").handler == "doctor"


def test_fastpath_sys_executes_and_blocks() -> None:
    from jarvis.core.router import get_fast_paths

    fp = get_fast_paths()
    # comando da allowlist roda (retorna a saída real de uptime)
    out = fp.respond("quanto tempo o sistema está ligado")
    assert isinstance(out, str) and "up" in out
    # comando FORA da allowlist é bloqueado (nunca executa via fast path)
    blocked = fp.respond("processos ativos")
    assert blocked is None or "não permitido" not in blocked


def test_match_ignores_final_punctuation() -> None:
    fp = FastPaths.from_text("oi * → <call>hi <star></call>")
    assert fp.match("oi mundo?") is not None
    assert fp.match("oi tudo bem!") is not None


def test_route_still_falls_to_agent() -> None:
    assert route_request("explique o conceito de recursão").handler == "agent"


def test_get_fast_paths_singleton() -> None:
    assert get_fast_paths() is get_fast_paths()
