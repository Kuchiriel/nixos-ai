"""Contract B — value-free lesson lint (R2 evidence)."""
from jarvis.core.lesson_lint import (lint_lesson, numeric_profile,
                                     transform_to_rule)


def test_numeric_profile_detects_kinds():
    p = numeric_profile("At 03:17:42, 7 retries failed.")
    assert "timestamp" in p["kinds"]
    assert "count" in p["kinds"]


def test_value_free_allowed():
    r = lint_lesson("count lines", "miscounted by estimating",
                    "enumerate every matching line, count the list")
    assert r.policy == "allowed"
    assert not r.numeric_kinds


def test_episode_transformed_to_rule():
    r = lint_lesson("count lines", "miscounted",
                    "At 03:17, 7 retries failed before Qdrant error")
    assert r.policy == "transformed"
    assert "<time>" in r.transformed or "<n>" in r.transformed
    assert r.original  # proveniência preservada


def test_config_numeric_allowed():
    # porta/versão são semânticos, não episódicos
    r = lint_lesson("nixos config", "port wrong",
                    "set qdrant port to 6333")
    assert r.policy == "allowed"


def test_rule_with_numbers_suspicious():
    r = lint_lesson("count", "miscounted",
                    "always enumerate, saw 3 vs 10")
    assert r.policy in ("suspicious", "transformed")


def test_transform_to_rule_value_free():
    out = transform_to_rule("write json", "bad",
                            "at 12:00 5 files failed; enumerate first")
    assert not any(ch.isdigit() for ch in out.replace("<time>", "").replace("<n>", ""))
    assert out