import pathlib
import runpy
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCALE = ROOT / "scripts" / "scale-loop-ab.py"

try:
    import torch
except Exception:  # pragma: no cover - CI without torch skips the model test
    torch = None


class LittleBit2CacheCausalEquivalenceTests(unittest.TestCase):
    @unittest.skipIf(torch is None, "torch unavailable")
    def test_loop_spec_full_causal_matches_per_loop_cache(self):
        ScaleLM = runpy.run_path(str(SCALE))["ScaleLM"]
        torch.manual_seed(3)
        model = ScaleLM(65, 64, "loop_spec").eval()
        ids = torch.randint(0, 65, (1, 12))
        with torch.no_grad():
            full = model(ids, causal=True)[0, -1, :].float()
            outputs = {}
            for mode in ("per_loop", "last"):
                state = {"caches": {}, "u": None}
                for position in range(ids.shape[1]):
                    output = model.forward_cached(
                        ids[:, position:position + 1], position, state, mode
                    )
                outputs[mode] = output[0, 0, :].float()
        per_loop_diff = float((full - outputs["per_loop"]).abs().max())
        last_diff = float((full - outputs["last"]).abs().max())
        self.assertLess(per_loop_diff, 1e-2)
        self.assertGreater(last_diff, per_loop_diff + 1e-4)

    def test_loop_spec_forward_propagates_causal_mask(self):
        source = SCALE.read_text(encoding="utf-8")
        self.assertIn("h = blk(h, causal=causal)", source)


if __name__ == "__main__":
    unittest.main()
