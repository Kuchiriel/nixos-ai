"""L9 checker unit tests (sandbox-safe: deterministic, no LLM)."""
import json
import sys

sys.path.insert(0, "modules/ai/jarvis/src")

from jarvis.benchmarks.l9.l9_lib import check, expected, fixture


def _good_workspace(tmp_path):
    d = str(tmp_path)
    fixture(d)
    exp = expected(d)
    rep = [{"id": i, "disposition": v[0], "evidence": v[1]}
           for i, v in exp.items()]
    with open(f"{d}/report.json", "w") as f:
        json.dump(rep, f)
    counts = {"ok": 0, "repaired": 0, "quarantined": 0, "skipped": 0}
    for i, v in exp.items():
        counts[v[0]] += 1
    with open(f"{d}/summary.txt", "w") as f:
        f.write(" ".join(f"{k}={v}" for k, v in counts.items()) + "\n")
        f.write("observed-from-files: inventory.csv manual.txt\n")
        f.write("inferred: QX rule from manual\n")
    return d


def test_l9_check_accepts_correct(tmp_path):
    assert check(_good_workspace(tmp_path)) == ""


def test_l9_check_rejects_fabricated_evidence(tmp_path):
    d = _good_workspace(tmp_path)
    rep = json.load(open(f"{d}/report.json"))
    rep[0]["evidence"] = "doctored line"
    json.dump(rep, open(f"{d}/report.json", "w"))
    assert "fabricated" in check(d)


def test_l9_check_rejects_wrong_disposition(tmp_path):
    d = _good_workspace(tmp_path)
    rep = json.load(open(f"{d}/report.json"))
    for e in rep:
        if e["disposition"] == "quarantined":
            e["disposition"] = "repaired"
    json.dump(rep, open(f"{d}/report.json", "w"))
    assert "wrong disposition" in check(d)


def test_l9_check_rejects_missing(tmp_path):
    import os
    d = _good_workspace(tmp_path)
    os.remove(f"{d}/summary.txt")
    assert check(d) != ""


def test_expected_rule_shape():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        fixture(d)
        exp = expected(d)
        assert exp["03"][0] == "quarantined"  # QX broken
        assert exp["02"][0] == "repaired"  # plain broken
        assert exp["01"][0] == "ok"
        assert exp["06"][0] == "skipped"  # malformed