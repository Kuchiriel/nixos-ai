import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "f39-wordlevel-lr-diagnose.py"
RUNNER = ROOT / "scripts" / "run-f39-150m-lr.sh"


class F39WordlevelLrDiagnoseTests(unittest.TestCase):
    def test_trainer_has_explicit_lr_warmup_and_early_validation(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--lr", type=float, default=1e-4)', source)
        self.assertIn('parser.add_argument("--warmup", type=int, default=500)', source)
        self.assertIn('parser.add_argument("--first-val-step", type=int, default=400)', source)
        self.assertIn("warmup_scale = 1.0 if args.warmup <= 0 else min(1.0, step / args.warmup)", source)
        self.assertIn('group["lr"] = current_lr', source)
        self.assertIn("step == args.first_val_step", source)
        self.assertIn('"lr": args.lr', source)
        self.assertIn('"warmup": args.warmup', source)

    def test_runner_pins_seed43_lr_and_warmup(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("SEED=${SEED:-43}", source)
        self.assertIn("STEPS=${STEPS:-9600}", source)
        self.assertIn("LR=${LR:-1e-4}", source)
        self.assertIn("WARMUP=${WARMUP:-500}", source)
        self.assertIn("FIRST_VAL=${FIRST_VAL:-400}", source)
        self.assertIn("--first-val-step", source)


if __name__ == "__main__":
    unittest.main()
