"""Q2_0 (QK=64) numpy dequant + self-verify vs unpacked dense.
Layout (wackmall ggml-common.h + ggml-quants.c): block = fp16 scale d
+ 16 bytes qs; values (q-1)*d, q in {0,1,2,3} -> {-1,0,+1,+2}.
g64 grouping verified empirically by correlation with unpacked.
"""
import sys

import numpy as np

sys.path.insert(0, "/home/nixos/projects/llama.cpp/gguf-py")
from gguf import GGUFReader

GGUF2HF = [("blk.", "model.layers."), (".attn_q.", ".self_attn.q_proj."),
           (".attn_k.", ".self_attn.k_proj."), (".attn_v.", ".self_attn.v_proj."),
           (".attn_output.", ".self_attn.o_proj."), (".attn_norm.", ".input_layernorm."),
           (".ffn_gate.", ".mlp.gate_proj."), (".ffn_up.", ".mlp.up_proj."),
           (".ffn_down.", ".mlp.down_proj."), (".ffn_norm.", ".post_attention_layernorm."),
           ("output.weight", "lm_head.weight"), ("token_embd.weight", "model.embed_tokens.weight"),
           ("output_norm.weight", "model.norm.weight")]


def g2h(name):
    for a, b in GGUF2HF:
        name = name.replace(a, b)
    return name


def dequant_q2_0(raw: bytes, n_elements: int, shape) -> np.ndarray:
    QK = 64
    assert n_elements % QK == 0, n_elements
    nb = n_elements // QK
    assert len(raw) == nb * (2 + QK // 4), (len(raw), nb)
    buf = np.frombuffer(raw, dtype=np.uint8).reshape(nb, 18)
    d = buf[:, :2].view(np.float16).astype(np.float32).reshape(nb, 1)
    qs = buf[:, 2:]
    # j = b*4+k -> byte b, offset k*2 (wackmall dequantize_row_q2_0)
    cols = []
    for b in range(16):
        for s in (0, 2, 4, 6):
            cols.append(((qs[:, b] >> s) & 0x03).reshape(nb, 1))
    vals = np.concatenate(cols, axis=1).astype(np.float32) - 1.0
    return (vals * d).reshape(shape)


def main() -> None:
    gguf_path = "/nix/store/nc3rnnsmz17mnhbqfry1xiw3lk5sni0x-Ternary-Bonsai-8B-Q2_0_g64.gguf"
    reader = GGUFReader(gguf_path)
    from safetensors import safe_open
    ok = tested = 0
    with safe_open("/home/nixos/.cache/bonsai-unpacked/model-00001-of-00004.safetensors",
                   framework="np") as f:
        keys = set(f.keys())
        for t in reader.tensors:
            if int(t.tensor_type) != 42:
                continue
            name = g2h(str(t.name))
            n_el = 1
            for s in t.shape:
                n_el *= int(s)
            try:
                raw = bytes(t.data)
                dq = dequant_q2_0(raw, n_el, tuple(int(s) for s in t.shape))
            except Exception as e:
                print("DEQ-FAIL", name, str(e)[:80])
                continue
            if name in keys and tested < 8:
                ref = np.asarray(f.get_slice(name)[:])
                a = dq.ravel().astype(np.float64)
                best = -2.0
                for bb in (ref.ravel().astype(np.float64),):
                    if bb.shape == a.shape:
                        best = max(best, float(np.corrcoef(a, bb)[0, 1]))
                if dq.ndim == 2:
                    bt = dq.T.ravel().astype(np.float64)
                    if bt.shape == a.shape:
                        best = max(best, float(np.corrcoef(a, bt)[0, 1]))
                u = len(np.unique(dq))
                print(f"{name}: corr={best:.4f} uniques={u}", flush=True)
                tested += 1
                ok += best > 0.85
    print(f"layout-verified: {ok}/{tested} (corr>0.85)")


if __name__ == "__main__":
    main()
