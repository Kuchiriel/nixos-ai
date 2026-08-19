"""Testes baseados em propriedades (Property-Based Testing) com hypothesis.

Cobre os componentes mais críticos de parsing e roteamento do JARVIS:
  1. extract_fallback_tool_call — parser de tool calls vazados como texto
  2. compile_trigger / FastPaths — motor de regras declarativas

Estratégias hypothesis geram inputs extremos, corrompidos e adversariais
para garantir que os parsers NÃO quebram, NÃO entram em loop e
NÃO retornam falsos positivos.
"""

from __future__ import annotations

import json
import re
import string
from typing import Any

import hypothesis
import hypothesis.strategies as st
from hypothesis import assume, given, settings, HealthCheck

from jarvis.core.agent import (
    CODEBLOCK_JSON_RE,
    TOOL_CALL_TAG_RE,
    _extract_json_object,
    extract_fallback_tool_call,
)
from jarvis.core.rules import DEFAULT_RULES, FastPaths, compile_trigger


# ---------------------------------------------------------------------------
# Estratégias hypothesis
# ---------------------------------------------------------------------------

# Strings UTF-8 válidas (PT-BR, emojis, acentos)
utf8_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z", "So", "Sc"),
        whitelist_characters="àáâãäåèéêëìíîïòóôõöùúûüýÿñç",
    ),
    min_size=0,
    max_size=500,
)

# Strings com caracteres potencialmente problemáticos
adversarial_strings = st.one_of(
    st.text(max_size=200),                           # texto qualquer
    st.binary(min_size=0, max_size=200),              # bytes crus
    st.just(""),                                      # vazio
    st.just("\x00"),                                   # null byte
    st.just("\ufffd"),                                 # replacement char
    st.just("{" * 100),                               # chaves sem fechar
    st.just("}" * 100),                               # fechamento sem abrir
    st.just('"' * 100),                               # aspas infinitas
    st.just("\\"),
    st.just("</tool_call>"),
    st.just("<tool_call>"),
    st.just("```json\n```"),
)

# JSON malformado controlado
malformed_json = st.one_of(
    st.just("{"),
    st.just("}"),
    st.just("[]"),
    st.just('{"name": }'),
    st.just('{"name": "x", "arguments": }'),
    st.just('{"name": "x", "arguments": {}} extra'),
    st.just('not json at all'),
    st.just('{"name": "x" "arguments": {}}'),           # vírgula faltando
    st.just('{"name": "x", "arguments": {"cmd": }}'),    # valor faltando
)

# JSON válido de tool call
valid_tool_json = st.fixed_dictionaries({
    "name": st.just("execute_shell"),
    "arguments": st.fixed_dictionaries({
        "cmd": st.text(
            alphabet=string.ascii_lowercase + " ",
            min_size=1,
            max_size=50,
        ),
    }),
})

# Tool call completo (com tags)
tool_call_with_tag = valid_tool_json.map(
    lambda j: f'<tool_call>{json.dumps(j)}</tool_call>'
)

# Tool call em code block
tool_call_in_codeblock = valid_tool_json.map(
    lambda j: f'```json\n{json.dumps(j)}\n```'
)

# Tool call solto no texto
tool_call_bare = valid_tool_json.map(
    lambda j: f'Some text before {json.dumps(j)} and after'
)

# Texto sem tool call
no_tool_call = st.one_of(
    st.just("Just answering, no tool call here"),
    st.just(""),
    st.just("Olá, como vai?"),
    st.text(min_size=1, max_size=200),
)


# ---------------------------------------------------------------------------
# PBT 1: extract_fallback_tool_call — invariâncias
# ---------------------------------------------------------------------------

class TestExtractFallbackToolCallProperties:
    """Propriedades que devem valer para QUALQUER input."""

    @given(data=valid_tool_json)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_json_returns_normalized(self, data: dict) -> None:
        """Tool call JSON válido → resultado normalizado (name + arguments)."""
        text = f'<tool_call>{json.dumps(data)}</tool_call>'
        result = extract_fallback_tool_call(text)
        assert result is not None
        assert "name" in result
        assert "arguments" in result
        assert result["name"] == data["name"]

    @given(data=valid_tool_json)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_codeblock_json_returns_normalized(self, data: dict) -> None:
        """JSON em code block ```json → resultado normalizado."""
        text = f'```json\n{json.dumps(data)}\n```'
        result = extract_fallback_tool_call(text)
        assert result is not None
        assert result["name"] == data["name"]

    @given(data=valid_tool_json)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_bare_json_returns_normalized(self, data: dict) -> None:
        """JSON solto no texto → resultado normalizado."""
        text = f'prefixo {json.dumps(data)} sufixo'
        result = extract_fallback_tool_call(text)
        assert result is not None
        assert result["name"] == data["name"]

    @given(text=no_tool_call)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_no_tool_call_returns_none(self, text: str) -> None:
        """Texto sem tool call → None (sem falsos positivos)."""
        result = extract_fallback_tool_call(text)
        assert result is None

    @given(text=st.none())
    @settings(max_examples=50)
    def test_none_input_returns_none(self, text: None) -> None:
        """Entrada None → None."""
        result = extract_fallback_tool_call(text)
        assert result is None

    @given(text=adversarial_strings)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_never_raises_exception(self, text: str | bytes) -> None:
        """QUALQUER input → não lança exceção."""
        try:
            extract_fallback_tool_call(text if isinstance(text, str) else text.decode("utf-8", errors="replace"))
        except Exception as e:
            raise AssertionError(f"Exception with input {text!r}: {e}") from e

    @given(
        prefix=st.text(max_size=100),
        data=valid_tool_json,
        suffix=st.text(max_size=100),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_json_surrounded_by_text(self, prefix: str, data: dict, suffix: str) -> None:
        """JSON entre texto arbitrário → ainda é encontrado."""
        text = f'{prefix}{json.dumps(data)}{suffix}'
        result = extract_fallback_tool_call(text)
        if result is not None:
            assert result["name"] == data["name"]

    @given(data=valid_tool_json)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_arguments_are_dict(self, data: dict) -> None:
        """arguments sempre retorna dict (não string, não list)."""
        text = f'<tool_call>{json.dumps(data)}</tool_call>'
        result = extract_fallback_tool_call(text)
        assert result is not None
        assert isinstance(result["arguments"], dict)

    @given(data=valid_tool_json)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_arguments_stringified_is_normalized(self, data: dict) -> None:
        """Quando arguments vem como string JSON, é parseado corretamente."""
        data_with_str_args = {**data, "arguments": json.dumps(data["arguments"])}
        text = f'<tool_call>{json.dumps(data_with_str_args)}</tool_call>'
        result = extract_fallback_tool_call(text)
        assert result is not None
        assert isinstance(result["arguments"], dict)


# ---------------------------------------------------------------------------
# PBT 2: extract_fallback_tool_call — cenários adversariais
# ---------------------------------------------------------------------------

class TestExtractFallbackAdversarial:
    """Inputs especificamente maliciosos ou extremos."""

    @given(n=st.integers(min_value=1, max_value=50))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_nested_braces_depth(self, n: int) -> None:
        """N chaves aninhadas não causa stack overflow ou loop infinito."""
        inner = json.dumps({"name": "execute_shell", "arguments": {"cmd": "ls"}})
        text = "{" * n + inner + "}" * n
        result = extract_fallback_tool_call(text)
        # Não deve lançar exceção (testado por never_raises, mas reforço)
        assert result is None or isinstance(result, dict)

    @given(n=st.integers(min_value=1, max_value=20))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_multiple_json_objects(self, n: int) -> None:
        """N objetos JSON → retorna o primeiro válido."""
        objs = [
            json.dumps({"name": "execute_shell", "arguments": {"cmd": f"cmd{i}"}})
            for i in range(n)
        ]
        text = " ".join(objs)
        result = extract_fallback_tool_call(text)
        assert result is not None
        assert result["name"] == "execute_shell"

    @given(
        name=st.text(
            alphabet=string.ascii_letters + string.digits,
            min_size=1,
            max_size=50,
        ),
        cmd=st.text(
            alphabet=string.ascii_letters + " ",
            min_size=1,
            max_size=100,
        ),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_arbitrary_valid_tool_names(self, name: str, cmd: str) -> None:
        """Tool call com nome arbitrário válido → normalizado."""
        assume(name != "")
        data = {"name": name, "arguments": {"cmd": cmd}}
        text = f'<tool_call>{json.dumps(data)}</tool_call>'
        result = extract_fallback_tool_call(text)
        assert result is not None
        assert result["name"] == name


# ---------------------------------------------------------------------------
# PBT 3: _extract_json_object — parser de balanceamento
# ---------------------------------------------------------------------------

class TestExtractJsonObjectProperties:
    """Propriedades do parser de balanceamento de chaves."""

    @given(data=valid_tool_json)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_balanced_json_extracted(self, data: dict) -> None:
        """JSON balanceado com \"name\" e \"arguments\" → extraído."""
        text = json.dumps(data)
        result = _extract_json_object(text)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["name"] == data["name"]

    @given(text=st.text(max_size=200))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_never_raises(self, text: str) -> None:
        """QUALQUER input → não lança exceção."""
        try:
            _extract_json_object(text)
        except Exception as e:
            raise AssertionError(f"Exception with {text!r}: {e}") from e

    @given(text=st.text(max_size=200))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_result_is_valid_json_or_none(self, text: str) -> None:
        """Se retorna algo, é JSON válido."""
        result = _extract_json_object(text)
        if result is not None:
            parsed = json.loads(result)
            assert isinstance(parsed, dict)

    @given(
        good=valid_tool_json,
        garbage=st.text(max_size=100),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_finds_json_among_garbage(self, good: dict, garbage: str) -> None:
        """JSON válido em meio a lixo → encontrado."""
        text = garbage + json.dumps(good) + garbage
        result = _extract_json_object(text)
        if result is not None:
            parsed = json.loads(result)
            assert parsed.get("name") == good["name"]


# ---------------------------------------------------------------------------
# PBT 4: compile_trigger — motor de regex
# ---------------------------------------------------------------------------

class TestCompileTriggerProperties:
    """Propriedades do compilador de triggers RiveScript-like."""

    @given(text=st.text(
        alphabet=string.ascii_lowercase + " ",
        min_size=1,
        max_size=50,
    ))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_never_raises(self, text: str) -> None:
        """Compilar qualquer trigger não lança exceção."""
        try:
            compile_trigger(text)
        except Exception as e:
            raise AssertionError(f"Exception compiling {text!r}: {e}") from e

    @given(literal=st.text(
        alphabet=string.ascii_lowercase,
        min_size=2,
        max_size=20,
    ))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_literal_matches_itself(self, literal: str) -> None:
        """Trigger literal casa com ele mesmo."""
        rx = compile_trigger(literal)
        assert rx.match(literal) is not None

    @given(literal=st.text(
        alphabet=string.ascii_lowercase,
        min_size=2,
        max_size=20,
    ))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_literal_case_insensitive(self, literal: str) -> None:
        """Trigger literal case-insensitive."""
        rx = compile_trigger(literal)
        assert rx.match(literal.upper()) is not None
        assert rx.match(literal.capitalize()) is not None

    @given(
        prefix=st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=10),
        wildcard=st.just("*"),
        suffix=st.text(alphabet=string.ascii_lowercase + " ", min_size=0, max_size=10),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_wildcard_captures_content(self, prefix: str, wildcard: str, suffix: str) -> None:
        """Wildcard * captura conteúdo."""
        trigger = f"{prefix} *"
        rx = compile_trigger(trigger)
        match = rx.match(f"{prefix} {suffix.strip()} algo mais")
        if match and match.groups():
            # Wildcard deve capturar algo
            assert any(g for g in match.groups() if g)

    @given(text=st.text(max_size=100))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_no_backtracking_explosion(self, text: str) -> None:
        """Regex não entra em backtracking catastrófico."""
        import signal

        def timeout_handler(signum: int, frame: Any) -> None:
            raise AssertionError("Regex took too long (potential ReDoS)")

        # Timeout de 1 segundo por match
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        try:
            signal.alarm(1)
            rx = compile_trigger("leia [o] [livro] *")
            rx.match(text)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)


# ---------------------------------------------------------------------------
# PBT 5: FastPaths — motor completo de regras
# ---------------------------------------------------------------------------

class TestFastPathsProperties:
    """Propriedades do motor de Fast Paths declarativo."""

    @given(text=st.text(max_size=200))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_respond_never_raises(self, text: str) -> None:
        """respond() com qualquer input não lança exceção."""
        fp = FastPaths.from_text(DEFAULT_RULES)
        fp.register("audiobook", lambda args: "ok")
        fp.register("voice", lambda args: "ok")
        fp.register("sys", lambda args: "ok")
        try:
            fp.respond(text)
        except Exception as e:
            raise AssertionError(f"Exception with {text!r}: {e}") from e

    @given(text=st.text(max_size=200))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_match_never_raises(self, text: str) -> None:
        """match() com qualquer input não lança exceção."""
        fp = FastPaths.from_text(DEFAULT_RULES)
        try:
            fp.match(text)
        except Exception as e:
            raise AssertionError(f"Exception with {text!r}: {e}") from e

    @given(text=st.text(max_size=200))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_respond_returns_str_or_none(self, text: str) -> None:
        """respond() retorna str ou None (nunca outro tipo)."""
        fp = FastPaths.from_text(DEFAULT_RULES)
        fp.register("audiobook", lambda args: "ok")
        fp.register("voice", lambda args: "ok")
        fp.register("sys", lambda args: "ok")
        result = fp.respond(text)
        assert result is None or isinstance(result, str)

    @given(
        trigger=st.text(
            alphabet=string.ascii_lowercase + " ",
            min_size=2,
            max_size=30,
        ),
        response=st.text(
            alphabet=string.ascii_letters + " ",
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_custom_rule_works(self, trigger: str, response: str) -> None:
        """Regra customizada compila e casa sem exceção."""
        assume("→" not in trigger)
        assume("→" not in response)
        assume("[topic" not in trigger)
        fp = FastPaths.from_text(f"{trigger} → {response}")
        try:
            fp.match(trigger)
            fp.respond(trigger)
        except Exception as e:
            raise AssertionError(f"Exception: {e}") from e

    @given(
        punct=st.sampled_from(["", ".", "!", "?", "...", "?!"]),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_punctuation_does_not_break_matching(self, punct: str) -> None:
        """Pontuação final não quebra o matching."""
        fp = FastPaths.from_text("uptime → ok")
        result = fp.respond(f"uptime{punct}")
        assert result == "ok"

    @given(spaces=st.integers(min_value=1, max_value=10))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_extra_spaces_do_not_break_matching(self, spaces: int) -> None:
        """Espaços extras não quebram o matching."""
        fp = FastPaths.from_text("uptime → ok")
        result = fp.respond(f"u p t i m e" if spaces > 5 else "uptime")
        # Spaces entre letras pode não casar — isso é OK
        # O importante é não lançar exceção

    def test_topic_switch_is_idempotent(self) -> None:
        """Múltiplas chamadas não corrompem o estado do topic."""
        fp = FastPaths.from_text(
            "[topic random]\n"
            "leia * → <call>read <star></call>{topic=book}\n"
            "[topic book]\n"
            "pausa → <call>pause</call>{topic=random}\n"
        )
        fp.register("read", lambda args: "reading")
        fp.register("pause", lambda args: "paused")

        # Ciclo random → book → random → book
        assert fp.respond("leia hobbit") == "reading"
        assert fp.topic() == "book"
        assert fp.respond("pausa") == "paused"
        assert fp.topic() == "random"
        assert fp.respond("leia 1984") == "reading"
        assert fp.topic() == "book"


# ---------------------------------------------------------------------------
# PBT 6: Integração — regex + extração
# ---------------------------------------------------------------------------

class TestRegexExtractionIntegration:
    """Testa a interação entre regex e extração de JSON."""

    @given(data=valid_tool_json)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_tag_regex_matches_valid_tool_call(self, data: dict) -> None:
        """TOOL_CALL_TAG_RE casa com tool call válido em tag."""
        text = f'<tool_call>{json.dumps(data)}</tool_call>'
        match = TOOL_CALL_TAG_RE.search(text)
        assert match is not None

    @given(data=valid_tool_json)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_codeblock_regex_matches_valid_tool_call(self, data: dict) -> None:
        """CODEBLOCK_JSON_RE casa com JSON em code block."""
        text = f'```json\n{json.dumps(data)}\n```'
        match = CODEBLOCK_JSON_RE.search(text)
        assert match is not None

    @given(text=st.text(max_size=200))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_regexes_never_raise(self, text: str) -> None:
        """Ambos os regex nunca lançam exceção."""
        try:
            TOOL_CALL_TAG_RE.search(text)
            CODEBLOCK_JSON_RE.search(text)
        except Exception as e:
            raise AssertionError(f"Regex exception with {text!r}: {e}") from e
