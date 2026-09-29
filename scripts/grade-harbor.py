#!/usr/bin/env python3
"""grade-harbor.py — taxonomia de estratégia sobre trajetórias salvas.

Tudo marcava 0/1 sem diferenciar. Este grader lê steps/sessions de todos
os jobs e classifica a ESTRATÉGIA de cada trial (independente de reward):
  cp-shell | text-fight | header-leak | note-copy | src-overwrite |
  binary-giveup | prosa-only | tool-error-loop
Uso: python3 scripts/grade-harbor.py [/tmp/harbor-work/jobs]
"""
import glob
import json
import os
import sys

JOBS = sys.argv[1] if len(sys.argv) > 1 else "/tmp/harbor-work/jobs"


def classify(traj, sess):
    steps = traj.get("steps", []) or sess.get("steps", [])
    runs = sess.get("commands_run", []) if sess else []
    tools = [s.get("tool", "") for s in steps]
    blobs = json.dumps(steps, ensure_ascii=False).lower()
    has_shell = any("execute_shell" in t for t in tools)
    cp_written = "copy.sh" in blobs or ("cp /app" in blobs)
    # executed = comando shell de verdade (commands_run guarda "tool path"
    # p/ tools — escrever copy.sh NÃO conta como executar).
    _TOOLS = ("write_file", "str_replace", "read_file", "list_directory",
              "execute_shell", "jarvis_execute")
    cp_executed = any(
        ("copy.sh" in c or "cp /app" in c or c.strip().startswith("cp "))
        and not c.startswith(_TOOLS)
        for c in runs)
    src_hit = any("src.txt" in c and ("write" in c or "str_replace" in c)
                  for c in runs)
    if not steps and (traj.get("turns", 0) or 0) <= 2:
        return "prosa-only"
    if cp_executed:
        return "cp-executed"
    if cp_written:
        # B-cell 29/09: MoE escreveu copy.sh correto e NUNCA executou —
        # estratégia descoberta, execução abandonada. Dado, não falha.
        return "cp-written-only"
    if src_hit:
        return "src-overwrite"
    if "# /app/" in blobs and "o.txt" in blobs and "header" in blobs:
        return "header-leak"
    if "corrupt this file" in blobs or "not valid utf-8" in blobs.lower():
        return "note-copy"
    if "trailer" in blobs and "bytes" not in blobs:
        return "binary-giveup"
    if tools and all(t in ("read_file", "write_file", "list_directory",
                           "str_replace") for t in tools):
        return "text-fight"
    if not tools:
        return "prosa-only"
    return "mixed"


def main():
    rows = []
    import itertools as _it
    pats = [os.path.join(JOBS, "*/bytecopy-*/agent/trajectory.json"),
            os.path.join(JOBS, "*/extract-line__*/agent/trajectory.json")]
    trajs = sorted(set(_it.chain.from_iterable(glob.glob(p) for p in pats)))
    for tj in trajs:
        try:
            traj = json.load(open(tj))
        except Exception:
            continue
        sj = tj.replace("trajectory.json", "session.json")
        sess = None
        try:
            sess = json.load(open(sj))
        except Exception:
            pass
        model = str(traj.get("model", "?"))[:45]
        job = tj.split("/jobs/")[1].split("/")[0]
        task = "bin" if "bytecopy-bin" in tj else ("line" if "extract-line" in tj else "byte")
        diag = ""
        dj = tj.replace("agent/trajectory.json", "verifier/diag.json")
        try:
            pct = json.load(open(dj)).get("bytes_match_pct")
            diag = f"{pct}%"
        except Exception:
            pass
        rows.append((job, task, model.split("/")[-1][:28],
                     classify(traj, sess), traj.get("turns", "?"), diag,
                     round(float(traj.get("duration_s", 0) or 0), 1),
                     (traj.get("grounding") or {}).get("n_exec", "?")))
    print(f"{'job':<16}{'task':<5}{'model':<30}{'strategy':<16}{'turns':<6}{'bytes':<7}wall_s execs")
    for r in rows:
        print(f"{r[0]:<16}{r[1]:<5}{r[2]:<30}{r[3]:<16}{r[4]:<6}{r[5]:<7}{r[6]:<7}{r[7]}")


if __name__ == "__main__":
    main()
