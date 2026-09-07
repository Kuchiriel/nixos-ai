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


# ---------------------------------------------------------------------------
# Motor enriquecido (portado do RiveScript do legado)
# ---------------------------------------------------------------------------


def test_array_synonyms_expand() -> None:
    fp = FastPaths.from_text(
        "! array memoria = memoria memória memòria\n"
        "uso de @memoria → ok\n"
    )
    assert fp.respond("uso de memoria") == "ok"
    assert fp.respond("uso de memória") == "ok"
    assert fp.respond("uso de memòria") == "ok"
    assert fp.respond("uso de ram") is None  # fora do array


def test_array_inside_optional() -> None:
    # `[@livro]` precisa expandir o array (não virar literal "@livro")
    fp = FastPaths.from_text(
        "! array livro = livro book audiobook\n"
        "! array ler = ler leia le lê leio\n"
        "@ler [o] [@livro] * → read <star>\n"
    )
    assert fp.respond("leia o livro hobbit") == "read hobbit"
    assert fp.respond("ler book dune") == "read dune"
    assert fp.respond("leia hobbit") == "read hobbit"


def test_array_longest_alternative_wins() -> None:
    # "leio" não pode ser roubado pela alternativa "le" (prefixo)
    fp = FastPaths.from_text(
        "! array ler = ler leia le lê leio\n"
        "@ler * → read <star>\n"
    )
    assert fp.respond("leio audiobook the martian") == "read audiobook the martian"


def test_optional_wildcard_star_brackets() -> None:
    fp = FastPaths.from_text(
        "[*] (tire|tira|tirar) [*] (print|screenshot) [*] → shot\n"
    )
    assert fp.respond("tira um print") == "shot"
    assert fp.respond("pode tirar um print pra mim") == "shot"
    # sem o verbo (tire/tira/tirar), a regra NÃO casa — "screenshot"
    # puro é outra regra (trigger literal) no DEFAULT_RULES
    assert fp.respond("screenshot") is None
    assert fp.respond("tira uma foto da paisagem") is None  # sem print/screenshot


def test_numeric_wildcard_math() -> None:
    fp = FastPaths.from_text("quanto é # * # → <call>m <star1> <star2> <star3></call>")
    fp.register("m", lambda args: "|".join(args))
    assert fp.respond("quanto é 8 + 2") == "8|+|2"
    assert fp.respond("quanto é 5,5 + 1,5") == "5,5|+|1,5"
    assert fp.respond("quanto é a capital da frança") is None  # sem números


def test_normalization_strips_name_and_filler() -> None:
    fp = FastPaths.from_text("leia [o] [livro] * → ok\nquanto de memória tem → ok2\n")
    assert fp.respond("jarvis, leia o livro hobbit") == "ok"
    assert fp.respond("hey jarvis leia hobbit") == "ok"
    assert fp.respond("ei jarvis, por favor, leia o livro hobbit") == "ok"
    assert fp.respond("por favor, quanto de memória tem?") == "ok2"


def test_normalization_does_not_steal_real_requests() -> None:
    # filler/prefix stripping NUNCA pode transformar uma pergunta real
    # em um trigger curto (ex.: "boa tarde, qual a capital da frança")
    fp = FastPaths.from_text(
        "boa tarde → Boa tarde!\n"
        "cpu → cpu status\n"
    )
    assert fp.respond("boa tarde") == "Boa tarde!"
    assert fp.respond("boa tarde, qual a capital da frança") is None
    assert fp.respond("cpu") == "cpu status"
    assert fp.respond("explique como funciona uma cpu") is None


def test_specificity_literal_count_first() -> None:
    # com literais iguais, `#` (número) vence `[*]` (wildcard opcional)
    fp = FastPaths()
    fp.add("[*] quanto é [*]", "generico")
    fp.add("quanto é # * #", "especifico")
    assert fp.respond("quanto é 8 + 2") == "especifico"


def test_topic_short_commands_stay_in_topic() -> None:
    fp = FastPaths.from_text(
        "[topic random]\n"
        "leia o livro * → <call>audio read <star></call>{topic=audiobook}\n"
        "[topic audiobook]\n"
        "pausa → <call>audio pause</call>{topic=audiobook}\n"
        "continua → <call>audio resume</call>{topic=audiobook}\n"
        "proximo → <call>audio next</call>{topic=audiobook}\n"
    )
    fp.register("audio", lambda args: f"audio:{args[0]}")
    assert fp.respond("leia o livro hobbit") == "audio:read"
    assert fp.topic() == "audiobook"
    assert fp.respond("pausa") == "audio:pause"
    assert fp.topic() == "audiobook"  # pausa não expulsa do tópico
    assert fp.respond("continua") == "audio:resume"
    assert fp.topic() == "audiobook"
    assert fp.respond("proximo") == "audio:next"


def test_route_math_and_screenshot_fastpath() -> None:
    assert route_request("quanto é 8 + 2").handler == "fastpath"
    assert route_request("tira um print").handler == "fastpath"
    assert route_request("quanto é 8 + 2 + 3").handler == "fastpath"


def test_route_math_answer_correct() -> None:
    from jarvis.core.router import handle_fastpath

    assert handle_fastpath("quanto é 8 + 2")["response"] == "10"
    assert handle_fastpath("quanto é 8 dividido por 2")["response"] == "4"
    assert handle_fastpath("quanto é 8 + 2 + 3")["response"] == "13"
    assert handle_fastpath("quanto é 2 vezes 3")["response"] == "6"


def test_real_questions_never_match_fastpath() -> None:
    for text in [
        "explique o conceito de recursão",
        "o que você acha do livro que escrevi",
        "que livros você recomenda",
        "quanto é a capital da frança",
        "qual a temperatura da cpu agora",
        "me conta uma piada",
        "boa tarde, qual a capital da frança",
    ]:
        assert route_request(text).handler != "fastpath", text
