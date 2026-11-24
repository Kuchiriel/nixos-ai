#!/usr/bin/env python3
"""alien-sampling — gerar HIPOTESES NOVAS por combinacao de papers do RAG.

Inspirado no Lacuna/Tiptree (research map, alien sampling): combinacoes de
ideias plausiveis sob a estrutura do conhecimento, mas improváveis sob a
distribuicao dos pesquisadores. Nao e' finding — e' candidato a experimento.

Uso: python3 alien-sampling.py --out <json>
"""
from __future__ import annotations
import argparse, itertools, json
from pathlib import Path

# Pares de conceitos de papers JA indexados em jarvis_test_frontier_2026_11.
# Cada tupla: (id, conceito, paper, pergunta que a combinacao levanta)
CONCEPTS = [
    ("dory_elastic", "elastic depth: k variavel no mesmo checkpoint", "2611.03998"),
    ("dory_kv", "last-loop KV cache (memoria constante com k)", "2611.03998"),
    ("bitnet_ternary", "pesos {-1,0,1} com QAT", "2402.17764"),
    ("littlebit_itq", "Joint-ITQ alinha fatores ao hipercubo binario", "Samsung ICML2026"),
    ("byte_eot", "vocab 256 bytes + End-Of-Token, 1/6 dos dados", "2609.12303"),
    ("hybrid_latent", "modo latente auditavel com HybridLink", "2610.18861"),
    ("loop_lora", "LoRA por loop (W + B_l A_l)", "2610.40325"),
    ("inr_hyper", "hypernetwork gera pesos de INR continua", "2504.16580"),
    ("self_rewrite", "modelo reescreve proprios pesos sem gradiente", "2611.21885"),
]

# Combinacoes deliberadamente "alienigenas" (baixa probabilidade, alta plausibilidade)
PAIRS = [
    ("dory_elastic", "bitnet_ternary",
     "E se o numero de loops variar junto com a precisao ternaria por camada — "
     "k=4 com camadas ternarias e k=1 com int4 no MESMO checkpoint?"),
    ("dory_kv", "hybrid_latent",
     "E se o cache KV do ultimo loop tambem servisse de working memory para "
     "pensamentos latentes entre turnos, zerando o custo de context assembly?"),
    ("byte_eot", "littlebit_itq",
     "Joint-ITQ nos embeddings de 256 bytes — a geometria do hipercubo binario "
     "e' natural para bytes? Medir PPL vs ITQ em vocab BPE."),
    ("loop_lora", "self_rewrite",
     "E se o adapter por loop fosse reescrito pelo proprio modelo em operacao "
     "(sem gradiente), especializando k para a tarefa atual?"),
    ("inr_hyper", "dory_elastic",
     "E se a INR representasse a funcao de profundidade f(k) e a hypernetwork "
     "gerasse os pesos do loop k sob demanda, eliminando o checkpoint elastico?"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    by_id = {c[0]: c for c in CONCEPTS}
    out = []
    for x, y, q in PAIRS:
        cx, cy = by_id[x], by_id[y]
        out.append({"a": x, "b": y, "papers": [cx[2], cy[2]],
                    "hypothesis": q,
                    "status": "candidate",
                    "note": "alien sampling — nao e' evidencia; vira experimento so com gate medido"})
    a_out = Path(a.out)
    a_out.parent.mkdir(parents=True, exist_ok=True)
    a_out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
