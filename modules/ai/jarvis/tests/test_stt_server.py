"""STT persistente — protocolo socket + fallback (F-voz)."""
import threading
import time

from jarvis.core.stt_server import STTServer, transcribe_warm


def _serve(sock, text="OI STT"):
    srv = STTServer(sock_path=sock, transcribe_fn=lambda wav: text)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    for _ in range(100):
        import os
        if os.path.exists(sock):
            break
        time.sleep(0.05)
    return srv


def test_roundtrip_over_socket(tmp_path) -> None:
    sock = str(tmp_path / "stt.sock")
    srv = _serve(sock)
    try:
        assert transcribe_warm("/tmp/x.wav", sock_path=sock) == "OI STT"
    finally:
        srv.stop()


def test_no_server_returns_none(tmp_path) -> None:
    assert transcribe_warm("/tmp/x.wav",
                           sock_path=str(tmp_path / "ausente.sock")) is None


def test_server_error_becomes_none(tmp_path) -> None:
    def boom(wav):
        raise RuntimeError("mic falhou")
    srv = STTServer(sock_path=str(tmp_path / "e.sock"), transcribe_fn=boom)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    import os
    for _ in range(100):
        if os.path.exists(str(tmp_path / "e.sock")):
            break
        time.sleep(0.05)
    try:
        assert transcribe_warm("/tmp/x.wav",
                               sock_path=str(tmp_path / "e.sock")) is None
    finally:
        srv.stop()
