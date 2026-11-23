import importlib.util
import json
import pathlib
import tempfile
import unittest
from importlib.machinery import SourceFileLoader

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_loader("agg2", SourceFileLoader("agg2", str(ROOT / "scripts/aggregate-littlebit2-outputs.py")))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class LogAggregationTests(unittest.TestCase):
    def test_decodes_real_kaggle_jsonl_shape(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="agg-log-"))
        log = tmp / "run.log"
        events = [{"stream_name": "stdout", "time": 1.0, "data": "linha um\n"},
                  {"stream_name": "stdout", "time": 2.0, "data": "--use_itq True\n"}]
        text = json.dumps(events[0]) + "\n" + "," + json.dumps(events[1]) + "\n"
        log.write_text(text, encoding="utf-8")
        decoded = m.decode_kaggle_log(log)
        self.assertIn("linha um", decoded)
        self.assertIn("--use_itq True", decoded)

    def test_combined_log_is_written(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="agg-comb-"))
        src = tmp / "run"
        (src / "official-output").mkdir(parents=True)
        data = {"schema": 1, "production_writes": False, "variants": {}}
        (src / "official-output/results.json").write_text(json.dumps(data), encoding="utf-8")
        log = tmp / "kernel.log"
        log.write_text(json.dumps([{"data": "OFFICIAL_LITTLEBIT2_COMPLETE\n"}]), encoding="utf-8")
        man = m.aggregate([src], tmp / "out", [log])
        combined = (tmp / "out/combined-kernel.log").read_text(encoding="utf-8")
        self.assertIn("OFFICIAL_LITTLEBIT2_COMPLETE", combined)
        self.assertEqual(1, man["combined_log"]["files"].__len__())


if __name__ == "__main__":
    unittest.main()
