import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
EVALUATOR = ROOT / "scripts" / "f51-eval-checkpoint.py"
RUNNER = ROOT / "scripts" / "run-f51-150m-best-eval.sh"


class F51CheckpointEvalTests(unittest.TestCase):
    def test_evaluator_loads_checkpoint_and_never_trains(self):
        source = EVALUATOR.read_text(encoding="utf-8")
        self.assertIn("torch.load(args.checkpoint", source)
        self.assertIn("model.load_state_dict(checkpoint[\"state\"], strict=True)", source)
        self.assertIn("model.eval()", source)
        self.assertNotIn("torch.optim", source)
        self.assertNotIn("model.train()", source)
        self.assertIn('"trained": False', source)
        self.assertIn('"checkpoint_modified": False', source)

    def test_evaluator_uses_same_heldout_window_and_corpus_split(self):
        source = EVALUATOR.read_text(encoding="utf-8")
        self.assertIn("train_count = int(token_count * (1.0 - args.val_ratio))", source)
        self.assertIn("args.val_tokens, val_count", source)
        self.assertIn("np.load(args.corpus, mmap_mode=\"r\")", source)

    def test_evaluator_uses_contiguous_non_overlapping_windows_like_f32(self):
        source = EVALUATOR.read_text(encoding="utf-8")
        self.assertIn("starts = np.arange(0, validation_limit, args.seq, dtype=np.int64)", source)
        self.assertIn("offsets = starts[group:group + args.batch]", source)
        self.assertNotIn("np.arange(\n                offset,", source)

    def test_runner_waits_for_f50_and_uses_global_gpu_lock(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("F50_150M_60K_DONE", source)
        self.assertIn("best_checkpoint", source)
        self.assertIn("flock -n 9", source)
        self.assertIn("nvidia-smi --query-compute-apps", source)
        self.assertIn("--val-tokens 200000", source)
        self.assertIn("F51_150M_BEST_EVAL_DONE", source)


if __name__ == "__main__":
    unittest.main()
