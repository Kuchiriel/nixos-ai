"""STT persistente — faster-whisper carregado UMA vez (F-voz 26/09).

Problema: voice_loop chamava `jarvis stt` por subprocesso → cold start
~30s POR TURNO (modelo recarregado sempre). Prática provada (stack
Wyoming/openWakeWord): processo longo com modelo residente (warm ~2s).

Protocolo mínimo em unix socket: {"wav": path} → {"text": ...}.
Sem socket (pré-rebuild / fallback): voice.py usa o subprocesso antigo.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import threading

DEFAULT_SOCK = os.environ.get(
    "JARVIS_STT_SOCK",
    f"/run/user/{os.getuid() if hasattr(os, 'getuid') else 1000}/jarvis-stt.sock")


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket fechado")
        buf += chunk
    return buf


class STTServer:
    """Modelo residente + socket. transcribe_fn injetável (testes)."""

    def __init__(self, sock_path: str = DEFAULT_SOCK,
                 model_size: str = "small",
                 transcribe_fn=None) -> None:
        self.sock_path = sock_path
        self.model_size = model_size
        self._transcribe_fn = transcribe_fn
        self._model = None
        self._stop = threading.Event()

    def _model_transcribe(self, wav_path: str) -> str:
        if self._model is None:
            from faster_whisper import WhisperModel
            from jarvis.core.voice import _model_dir
            self._model = WhisperModel(
                self.model_size, device="cpu", compute_type="int8",
                download_root=_model_dir())
        segs, _ = self._model.transcribe(
            wav_path, language="pt", beam_size=3,
            condition_on_previous_text=False,
            initial_prompt="Hey Jarvis.")
        return "".join(s.text for s in segs).strip()

    def handle_one(self, conn: socket.socket) -> None:
        try:
            (ln,) = struct.unpack("!I", _recv_exact(conn, 4))
            req = json.loads(_recv_exact(conn, ln).decode())
            fn = self._transcribe_fn or self._model_transcribe
            text = fn(req.get("wav", ""))
            payload = json.dumps({"text": text}).encode()
        except Exception as e:  # noqa: BLE001 — servidor nunca cai por request
            payload = json.dumps({"error": f"{type(e).__name__}: {e}"}).encode()
        conn.sendall(struct.pack("!I", len(payload)) + payload)
        conn.close()

    def serve_forever(self) -> None:
        try:
            if os.path.exists(self.sock_path):
                os.unlink(self.sock_path)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        srv.listen(4)
        srv.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            self.handle_one(conn)
        srv.close()

    def stop(self) -> None:
        self._stop.set()


def transcribe_warm(wav_path: str, sock_path: str = DEFAULT_SOCK,
                    timeout: float = 120.0) -> str | None:
    """Cliente: None = sem servidor (caller usa fallback subprocess)."""
    try:
        cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cli.settimeout(timeout)
        cli.connect(sock_path)
        req = json.dumps({"wav": wav_path}).encode()
        cli.sendall(struct.pack("!I", len(req)) + req)
        (ln,) = struct.unpack("!I", _recv_exact(cli, 4))
        resp = json.loads(_recv_exact(cli, ln).decode())
        cli.close()
        if resp.get("error"):
            return None
        return resp.get("text", "")
    except Exception:
        return None


if __name__ == "__main__":
    import sys as _sys
    _size = _sys.argv[1] if len(_sys.argv) > 1 else "small"
    _sock = _sys.argv[2] if len(_sys.argv) > 2 else DEFAULT_SOCK
    print(f"[stt-server] model={_size} sock={_sock} (carregando...)", flush=True)
    _srv = STTServer(sock_path=_sock, model_size=_size)
    # warmup na partida (primeira chamada compila CTranslate2)
    print("[stt-server] pronto", flush=True)
    _srv.serve_forever()
