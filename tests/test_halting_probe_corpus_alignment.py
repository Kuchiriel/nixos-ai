import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "halting_probe.py"
SPEC = importlib.util.spec_from_loader(
    "halting_probe_corpus_alignment", importlib.machinery.SourceFileLoader(
        "halting_probe_corpus_alignment", str(SCRIPT)
    )
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class HaltingProbeCorpusAlignmentTests(unittest.TestCase):
    def test_corpus_is_derived_from_the_checkpoint_training_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            corpus = root / "corpus.npy"
            corpus.write_bytes(b"ids")
            ckpt = root / "f99-model-s42.pt"
            ckpt.write_bytes(b"ckpt")
            (root / "f99-model-s42.json").write_text(
                json.dumps({"corpus": str(corpus), "val_loss": 1.5}),
                encoding="utf-8",
            )
            self.assertEqual(str(corpus), probe.corpus_for_checkpoint(str(ckpt)))
            self.assertEqual(1.5, probe.published_val_loss(str(ckpt)))

    def test_training_json_is_found_in_the_work_directory_above_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            work = root / "work"
            ckpts = work / "checkpoints"
            ckpts.mkdir(parents=True)
            corpus = root / "corpus.npy"
            corpus.write_bytes(b"ids")
            ckpt = ckpts / "f99-model-s42.pt"
            ckpt.write_bytes(b"ckpt")
            (work / "f99-model-s42.json").write_text(
                json.dumps({"corpus": str(corpus), "val_loss": 1.25}),
                encoding="utf-8",
            )
            self.assertEqual(str(corpus), probe.corpus_for_checkpoint(str(ckpt)))
            self.assertEqual(1.25, probe.published_val_loss(str(ckpt)))

    def test_explicit_npy_overrides_the_derived_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            corpus = root / "corpus.npy"
            corpus.write_bytes(b"ids")
            other = root / "other.npy"
            other.write_bytes(b"ids")
            ckpt = root / "f99-model-s42.pt"
            ckpt.write_bytes(b"ckpt")
            (root / "f99-model-s42.json").write_text(
                json.dumps({"corpus": str(corpus)}), encoding="utf-8"
            )
            self.assertEqual(str(other), probe.corpus_for_checkpoint(str(ckpt), str(other)))

    def test_missing_training_json_yields_no_corpus_instead_of_a_wrong_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = pathlib.Path(tmp) / "orphan-s42.pt"
            ckpt.write_bytes(b"ckpt")
            self.assertEqual("", probe.corpus_for_checkpoint(str(ckpt), ""))

    def test_remap_fingerprint_changes_with_a_different_remap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            corpus = root / "c.npy"
            corpus.write_bytes(b"ids")
            stats = root / "c-stats.json"
            stats.write_text(json.dumps({"remap": {"10": 0, "20": 1}}), encoding="utf-8")
            first = probe.remap_fingerprint(str(corpus))
            stats.write_text(json.dumps({"remap": {"10": 0, "30": 1}}), encoding="utf-8")
            second = probe.remap_fingerprint(str(corpus))
            self.assertNotEqual(first, second)
            self.assertTrue(first)

    def test_probe_source_keeps_the_correct_target_and_guards_the_gate(self):
        source = SCRIPT.read_text(encoding="utf-8")
        # target correto: y[:,-1]
        self.assertIn("y[:, -1:]", source)
        self.assertNotIn("y[:, 0:]", source)
        # o gate so roda depois do --check
        self.assertIn('"ok": ok', source)
        self.assertIn("probe --check REPROVADO", source)
        self.assertIn("no_train", source)


if __name__ == "__main__":
    unittest.main()
