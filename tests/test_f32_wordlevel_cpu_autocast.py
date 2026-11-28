import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TRAINER = ROOT / "scripts" / "f32-wordlevel.py"


class F32WordlevelCpuAutocastTests(unittest.TestCase):
    def test_cpu_branch_does_not_use_legacy_autocast_api(self):
        source = TRAINER.read_text(encoding="utf-8")
        executable = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        self.assertNotIn("torch.autocast(enabled=False)", executable)
        self.assertIn("from contextlib import nullcontext", source)
        self.assertIn("else nullcontext()", executable)
        self.assertIn("torch.autocast(device_type=a.device, dtype=torch.bfloat16)", executable)


if __name__ == "__main__":
    unittest.main()
