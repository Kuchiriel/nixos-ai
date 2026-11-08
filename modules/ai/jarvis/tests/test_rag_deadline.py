"""RAG index: teto de relogio DURO (medido 08/11: rag-index 13h pendurado).

Um `rag-index` ficou 13h em `poll` num socket do :8081 com o servidor
saudavel (health 200 em 0,7 ms). O `index_file` tem `except Exception` no
fallback de embed (batch -> item a item), entao um TimeoutError comum seria
engolido e o hang continuaria. Por isso IndexDeadline e BaseException.
"""

from __future__ import annotations

import time

import pytest


def test_index_deadline_is_not_swallowed_by_broad_except():
    from jarvis.core.rag import IndexDeadline

    assert issubclass(IndexDeadline, BaseException)
    assert not issubclass(IndexDeadline, Exception)
    with pytest.raises(IndexDeadline):
        try:
            raise IndexDeadline("estourou")
        except Exception:  # o fallback de embed do index_file
            pytest.fail("deadline engolido pelo except Exception")


def test_hard_deadline_interrupts_a_hung_call():
    from jarvis.core.rag import IndexDeadline, _hard_deadline

    t0 = time.monotonic()
    with pytest.raises(IndexDeadline):
        with _hard_deadline(1):
            time.sleep(10)
    assert time.monotonic() - t0 < 5
