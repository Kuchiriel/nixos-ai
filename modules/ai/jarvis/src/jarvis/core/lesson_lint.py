"""LESSON LINT — value-free representation contract (Contract B, R2/E6).

Empirical basis (EXP-C/R2, 20/09): lessons with episodic numeric values
degrade Bonsai (B2 1/5 vs value-free 3/3); numbers attract attention even
when labeled historical (L4 scoped 1/3). Policy: detect NUMERIC EPISODIC
DETAIL likely to act as parasitic context; transform to a generalized
value-free rule. Original episode preserved as evidence (provenance).

Categories: metric, timestamp, count, identifier, threshold, port,
version, ip, measurement, unknown.

MODEL-SPECIFIC (Bonsai/context sensitivity — §19): the numeric
attraction is configuration-specific; the lint is a representation
policy that GENERALIZES to SLMs. Kept as a policy, not a hard ban on
numbers in all knowledge (allowed where numbers are semantic truth, e.g.
ports/versions in config knowledge).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_EPISODIC_NUM = [
    (re.compile(r"\d{1,2}:\d{2}(:\d{2})?"), "timestamp"),
    (re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"), "ip"),
    (re.compile(r"\b\d{1,3}\b"), "count"),
    (re.compile(r"\d+\.\d+"), "measurement"),
    (re.compile(r"\b\d{4,5}\b"), "port"),
    (re.compile(r"\bv?\d+(\.\d+){1,3}\b"), "version"),
]

_RULE_VERBS = re.compile(
    r"classif|general|rule|always|never|when|instead|avoid|ensure|"
    r"must|repeated|detect|distinguish", re.I)


@dataclass
class LintResult:
    policy: str  # allowed | suspicious | transformed | rejected
    reason: str
    numeric_kinds: list[str] = field(default_factory=list)
    original: str = ""
    transformed: str = ""


def numeric_profile(text: str) -> dict[str, list[str]]:
    kinds: list[str] = []
    for pat, kind in _EPISODIC_NUM:
        if pat.search(text):
            kinds.append(kind)
    return {"kinds": kinds, "count": len(kinds)}


def _strip_numerics(text: str) -> str:
    out = re.sub(r"\d{1,2}:\d{2}(:\d{2})?", "<time>", text)
    out = re.sub(r"\b\d{1,3}(\.\d{1,3}){3}\b", "<ip>", out)
    out = re.sub(r"\bv?\d+(\.\d+){1,3}\b", "<n>", out)
    out = re.sub(r"\b\d+\b", "<n>", out)
    return out


def lint_lesson(task: str, error_pattern: str, fix: str) -> LintResult:
    """Classifica lesson por conteúdo numérico episódico (Policy §3):
    allowed | suspicious | transformed | rejected."""
    profile = numeric_profile(f"{task} {error_pattern} {fix}")
    if not profile["kinds"]:
        return LintResult(policy="allowed", reason="sem números episódicos",
                          original=fix)
    # Números de SEMÂNTICA de verdade (porta/versão em knowledge de
    # config) não são episódicos: fix sem verbo de regra + números de
    # porta/versão => allowed.
    if set(profile["kinds"]) <= {"port", "version", "ip"} and not _RULE_VERBS.search(fix):
        return LintResult(policy="allowed",
                          reason="números são semânticos (config knowledge)",
                          numeric_kinds=profile["kinds"], original=fix)
    # fix já é regra generalizada (verbos) apesar de números => suspicious
    if _RULE_VERBS.search(fix):
        return LintResult(policy="suspicious",
                          reason="regra + números; preferir regra limpa",
                          numeric_kinds=profile["kinds"], original=fix)
    # episódico puro => transformado para regra generalizada value-free
    generalized = _strip_numerics(fix).strip(" .:") + "."
    if not generalized or generalized in (".", "<n>."):
        generalized = ("Repeated " + task.strip()[:60].lower() +
                       " should be classified/detected as a pattern "
                       "rather than fixed with episodic values.")
    return LintResult(policy="transformed", reason="episódico->regra generalizada",
                      numeric_kinds=profile["kinds"], original=fix,
                      transformed=generalized)


def transform_to_rule(task: str, error_pattern: str, fix: str) -> str:
    res = lint_lesson(task, error_pattern, fix)
    if res.policy in ("allowed", "suspicious") and res.transformed:
        return res.transformed
    if res.policy == "transformed":
        return res.transformed
    return res.original