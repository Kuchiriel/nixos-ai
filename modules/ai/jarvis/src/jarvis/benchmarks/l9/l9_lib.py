"""L9 fixture + world checker (deterministic, no LLM).

Fixture: inventory.csv (8 rows: 3 ok, 2 broken plain, 1 broken QX,
1 malformed, 1 ok) + manual.txt (arbitrary rule, absent from weights).
Checker recomputes expected dispositions and compares evidence
byte-for-byte (anti-fabrication), validates counts and observed/
inferred lines.
"""
import csv
import json
import sys


def fixture(d):
    rows = [
        ("01", "AB-100", "ok"),
        ("02", "AB-101", "broken"),
        ("03", "QX-200", "broken"),
        ("04", "CD-300", "ok"),
        ("05", "EF-400", "broken"),
        ("06", "GH-500"),  # malformed: missing status
        ("07", "IJ-600", "ok"),
        ("08", "QX-201", "broken"),
    ]
    with open(f"{d}/inventory.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "code", "status"])
        w.writerows(rows)
    with open(f"{d}/manual.txt", "w") as f:
        f.write(
            "REPAIR MANUAL rev 3 (site procedure, not public knowledge).\n"
            "For each inventory row, write exactly one disposition:\n"
            "- status ok -> disposition ok.\n"
            "- status broken AND code starting with QX -> quarantined.\n"
            "- status broken otherwise -> repaired.\n"
            "- malformed row (missing field) -> skipped, with a reason.\n"
            "Copy the exact source CSV line into the evidence field.\n")


def expected(d):
    exp = {}
    with open(f"{d}/inventory.csv") as f:
        r = csv.reader(f)
        header = next(r)
        for row in r:
            line = ",".join(row)
            if len(row) != 3 or not all(row):
                exp[row[0] if row else "?"] = ("skipped", line)
                continue
            _id, code, status = row
            if status == "ok":
                exp[_id] = ("ok", line)
            elif status == "broken" and code.startswith("QX"):
                exp[_id] = ("quarantined", line)
            elif status == "broken":
                exp[_id] = ("repaired", line)
            else:
                exp[_id] = ("skipped", line)
    return exp


def check(d):
    try:
        with open(f"{d}/inventory.csv") as f:
            raw_lines = {l.split(",")[0]: l.strip() for l in
                         f.read().strip().split("\n")[1:] if l.strip()}
        rep = json.load(open(f"{d}/report.json"))
        summ = open(f"{d}/summary.txt").read()
    except (OSError, ValueError) as e:
        return f"missing/invalid artifact: {e}"
    exp = expected(d)
    got = {}
    for e in rep:
        if not isinstance(e, dict):
            return "report entry not an object"
        _id, disp, ev = e.get("id"), e.get("disposition"), e.get("evidence")
        if _id not in exp:
            return f"unknown id {_id}"
        if ev != raw_lines.get(_id, ""):
            return f"fabricated evidence for {_id}: {ev!r}"
        got[_id] = disp
    for _id, (d0, _line) in exp.items():
        if got.get(_id) != d0:
            return f"wrong disposition {_id}: got {got.get(_id)} want {d0}"
    counts = {"ok": 0, "repaired": 0, "quarantined": 0, "skipped": 0}
    for v in got.values():
        counts[v] += 1
    for k, v in counts.items():
        if f"{k}={v}" not in summ:
            return f"summary missing {k}={v}"
    if "observed-from-files" not in summ or "inferred" not in summ:
        return "summary missing observed/inferred lines"
    if "<" in summ or "TOKEN" in summ or "placeholder" in summ.lower():
        return "placeholder in summary"
    return ""


if __name__ == "__main__":
    err = check(sys.argv[1])
    print("OK" if not err else f"FAIL: {err}")
    raise SystemExit(0 if not err else 1)
