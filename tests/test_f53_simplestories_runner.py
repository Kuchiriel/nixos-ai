import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TOKENIZER = ROOT / "scripts" / "f53-simplestories-tokenize.py"
RUNNER = ROOT / "scripts" / "run-f53-simplestories-150m.sh"


class F53SimpleStoriesTests(unittest.TestCase):
    def test_tokenizer_streams_parquet_and_builds_diversity_sample(self):
        source = TOKENIZER.read_text(encoding="utf-8")
        self.assertIn("pq.ParquetFile(args.parquet)", source)
        self.assertIn("iter_batches(", source)
        self.assertIn("diversity_strata(row)", source)
        self.assertIn('parser.add_argument("--target-bytes", type=int, default=200_000_000)', source)
        self.assertIn("stable_key(", source)
        self.assertNotIn("read_table(", source)

    def test_tokenizer_uses_local_tokenizer_and_writes_npy_stats(self):
        source = TOKENIZER.read_text(encoding="utf-8")
        self.assertIn("GPT2TokenizerFast.from_pretrained(str(TOKDIR), local_files_only=True)", source)
        self.assertIn("np.save(output, mapped, allow_pickle=False)", source)
        self.assertIn('"remap": {str(token): index for token, index in remap.items()}', source)
        self.assertIn('"n": int(mapped.shape[0])', source)

    def test_runner_waits_for_f50_and_uses_global_gpu_lock(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("jarvis-f50-150m-60k", source)
        self.assertIn("flock -n 9", source)
        self.assertIn("nvidia-smi --query-compute-apps", source)
        self.assertIn('SEEDS=${SEEDS:-"42 43"}', source)
        self.assertIn("STEPS=${STEPS:-9600}", source)
        self.assertIn("DEPTH=${DEPTH:-1216}", source)
        self.assertIn("--target-bytes 200000000", source)
        self.assertIn("F53_SIMPLESTORIES_DONE", source)


if __name__ == "__main__":
    unittest.main()
