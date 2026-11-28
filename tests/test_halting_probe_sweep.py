import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "halting_probe.py"
SPEC = importlib.util.spec_from_loader(
    "halting_probe_sweep", importlib.machinery.SourceFileLoader(
        "halting_probe_sweep", str(SCRIPT)
    )
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class HaltingProbeSweepTests(unittest.TestCase):
    """The exit-step rule must not pick step 0 for every epsilon.

    kl[:,0] is +inf because the first loop pass has no previous pass to
    compare against. With kl[:,0] = 0 every (kl < eps) was True from index 0,
    so argmax always returned 0 and the sweep was identical for all eps.
    """

    @staticmethod
    def _torch():
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - environment guard
            raise unittest.SkipTest(f"torch indisponivel: {exc}")
        return torch

    def test_kl_column_zero_is_infinite_so_no_early_exit_at_step_zero(self):
        torch = self._torch()
        kl = torch.tensor([[float("inf"), 0.5, 0.2, 0.1]])
        exit_t, any_below = probe.choose_exit_step(kl, eps=0.3)
        # t=1 (0.5) is above the threshold, t=2 (0.2) is the first below it.
        self.assertEqual(2, int(exit_t[0]))
        self.assertTrue(bool(any_below[0]))

    def test_exit_falls_back_to_last_loop_when_no_step_is_below_eps(self):
        torch = self._torch()
        kl = torch.tensor([[float("inf"), 0.9, 0.8, 0.7]])
        exit_t, any_below = probe.choose_exit_step(kl, eps=0.1)
        self.assertEqual(3, int(exit_t[0]))
        self.assertFalse(bool(any_below[0]))

    def test_largest_eps_exits_at_the_earliest_step(self):
        torch = self._torch()
        kl = torch.tensor([[float("inf"), 0.5, 0.2, 0.1]])
        early, _ = probe.choose_exit_step(kl, eps=0.6)
        late, _ = probe.choose_exit_step(kl, eps=0.15)
        self.assertEqual(1, int(early[0]))
        self.assertEqual(3, int(late[0]))

    def test_probe_source_uses_infinite_first_kl_column(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('kl = torch.full((p.shape[0], p.shape[1]), float("inf"))', source)
        self.assertNotIn("kl = torch.zeros(p.shape[0], p.shape[1])", source)
        self.assertIn("choose_exit_step(kl, eps)", source)

    def test_sweep_is_streaming_and_does_not_keep_every_trajectory(self):
        source = SCRIPT.read_text(encoding="utf-8")
        # Guardar as trajetorias de todos os batches consumia ~32 GB de RAM e
        # o host matou o processo pelo OOM killer.
        self.assertNotIn("traces.append(", source)
        self.assertIn("sweep_acc = {eps:", source)
        self.assertIn("streaming_sweep", source)
        self.assertIn("del lgseq, lp, p, kl, tr", source)


if __name__ == "__main__":
    unittest.main()
