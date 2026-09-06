"""Conversão de voz RVC (timbre de personagem) — pós-processamento do TTS.

Pipeline: texto → Kokoro (PT-BR limpo) → RVC (timbre) → WAV final.
A inferência RVC é pesada (torch/faiss/hubert) e vive fora do núcleo Nix
(venv + checkout Applio configurados via env — ver scripts/rvc-spike-bootstrap.sh).
Este módulo orquestra via subprocesso e degrada com ERROR claro se ausente.

Env:
  JARVIS_RVC_PYTHON       python com torch/faiss/librosa (/tmp/opencode/tts-venv/bin/python)
  JARVIS_RVC_APP_DIR      checkout Applio (módulo rvc.infer.infer importável)
  JARVIS_VOICE_CLONE_MODEL  .pth do personagem (~/models/Jarvis_*_best_epoch.pth)
  JARVIS_VOICE_CLONE_INDEX  .index correspondente
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

# Driver RVC autocontido: escrito em tmp a cada chamada (sem depender de
# arquivos soltos). Espelha o rvc-test.py validado no spike (pedalboard sob
# stub — SIGILL nesta CPU; post_process=False de qualquer forma).
_DRIVER_TEMPLATE = """\
import sys
from unittest.mock import MagicMock
sys.modules['pedalboard'] = MagicMock()
from rvc.infer.infer import VoiceConverter
vc = VoiceConverter()
vc.convert_audio(
    audio_input_path={input_path!r},
    audio_output_path={output_path!r},
    model_path={model_path!r},
    index_path={index_path!r},
    f0_method='rmvpe',
    embedder_model='contentvec',
    index_rate=0.75,
    clean_audio=False,
    post_process=False,
)
print('RVC-OK')
"""


def _cfg(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def is_available() -> tuple[bool, str]:
    """Verifica se a stack RVC está configurada. (ok, motivo)."""
    py = _cfg("JARVIS_RVC_PYTHON")
    app = _cfg("JARVIS_RVC_APP_DIR")
    model = _cfg("JARVIS_VOICE_CLONE_MODEL")
    index = _cfg("JARVIS_VOICE_CLONE_INDEX")
    if not py or not Path(py).exists():
        return False, "JARVIS_RVC_PYTHON ausente (ver scripts/rvc-spike-bootstrap.sh)"
    if not app or not Path(app, "rvc", "infer", "infer.py").exists():
        return False, "JARVIS_RVC_APP_DIR ausente ou sem rvc/infer/infer.py"
    if not model or not Path(model).exists():
        return False, "JARVIS_VOICE_CLONE_MODEL ausente"
    if not index or not Path(index).exists():
        return False, "JARVIS_VOICE_CLONE_INDEX ausente"
    return True, ""


def _run_driver(
    pairs: list[tuple[str, str]],
    model: str,
    index: str,
    timeout_s: int,
) -> tuple[bool, str]:
    """Executa o driver batch (UM processo, modelos carregados 1x)."""
    items = "\n".join(f"{i}\t{o}" for i, o in pairs)
    driver = _BATCH_TEMPLATE.format(
        items=items, model_path=model, index_path=index,
    )
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(driver)
            driver_path = f.name
        env = dict(os.environ)
        app_dir = _cfg("JARVIS_RVC_APP_DIR")
        env["PYTHONPATH"] = app_dir + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        extra_ld = _cfg("JARVIS_RVC_LD_PATH")
        if extra_ld:
            env["LD_LIBRARY_PATH"] = extra_ld + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        proc = subprocess.run(
            [_cfg("JARVIS_RVC_PYTHON"), driver_path],
            cwd=app_dir, env=env, capture_output=True, text=True,
            input=items, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout após {timeout_s}s"
    except OSError as exc:
        return False, f"spawn falhou: {exc}"
    finally:
        try:
            Path(driver_path).unlink()
        except (NameError, OSError):
            pass
    if proc.returncode != 0 or "RVC-BATCH-OK" not in (proc.stdout or ""):
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = " | ".join(err[-3:]) if err else f"exit={proc.returncode}"
        return False, tail[:300]
    return True, ""


def clone_many(
    pairs: list[tuple[str, str]],
    *,
    model_path: str | None = None,
    index_path: str | None = None,
    timeout_s: int = 1800,
) -> dict[str, str]:
    """Converte N arquivos com UMA carga de modelos. Retorna {input: output|ERROR}."""
    result: dict[str, str] = {}
    if not pairs:
        return result
    ok, reason = is_available()
    if not ok:
        return {i: f"ERROR: voice-clone indisponível: {reason}" for i, _ in pairs}
    missing = [i for i, _ in pairs if not Path(i).exists()]
    for i in missing:
        result[i] = f"ERROR: input inexistente: {i}"
    todo = [(i, o) for i, o in pairs if i not in result]
    if not todo:
        return result
    model = model_path or _cfg("JARVIS_VOICE_CLONE_MODEL")
    index = index_path or _cfg("JARVIS_VOICE_CLONE_INDEX")
    t0 = time.monotonic()
    good, err = _run_driver(todo, model, index, timeout_s)
    elapsed = time.monotonic() - t0
    for i, o in todo:
        result[i] = o if good and Path(o).exists() else f"ERROR: voice-clone falhou: {err}"
    try:
        from jarvis.core.eventbus import get_bus
        get_bus().publish("voice.clone_batch", {
            "files": len(todo), "ok": sum(1 for v in result.values() if not v.startswith("ERROR")),
            "latency_s": round(elapsed, 1),
        })
    except Exception:  # noqa: BLE001
        pass
    return result


def clone_wav(
    input_wav: str,
    output_wav: str | None = None,
    *,
    model_path: str | None = None,
    index_path: str | None = None,
    timeout_s: int = 300,
) -> str:
    """Converte input_wav para o timbre do modelo. Retorna path ou ERROR:."""
    if output_wav is None and input_wav:
        output_wav = str(Path(input_wav).with_name(Path(input_wav).stem + "-clone.wav"))
    result = clone_many(
        [(input_wav, output_wav or "")],
        model_path=model_path, index_path=index_path, timeout_s=timeout_s,
    )
    return result.get(input_wav, f"ERROR: input inexistente: {input_wav}")


# Driver batch: UMA carga (VoiceConverter+hubert+rmvpe), N conversões.
# stdin: linhas "input\toutput" (evita shell quoting).
_BATCH_TEMPLATE = """\
import sys
from unittest.mock import MagicMock
sys.modules['pedalboard'] = MagicMock()
from rvc.infer.infer import VoiceConverter
vc = VoiceConverter()
count = 0
for line in sys.stdin:
    line = line.rstrip("\\n")
    if not line.strip():
        continue
    src, dst = line.split("\\t")
    vc.convert_audio(
        audio_input_path=src,
        audio_output_path=dst,
        model_path={model_path!r},
        index_path={index_path!r},
        f0_method='rmvpe',
        embedder_model='contentvec',
        index_rate=0.75,
        clean_audio=False,
        post_process=False,
    )
    count += 1
print(f"RVC-BATCH-OK {{count}}")
"""
