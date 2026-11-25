import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class F17cF21cRunnerTests(unittest.TestCase):
    def test_f17c_runner_pins_six_causal_150m_seeds(self):
        source = (ROOT / "scripts" / "run-f17c-causal150.sh").read_text(encoding="utf-8")
        self.assertIn('SEEDS=${SEEDS:-"45 46 47 48 49 50"}', source)
        self.assertIn("DEPTH=${DEPTH:-1216}", source)
        self.assertIn("STEPS=${STEPS:-2400}", source)
        self.assertIn("--causal-train", source)
        self.assertIn("f17c-causal150-", source)

    def test_f21c_runner_pins_two_causal_300m_seeds_and_variants(self):
        source = (ROOT / "scripts" / "run-f21c-causal300.sh").read_text(encoding="utf-8")
        self.assertIn('SEEDS=${SEEDS:-"42 43"}', source)
        self.assertIn('VARIANTS=${VARIANTS:-"plain ngpt_only loop_spec"}', source)
        self.assertIn("DEPTH=${DEPTH:-1768}", source)
        self.assertIn("STEPS=${STEPS:-4800}", source)
        self.assertIn("--causal-train", source)
        self.assertIn("f21c-300m-valid-", source)


if __name__ == "__main__":
    unittest.main()
