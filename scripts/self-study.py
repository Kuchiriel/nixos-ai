#!/usr/bin/env python3
"""self-study.py — o harness estuda os próprios fracassos (LOOP-v3).

O ponto crítico que o dono pediu: com os modelos DISPONÍVEIS (começando
pelo fraco), analisar as falhas medidas e propor melhorias de harness.
Não é substituto do ciclo humano/agente que APLICA mudança — é o gerador
de candidatos com respaldo: cada proposta cita (aresta, lado) conforme
arXiv 2607.28802 e o mecanismo que teria pego a falha (Bhatt: hooks).

Entrada: JSONs de bateria (harness-suite). Saída:
docs/benchmarks/SELF-STUDY-<ts>.md com uma proposta por falha, atribuída
ao modelo que a analisou. Filtro/aplicação/medição fica com o loop.

Uso:
  nix develop --command python3 scripts/self-study.py \
      --evidence /tmp/.../reopen-hook-classic.json [--model bonsai]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import urllib.request

BASE = os.environ.get("JARVIS_LLM_BASE_URL",
                      "http://127.0.0.1:8080/v1").rstrip("/")
OUTDIR = "docs/benchmarks"

TAXONOMY = (
    "Failure localization taxonomy (arXiv 2607.28802): every failure "
    "belongs to an EDGE between two components (model<->instruction, "
    "model<->tool, harness<->context, model<->world, ...) and a FAULT "
    "SIDE (model / harness / environment / grader). Same visible "
    "failure can need opposite repairs.\n"
    "House doctrine: mechanisms beat prompts (hooks 100% vs 70-90%); "
    "world-state verification beats self-report; feedback as structure "
    "beats prose."
)

PROMPT_TMPL = """You are analyzing YOUR OWN failure as a coding agent, to improve the HARNESS that runs you (not to excuse yourself).

TASK GIVEN TO THE AGENT:
{prompt}

WHAT ACTUALLY HAPPENED (measured world-state):
- world checks satisfied: {world_ok}
- false_done (agent claimed completion falsely): {false_done}
- turns used: {turns}
- world checks that FAILED: {missed}

Propose ONE concrete HARNESS improvement that would have prevented or caught THIS failure. Requirements:
- A MECHANISM (structural check, gate, hook, routing rule), not a polite instruction to try harder.
- Cite the failure's EDGE and FAULT SIDE per the taxonomy.
- Be specific enough that an engineer could implement it in a day.
{taxonomy}

MECHANISMS THE HARNESS ALREADY HAS (do NOT re-propose these):
- promise-catcher (future-tense claim without tool call -> nudge)
- claim-checker (declared file write never recorded -> correction)
- check_completion: structural world verdict — written files exist,
  .py compiles (AST), parquet magic, instruction-read-in-file-was-executed
- reopen-on-UNVERIFIED (1x, artifact-class missing fed back to agent)
- LoopDetector (identical repetition x3 -> honest STUCK)
- rtk-lite head+tail truncation with omission marker

If an existing mechanism SHOULD have caught this failure, say which one
and why it did not (residual gap). Then propose the mechanism that
covers the RESIDUAL gap — or, if none exists, say MODEL-SIDE LIMIT and
what model capability is missing.

Answer in EXACTLY this format:
EDGE: <edge>
SIDE: <model|harness|environment|grader>
RESIDUAL-GAP: <what existing mechanisms missed, or MODEL-SIDE LIMIT>
PROPOSAL: <one sentence, concrete mechanism (or "none — model-side limit")>
WHY: <one sentence>
"""


def ask_llm(model: str, user: str) -> str:
    payload = json.dumps({
        "model": model, "temperature": 0.5, "max_tokens": 300,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(f"{BASE}/chat/completions", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return (json.load(r)["choices"][0]["message"]["content"] or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", required=True, help="JSON da bateria")
    ap.add_argument("--model", default="bonsai")
    ap.add_argument("--task-file", help="harness-challenges.json p/ pegar prompts")
    args = ap.parse_args()

    ev = json.load(open(args.evidence))
    prompts: dict[str, str] = {}
    if args.task_file:
        for t in json.load(open(args.task_file))["tasks"]:
            prompts[t["id"]] = t["prompt"]

    failures = [r for r in ev.get("results", [])
                if not r.get("world_ok") or r.get("false_done")]
    if not failures:
        print("sem falhas na evidência — nada a estudar")
        return 0

    lines = [f"# SELF-STUDY — {datetime.datetime.now():%Y-%m-%d %H:%M}",
             f"> Analista: **{args.model}** (o próprio modelo que falhou, onde aplicável).",
             f"> Evidência: `{args.evidence}` — {len(failures)} falha(s). Propostas são CANDIDATOS;",
             "> aplicação exige A/B no harness (só entra o que se prova).",
             ""]
    for r in failures:
        tid = r.get("task_id", "?")
        print(f"estudando {tid}...")
        user = PROMPT_TMPL.format(
            prompt=prompts.get(tid, "(ver evidência)"),
            world_ok=bool(r.get("world_ok")),
            false_done=bool(r.get("false_done")),
            turns=r.get("turns", "?"),
            missed="; ".join(r.get("missed") or []) or "(none listed)",
            taxonomy=TAXONOMY,
        )
        try:
            ans = ask_llm(args.model, user)
        except Exception as e:
            ans = f"(LLM indisponível: {e})"
        lines += [f"## {tid} ({r.get('tier')})", "```", ans, "```", ""]
        print(ans.splitlines()[0] if ans else "(vazio)")

    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    out = os.path.join(OUTDIR, f"SELF-STUDY-{ts}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"salvo: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
