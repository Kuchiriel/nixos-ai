import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-f138-fineweb-150m.sh"


class F138FineWebRunnerTests(unittest.TestCase):
    def test_runner_pins_the_preregistered_f118_protocol(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("STEPS=${STEPS:-9600}", source)
        self.assertIn("DEPTH=${DEPTH:-1216}", source)
        self.assertIn("SEED=${SEED:-42}", source)
        self.assertIn("BATCH=${BATCH:-8}", source)
        self.assertIn("SEQ=${SEQ:-256}", source)
        self.assertIn("LR=${LR:-1e-4}", source)
        self.assertIn("WARMUP=${WARMUP:-500}", source)
        self.assertIn("GATE_MAX_VAL_LOSS=${GATE_MAX_VAL_LOSS:-1.9762}", source)
        self.assertIn("--no-ss", source)

    def test_runner_reuses_the_materialized_fineweb_corpus(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("fineweb-edu-1b-ids-top10000.npy", source)
        self.assertIn("fineweb-edu-1b-ids-top10000-stats.json", source)
        self.assertNotIn("huggingface", source.lower())
        self.assertNotIn("snapshot_download", source)

    def test_runner_serializes_gpu_and_records_the_gate_verdict(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("flock -n 9", source)
        self.assertIn("--query-compute-apps", source)
        self.assertIn("until gpu_free; do", source)
        self.assertIn('"gate": "F118"', source)
        self.assertIn('"verdict": verdict', source)
        self.assertIn('"REPROVADO"', source)
        self.assertIn("F138_FINEWEB_DONE", source)
        self.assertIn("F138 sem JSON de resultado", source)
        self.assertIn('if [ "$DRY_RUN" != "1" ]; then', source)

    def test_runner_exposes_stubs_and_dry_run(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn('SYSTEMCTL=${SYSTEMCTL:-systemctl --user}', source)
        self.assertIn('NVIDIA_SMI=${NVIDIA_SMI:-nvidia-smi}', source)
        self.assertIn('DRY_RUN=${DRY_RUN:-0}', source)
        self.assertIn('TRAIN_CMD=("$PYTHON" -u', source)


if __name__ == "__main__":
    unittest.main()
