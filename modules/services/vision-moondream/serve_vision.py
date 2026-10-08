#!/usr/bin/env python3
"""serve_vision.py — serviço do Moondream2 para tagging de sprites.

Por que um servidor Python e nao o llama-server (medido 08/10, ver
MODELS-VISION.md):

  - llama-server NAO serve imagem para o Moondream2: 400 "Failed to
    tokenize prompt". O GGUF local tem chat_template "vicuna" e o mtmd
    injeta um media_marker ALEATORIO que o tokenizer do Moondream nao
    conhece (llama.cpp #27249/#21955). O GGUF do cjpais tokeniza, mas o
    Q8 esta degenerado ("capital da Franca?" -> "London").
  - A revision 2024-08-26 (sha 92d3d73) traz pesos + codigo CASADOS e
    funciona: 4120 MB em bfloat16, ~1.4 sprites/s.

O processo mantem o modelo carregado (2 s no start, em vez de 3-5 s por
imagem) e expoe:
    GET  /health            -> {"status":"ok"} quando o modelo esta pronto
    POST /tag               -> multipart OU {"path": "..."} -> descricao
    GET  /props             -> config do servico (prompt, precisao)

O prompt e CURTO e POSITIVO de proposito: negative constraints fazem este
modelo colapsar para "Grass" (medido 5/6 sprites). Nao anexar o bloco
"DO NOT:" do PROMPTS-VISION.md aqui.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Offline antes de qualquer import do transformers: sem isto o repo tenta
# a rede no __init__ e morre com 401 (HF_TOKEN expirado) ou baixa
# moondream/starmie-v1.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Prompt validado no bake-off de 08/10 (4 prompts, 5 sprites: 3/5 cada;
# com negative constraints o modelo responde so "Grass").
PROMPT = ("This is a 32x32 pixel-art game tile, shown zoomed and repeated "
          "twice in the middle of a grass field. Describe only what is drawn "
          "on the tile itself, in one short sentence.")

_MODEL = None
_TOK = None
_STATS = {"tagged": 0, "errors": 0, "started": None}


def load(model_dir: str):
    """Carrega o par pinado. bf16 direto — em fp32 estoura os 6 GB."""
    global _MODEL, _TOK
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    _TOK = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True,
                                         local_files_only=True)
    # torch_dtype no from_pretrained: sem isto carrega em fp32 e estoura a
    # VRAM antes de converter (medido: 5.17 GiB alocados).
    _MODEL = AutoModelForCausalLM.from_pretrained(
        model_dir, trust_remote_code=True, local_files_only=True,
        torch_dtype=torch.bfloat16)
    if torch.cuda.is_available():
        _MODEL = _MODEL.to("cuda")
    _MODEL.eval()
    _STATS["started"] = time.time()
    return torch


def tag(path: str, max_new_tokens: int = 48) -> str:
    """Descreve UM sprite. Devolve '' em falha (nao levanta)."""
    import torch
    from PIL import Image
    with torch.no_grad():
        img = Image.open(path).convert("RGB")
        enc = _MODEL.encode_image(img)
        if hasattr(_MODEL, "answer_question"):
            out = _MODEL.answer_question(enc, PROMPT, _TOK,
                                         max_new_tokens=max_new_tokens)
        else:                       # rev nova: query()
            out = _MODEL.query(enc, PROMPT, reasoning=True)["answer"]
    return str(out).strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "jarvis-vision/1.0"

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):        # quieto: log vai pro journal
        pass

    def do_GET(self) -> None:                  # noqa: N802
        if self.path.startswith("/health"):
            ready = _MODEL is not None
            self._json(200 if ready else 503,
                       {"status": "ok" if ready else "loading",
                        "model": "moondream2", "stats": _STATS})
        elif self.path.startswith("/props"):
            self._json(200, {
                "model": "vikhyatk/moondream2",
                "revision": "92d3d73b6fd61ab84d9fe093a9c7fd8c04bf2c0d",
                "tag": "2024-08-26",
                "prompt": PROMPT,
                "prompt_policy": "short and POSITIVE; negative constraints "
                                 "collapse this model to 'Grass'",
                "vram_mb": 4120,
                "dtype": "bfloat16",
                "precision": {"material_color": "good (~60%)",
                              "shape_detail": "poor (0%)",
                              "role": "complements pixel measurement; "
                                      "not authoritative"},
                "stats": _STATS,
            })
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:                 # noqa: N802
        if not self.path.startswith("/tag"):
            self._json(404, {"error": "not found"})
            return
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
            path = data.get("path")
            if not path:
                self._json(400, {"error": "missing 'path'"})
                return
            p = Path(path)
            if not p.is_file():
                self._json(404, {"error": f"not a file: {path}"})
                return
            ans = tag(path)
            _STATS["tagged"] += 1
            self._json(200, {"path": path, "description": ans,
                             "confidence": 0.5 if ans else 0.0,
                             "source": "moondream2-local"})
        except Exception as exc:               # noqa: BLE001
            _STATS["errors"] += 1
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--port", type=int, default=8098)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    print(f"[vision] carregando Moondream2 de {args.model_dir} ...", flush=True)
    torch = load(args.model_dir)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    used = 0
    if dev == "cuda":
        used = int((torch.cuda.mem_get_info()[1] - torch.cuda.mem_get_info()[0])
                   / 1048576)
    print(f"[vision] pronto em {dev} ({used} MB), servindo em "
          f"http://{args.host}:{args.port}", flush=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())