import importlib.util
import pathlib
import random
import unittest
from importlib.machinery import SourceFileLoader


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "f17-measure.py"
spec = importlib.util.spec_from_loader(
    "f17_measure_protocol",
    SourceFileLoader("f17_measure_protocol", str(SCRIPT)),
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class F17MeasureProtocolTests(unittest.TestCase):
    def test_protocol_is_f12_16_positions(self):
        self.assertEqual(16, module.TARGET_TOKENS)
        self.assertEqual(64, module.CONTEXT_TOKENS)
        self.assertEqual(160, module.PROMPT_MARGIN)
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"teacher_forcing": True', source)
        self.assertIn("for position, target in enumerate(targets)", source)
        self.assertIn("model.forward_cached", source)

    def test_prompt_starts_match_f12_fixed_rng(self):
        expected_rng = random.Random(1234)
        expected = [expected_rng.randint(0, 1000 - 160) for _ in range(5)]
        self.assertEqual(expected, module.fixed_starts(1000, 5))

    def test_summary_uses_all_token_predictions(self):
        per_position = {
            0: {"conf": [1.0, 0.0], "corr": [1, 0]},
            1: {"conf": [0.8, 0.2], "corr": [1, 0]},
        }
        summary = module.summarize(per_position)
        self.assertEqual(0.5, summary["acc_all"])
        self.assertEqual(0.1, summary["ece_all"])
        self.assertEqual([0, 1], [row["pos"] for row in summary["per_position"]])
        self.assertEqual([2, 2], [row["n"] for row in summary["per_position"]])

    def test_f17_rejects_a_non_protocol_target_count(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("F17 protocol requires exactly 16 target tokens", source)


if __name__ == "__main__":
    unittest.main()
