import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "f21-measure.py"
RUNNER = ROOT / "scripts" / "run-f21b-causal150.sh"


class F21bCausalTrainTests(unittest.TestCase):
    def test_measure_supports_causal_training_flag(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--causal-train", action="store_true"', source)
        self.assertIn("model(x, causal=True) if args.causal_train else model(x)", source)
        self.assertIn('"causal_train": args.causal_train', source)

    def test_runner_pins_one_150m_seed_and_causal_training(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn('SEEDS=${SEEDS:-"45"}', source)
        self.assertIn("DEPTH=${DEPTH:-1216}", source)
        self.assertIn("STEPS=${STEPS:-2400}", source)
        self.assertIn("--causal-train", source)
        self.assertIn("f21b-causal150-", source)


if __name__ == "__main__":
    unittest.main()
