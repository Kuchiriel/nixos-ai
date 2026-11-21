"""Tests for the read-only LittleBit-2 preflight checker."""
from __future__ import annotations

import importlib.util
import stat
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/littlebit2-preflight.py"
SPEC = importlib.util.spec_from_loader(
    "littlebit2_preflight", SourceFileLoader("littlebit2_preflight", str(SCRIPT))
)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def write_sources(tmp_path: Path) -> tuple[Path, Path]:
    official = tmp_path / "LittleBit"
    (official / "utils").mkdir(parents=True)
    (official / "main.py").write_text(
        """
import deepspeed
from transformers import TrainingArguments
from utils.kd_utils import KDTrainer
parser.add_argument("--num_train_epochs", type=float, default=3)
parser.add_argument("--use_itq", type=str2bool, default=False)
model.save_pretrained(save_dir)
open(os.path.join(save_dir, "littlebit_config.json"), "w")
logger.info("Loading teacher model...")
teacher_model, _, _, _ = deepspeed.initialize(model=teacher_model)
trainer = KDTrainer(model=model, teacher_model=teacher_model)
""",
        encoding="utf-8",
    )
    (official / "utils/kd_utils.py").write_text(
        """
class KDTrainer:
    def compute_loss(self, model, inputs):
        teacher_outputs = self.teacher_model(**inputs)
        teacher_reps = teacher_outputs.hidden_states[1:]
        kd_loss = F.kl_div(student_logits, teacher_logits)
        l2l_loss = self.mse_loss(student_reps, teacher_reps)
""",
        encoding="utf-8",
    )
    (official / "README.md").write_text(
        "Use --use_itq True and --num_train_epochs 5.0 with DeepSpeed.",
        encoding="utf-8",
    )
    minimal = official / "minimal_qat.py"
    minimal.write_text(
        """
import torch
MODEL = 'Qwen/Qwen3-0.6B'
STEPS = int(os.environ.get('LB_STEPS', '60'))
ap.add_argument('--teacher', action='store_true')
ap.add_argument('--use-itq', required=True)
for step in range(STEPS):
    loss = loss + KD_SCALE * torch.nn.functional.mse_loss(out.logits.float(), tlogits)
""",
        encoding="utf-8",
    )
    return official, minimal


def test_source_audit_names_material_divergences(tmp_path: Path) -> None:
    official, minimal = write_sources(tmp_path)
    audit = preflight.audit_sources(official, minimal)
    assert audit["ready"] is True
    assert audit["official"]["default_epochs"] == 3.0
    assert audit["official"]["readme_epochs"] == [5.0]
    assert audit["minimal"]["default_steps"] == 60
    areas = {row["area"] for row in audit["divergences"]}
    assert {"schedule", "teacher_distillation", "distributed_training", "artifact"} <= areas
    assert audit["divergences"]


def test_gate_blocks_small_or_busy_gpu() -> None:
    sources = {"ready": True}
    git = {"ok": True, "matches_expected": True, "commit": "abc"}
    environment = {"ok": True, "transformers_4_51": True, "cuda_available": True}
    gpu = {"ok": True, "gpus": [{"name": "RTX", "total_mib": 6141, "used_mib": 5305,
                                  "free_mib": 836, "utilization_percent": 0}]}
    gate = preflight.evaluate_gate(
        sources, git, gpu, environment,
        min_vram_mib=16384, min_free_mib=12288,
    )
    assert gate["ready_for_official_qat"] is False
    assert gate["hardware_ready"] is False
    assert any("requires 16384 MiB" in reason for reason in gate["reasons"])


def test_gate_can_pass_only_with_all_requirements() -> None:
    sources = {"ready": True}
    git = {"ok": True, "matches_expected": True, "commit": "abc"}
    environment = {"ok": True, "transformers_4_51": True, "cuda_available": True}
    gpu = {"ok": True, "gpus": [{"name": "A100", "total_mib": 24576, "used_mib": 2000,
                                  "free_mib": 22576, "utilization_percent": 0}]}
    gate = preflight.evaluate_gate(
        sources, git, gpu, environment,
        min_vram_mib=16384, min_free_mib=12288,
    )
    assert gate["ready_for_official_qat"] is True
    assert gate["reasons"] == []


def test_python_probe_is_import_only_and_reports_versions(tmp_path: Path) -> None:
    fake = tmp_path / "python"
    fake.write_text(
        "#!/bin/sh\nprintf '%s\\n' '{\"torch\":\"2.6.0\",\"cuda_available\":true,\"transformers\":\"4.51.3\"}'\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    probe = preflight.probe_python(fake)
    assert probe["ok"] is True
    assert probe["torch"] == "2.6.0"
    assert probe["transformers_4_51"] is True
    assert probe["cuda_available"] is True


def test_collect_report_never_starts_training(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    official, minimal = write_sources(tmp_path)
    monkeypatch.setattr(preflight, "probe_gpu", lambda: {"ok": True, "gpus": []})
    monkeypatch.setattr(preflight, "probe_python", lambda _path: {
        "ok": False, "torch": None, "transformers": "", "transformers_4_51": False,
        "cuda_available": False, "error": "fixture",
    })
    monkeypatch.setattr(preflight, "probe_git", lambda _path, _expected: {
        "ok": True, "commit": preflight.EXPECTED_OFFICIAL_COMMIT,
        "expected": preflight.EXPECTED_OFFICIAL_COMMIT, "matches_expected": True, "error": "",
    })
    args = preflight.build_parser().parse_args([
        "--official-dir", str(official), "--minimal", str(minimal),
        "--python", str(tmp_path / "unused-python"),
    ])
    report = preflight.collect_report(args)
    assert report["training_started"] is False
    assert report["read_only"] is True
    assert report["gate"]["ready_for_official_qat"] is False
    assert report["sources"]["divergences"]
