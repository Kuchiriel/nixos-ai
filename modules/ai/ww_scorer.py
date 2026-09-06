#!/usr/bin/env python3
"""hey_jarvis clip scorer — vendored algorithm from dscripka/openWakeWord.

Upstream: https://github.com/dscripka/openWakeWord (Apache-2.0).
Replicates openwakeword.model.Model.predict + AudioFeatures streaming
(ONNX path) for offline clip scoring: mel ONNX -> embedding ONNX (76-frame
windows, step 8) -> classifier ONNX over last 16 embeddings.

Only dependencies: numpy + onnxruntime. No torch, no tflite, no scipy.

Usage:
    ww_scorer.py --models DIR --wav FILE [--threshold 0.5] [--chunks 1280]
Prints max score; exit 0 if >= threshold else 1.
"""
from __future__ import annotations

import argparse
import sys
import wave
from collections import deque

import numpy as np

CHUNK = 1280  # 80 ms @ 16 kHz


def load_mono16k(path: str) -> np.ndarray:
    with wave.open(path, "rb") as f:
        n = f.getnframes()
        raw = f.readframes(n)
        data = np.frombuffer(raw, dtype=np.int16).copy()
        if f.getnchannels() > 1:
            data = data.reshape(-1, f.getnchannels()).mean(axis=1).astype(np.int16)
        if f.getframerate() != 16000:
            raise ValueError(f"need 16 kHz, got {f.getframerate()}")
        return data


class Scorer:
    def __init__(self, mel_path: str, emb_path: str, clf_path: str):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        prov = ["CPUExecutionProvider"]
        self._mel = ort.InferenceSession(mel_path, sess_options=opts, providers=prov)
        self._emb = ort.InferenceSession(emb_path, sess_options=opts, providers=prov)
        self._clf = ort.InferenceSession(clf_path, sess_options=opts, providers=prov)
        self.reset()

    def reset(self) -> None:
        self.raw: deque = deque(maxlen=160000)
        self.melbuf = np.ones((76, 32), dtype=np.float32)
        self.mel_max = 10 * 97
        self.acc = 0
        self.remainder = np.empty(0)
        self.featbuf = self._embeddings(
            np.random.randint(-1000, 1000, 16000 * 4).astype(np.int16)
        )
        self.feat_max = 120

    def _mel_predict(self, x: np.ndarray) -> np.ndarray:
        x = np.array(x).astype(np.int16)
        if len(x.shape) < 2:
            x = x[None,]
        x = x.astype(np.float32)
        spec = np.squeeze(self._mel.run(None, {"input": x})[0])
        return spec / 10 + 2

    def _embeddings(self, x: np.ndarray) -> np.ndarray:
        spec = self._mel_predict(x)
        windows = []
        for i in range(0, spec.shape[0], 8):
            w = spec[i : i + 76]
            if w.shape[0] == 76:
                windows.append(w)
        if not windows:
            return np.empty((0, 96), dtype=np.float32)
        batch = np.expand_dims(np.array(windows), axis=-1).astype(np.float32)
        return self._emb.run(None, {"input_1": batch})[0].squeeze()

    def _feed(self, x: np.ndarray) -> None:
        if self.remainder.shape[0] != 0:
            x = np.concatenate((self.remainder, x))
            self.remainder = np.empty(0)
        if self.acc + x.shape[0] >= CHUNK:
            rem = (self.acc + x.shape[0]) % CHUNK
            if rem != 0:
                self.raw.extend(x[0:-rem].tolist())
                self.acc += len(x[0:-rem])
                self.remainder = x[-rem:]
            else:
                self.raw.extend(x.tolist())
                self.acc += x.shape[0]
                self.remainder = np.empty(0)
        else:
            self.acc += x.shape[0]
            self.raw.extend(x.tolist() if isinstance(x, np.ndarray) else x)
        if self.acc >= CHUNK and self.acc % CHUNK == 0:
            mel = self._mel_predict(np.array(list(self.raw)[-self.acc - 480 :]))
            self.melbuf = np.vstack((self.melbuf, mel))[-self.mel_max :, :]
            for i in range(self.acc // CHUNK - 1, -1, -1):
                ndx = -8 * i
                ndx = ndx if ndx != 0 else len(self.melbuf)
                win = self.melbuf[-76 + ndx : ndx].astype(np.float32)[None, :, :, None]
                if win.shape[1] == 76:
                    emb = self._emb.run(None, {"input_1": win})[0].squeeze()
                    self.featbuf = np.vstack((self.featbuf, emb))
            self.acc = 0
        if self.featbuf.shape[0] > self.feat_max:
            self.featbuf = self.featbuf[-self.feat_max :, :]

    def _classify(self) -> float:
        feats = self.featbuf[-16:, :][None,].astype(np.float32)
        return float(self._clf.run(None, {"x.1": feats})[0][0][0])

    def score_clip(self, pcm: np.ndarray, pad_s: int = 1) -> float:
        self.reset()
        if pad_s:
            pcm = np.concatenate(
                (np.zeros(16000 * pad_s, dtype=np.int16), pcm,
                 np.zeros(16000 * pad_s, dtype=np.int16))
            )
        best = 0.0
        n_frames = 0
        for i in range(0, pcm.shape[0] - CHUNK, CHUNK):
            self._feed(pcm[i : i + CHUNK])
            n_frames += 1
            if n_frames <= 5:
                continue  # initFrames zeroed, como no upstream
            try:
                s = self._classify()
            except Exception:
                continue
            best = max(best, s)
        return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()
    sc = Scorer(
        f"{args.models}/melspectrogram.onnx",
        f"{args.models}/embedding_model.onnx",
        f"{args.models}/hey_jarvis_v0.1.onnx",
    )
    pcm = load_mono16k(args.wav)
    score = sc.score_clip(pcm)
    print(f"score={score:.4f}")
    return 0 if score >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
