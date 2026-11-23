import importlib.util, json, pathlib, tempfile, unittest
from importlib.machinery import SourceFileLoader

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_loader("agg", SourceFileLoader("agg", str(ROOT / "scripts/aggregate-littlebit2-outputs.py")))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class AggregateTests(unittest.TestCase):
    def _run(self, tmp, name, itq, ppl):
        root = tmp / name
        o = root / "official-output"
        o.mkdir(parents=True)
        v = o / ("littlebit2" if itq else "baseline")
        v.mkdir()
        (v / "config.json").write_text("{}", encoding="utf-8")
        (v / "official-eval.log").write_text("[wikitext2] PPL = %s\n" % ppl, encoding="utf-8")
        data = {
            "schema": 1,
            "production_writes": False,
            "official_commit": "42d658b0c79f76450b34b6a3547462c7cdc3e1a0",
            "hardware": {"gpus": []},
            "dataset": {"examples": 1229},
            "variants": {("littlebit2" if itq else "baseline"): {
                "use_itq": itq, "official_wikitext2_ppl": ppl}},
        }
        (o / "results.json").write_text(json.dumps(data), encoding="utf-8")
        (o / "protocol-measurement.json").write_text(json.dumps({"examples": 1229}), encoding="utf-8")
        return root

    def test_merges_two_sessions_without_touching_sources(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="lb2-agg-"))
        a = self._run(tmp, "run-baseline", False, 16.3)
        b = self._run(tmp, "run-itq", True, 11.5)
        before = {p: p.read_bytes() for p in a.rglob("*") if p.is_file()}
        before.update({p: p.read_bytes() for p in b.rglob("*") if p.is_file()})
        out = tmp / "merged"
        man = m.aggregate([a, b], out)
        self.assertTrue(man["complete"])
        self.assertEqual(["baseline", "littlebit2"], man["variants_merged"])
        results = json.loads((out / "results.json").read_text())
        self.assertEqual(16.3, results["variants"]["baseline"]["official_wikitext2_ppl"])
        self.assertEqual(11.5, results["variants"]["littlebit2"]["official_wikitext2_ppl"])
        self.assertTrue((out / "baseline/config.json").is_file())
        self.assertTrue((out / "littlebit2/official-eval.log").is_file())
        for p, raw in before.items():
            self.assertEqual(raw, p.read_bytes())

    def test_single_source_is_not_complete(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="lb2-agg-one-"))
        a = self._run(tmp, "only", False, 16.3)
        man = m.aggregate([a], tmp / "out")
        self.assertFalse(man["complete"])


if __name__ == "__main__":
    unittest.main()
