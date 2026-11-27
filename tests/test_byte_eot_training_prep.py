import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TRAINER = ROOT / "scripts" / "f32-byte-eot.py"
LAUNCHER = ROOT / "scripts" / "run-byte-eot.sh"
BASH = "/bin/bash"
PYTHON = "/home/nixos/.venvs/finetune/bin/python"


class ByteEotPreparationTests(unittest.TestCase):
    def test_check_validates_measured_contract_without_training(self):
        result = subprocess.run(
            [PYTHON, str(TRAINER), "--check"], capture_output=True,
            text=True, timeout=30, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(24_918_286, payload["expected_ids"])
        self.assertEqual(257, payload["expected_vocab"])
        self.assertEqual(1312, payload["d"])
        self.assertTrue(payload["no_train"])
        self.assertEqual(24_918_286, payload["stats_measured"]["n"])
        self.assertEqual(257, payload["stats_measured"]["vocab"])
        self.assertEqual(4_883_968, payload["stats_measured"]["eot_count"])

    def test_launcher_check_never_creates_output_or_checkpoint(self):
        out = pathlib.Path("/home/nixos/work/hybrid/f104-byte-eot-d1312-s42.json")
        ckpt = pathlib.Path(
            "/home/nixos/work/hybrid/checkpoints/f104-byte-eot-d1312-s42.pt")
        self.assertFalse(out.exists())
        self.assertFalse(ckpt.exists())
        result = subprocess.run(
            [BASH, str(LAUNCHER), "--check"], capture_output=True,
            text=True, timeout=30, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("sem treino", result.stdout)
        self.assertFalse(out.exists())
        self.assertFalse(ckpt.exists())

    def test_unknown_launcher_mode_is_refused(self):
        result = subprocess.run(
            [BASH, str(LAUNCHER)], capture_output=True,
            text=True, timeout=30, check=False)
        self.assertEqual(2, result.returncode)
        self.assertIn("--check", result.stderr)


if __name__ == "__main__":
    unittest.main()
