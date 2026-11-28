import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-f133-halting-probe.sh"


class F133RunnerTests(unittest.TestCase):
    def test_runner_pins_the_three_preregistered_sizes(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn('SIZES=${SIZES:-"320 704 1216"}', source)
        self.assertIn("ablation-d320-beta005-s42.pt", source)
        self.assertIn("f42-50m-full-s42.pt", source)
        self.assertIn("f75-simplefull-s42.pt", source)

    def test_runner_uses_the_final_checkpoint_and_calibrated_check(self):
        source = RUNNER.read_text(encoding="utf-8")
        # the published val_loss comes from the final model, not '-best'
        self.assertNotIn("ablation-d320-beta005-s42-best.pt", source)
        self.assertIn("--check-tokens 32768", source)

    def test_runner_checks_before_gpu_and_aborts_on_failure(self):
        source = RUNNER.read_text(encoding="utf-8")
        check_at = source.index("halting_probe.py\" check")
        run_at = source.index("halting_probe.py\" run")
        self.assertLess(check_at, run_at)
        self.assertIn("exit 92", source)
        self.assertIn("F133_CHECK_OK_D", source)

    def test_runner_serializes_gpu_with_flock_and_probe(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("flock -n 9", source)
        self.assertIn("--query-compute-apps", source)
        self.assertIn("until gpu_free; do", source)
        self.assertIn('TOKENS=${TOKENS:-200000}', source)

    def test_runner_aggregates_the_f123_verdict(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn('"gate": "F123"', source)
        self.assertIn("same_signal_all_sizes", source)
        self.assertIn("avg_depth", source)
        self.assertIn("<= 3.2", source)
        self.assertIn("f133-halting-probe-summary.json", source)


if __name__ == "__main__":
    unittest.main()
