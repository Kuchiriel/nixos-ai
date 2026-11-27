import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-f50-150m-60k.sh"


class F50CurveRunnerTests(unittest.TestCase):
    def test_runner_pins_curve_and_serializes_gpu(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("jarvis-f49", source)
        self.assertIn("flock -n 9", source)
        self.assertIn("nvidia-smi --query-compute-apps", source)
        self.assertIn("STEPS=${STEPS:-60000}", source)
        self.assertIn("VAL_EVERY=${VAL_EVERY:-4000}", source)
        self.assertIn("SEED=${SEED:-42}", source)
        self.assertIn("DEPTH=${DEPTH:-1216}", source)
        self.assertIn("--val-every", source)


if __name__ == "__main__":
    unittest.main()
