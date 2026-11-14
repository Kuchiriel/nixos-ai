import hashlib

import numpy as np
import onnxruntime as ort
import wave
from pathlib import Path
from transformers import WhisperFeatureExtractor

SR = 16000
CACHE = Path.home() / ".cache" / "duplex-conveyor"

TEXTS = [
    "Jarvis, que horas são?",
    "Jarvis, muda o brilho para cem",
    "Jarvis, me lembra de ligar para mãe amanhã",
    "Jarvis, tem reunião amanhã de manhã?",
    "Jarvis, você ouviu o que eu falei?",
    "Hoje no jornal de amanhã",
    "O Flamengo ganhou de três a zero no último jogo",
    "Jarvis, qual o significado da vida?",
]

feat = WhisperFeatureExtractor(chunk_length=8)
sess = ort.InferenceSession("/tmp/opencode/smart-turn-v3.2-cpu.onnx")

for text in TEXTS:
    cache = CACHE / f"conv-{hashlib.sha256(text.encode()).hexdigest()[:16]}.wav"
    if not cache.exists():
        print(f"MISSING {cache}")
        continue
    with wave.open(str(cache), "rb") as w:
        raw = w.readframes(w.getnframes())
        raw_sr = w.getframerate()
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n_dst = int(len(pcm) * SR / raw_sr)
    pcm = np.interp(np.linspace(0, len(pcm) - 1, n_dst), np.arange(len(pcm)), pcm).astype(np.float32)
    max_n = SR * 8
    if len(pcm) < max_n:
        pcm = np.pad(pcm, (max_n - len(pcm), 0), mode="constant")
    else:
        pcm = pcm[-max_n:]
    feats = feat(pcm, sampling_rate=SR, return_tensors="np",
                 padding="max_length", max_length=SR * 8,
                 truncation=True, do_normalize=True).input_features.squeeze(0).astype(np.float32)
    out = sess.run(None, {"input_features": feats[None]})
    prob = float(out[0].reshape(-1)[0])
    print(f"prob={prob:.3f}  {text!r}")
