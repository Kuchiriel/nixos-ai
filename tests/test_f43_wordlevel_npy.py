import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "f43-wordlevel-npy.py"
RUNNER = ROOT / "scripts" / "run-f43-150m-big.sh"


class F43WordlevelNpyTests(unittest.TestCase):
    def test_trainer_streams_numpy_memmap_in_batches(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('np.load(args.corpus, mmap_mode="r")', source)
        self.assertNotIn(".tolist()", source)
        self.assertIn("def batch_numpy(", source)
        self.assertIn("np.stack(", source)
        self.assertIn('parser.add_argument("--d", type=int, default=1_216)', source)
        self.assertIn('parser.add_argument("--lr", type=float, default=1e-4)', source)
        self.assertIn('parser.add_argument("--warmup", type=int, default=500)', source)
        self.assertIn('"remap": remap', source)

    def test_runner_waits_for_f42_and_uses_global_gpu_lock(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("f42-full-stats.json", source)
        self.assertIn("pgrep -f '[f]42_stream.py'", source)
        self.assertIn("flock -n 9", source)
        self.assertIn("nvidia-smi --query-compute-apps", source)
        self.assertIn('SEEDS=${SEEDS:-"42 43"}', source)
        self.assertIn("STEPS=${STEPS:-9600}", source)
        self.assertIn("DEPTH=${DEPTH:-1216}", source)


if __name__ == "__main__":
    unittest.main()
