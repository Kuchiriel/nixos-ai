import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "f38-wordlevel-early-stop.py"
BASE = ROOT / "scripts" / "f32-wordlevel.py"


class F38WordlevelEarlyStopTests(unittest.TestCase):
    def test_trainer_records_validation_curve_and_unique_best_checkpoint(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("def evaluate(", source)
        self.assertIn('parser.add_argument("--val-every"', source)
        self.assertIn('parser.add_argument("--val-tokens"', source)
        self.assertIn('parser.add_argument("--ckpt"', source)
        self.assertIn('"{step}"', source)
        self.assertIn('curve.append(record)', source)
        self.assertIn('if best is None or metrics["val_loss"] < best["val_loss"]', source)
        self.assertIn('"best": best', source)
        self.assertIn("else nullcontext()", source)
        self.assertIn("torch.autocast(device_type=args.device", source)

    def test_base_preserves_no_scheduled_sampling_and_generated_token_fix(self):
        source = BASE.read_text(encoding="utf-8")
        self.assertIn('ap.add_argument("--no-ss", action="store_true")', source)
        self.assertIn("(not a.no_ss)", source)
        self.assertIn("pref[:, 32:]", source)


if __name__ == "__main__":
    unittest.main()
