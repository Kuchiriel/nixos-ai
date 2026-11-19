"""Mede o CORTE DE SIMILARIDADE que o verificador de held-out deve usar.

POR QUE (18/11, sweep-2026-11): o verificador do heldout3 reprovou 24/34
itens como "quase-duplicata" no corte 0,55 — e olhando os pares, varios NAO
sao quas duplicatas: 'as provas de resistencia foram recolhidas pela manha' vs
'Jarvis, lembra de comprar leite amanha pela manha' = 0,600. Isso e' o
corte pegando o 'pela manha' em comum, nao o sentido da frase.

O heldout2 (que a auditoria do v10 reprovou) tem 19/24 no corte 0,55. Entao
o corte tem que ser o MESMO para comparar, mas tem que separar o que e'
template de verdade do que so compartilha palavras.

O QUE ESTE SCRIPT FAZ: para varios cortes, mede
  (a) quantos itens do HELDOUT2 passam (a referencia: 19/24 no 0,55);
  (b) quantos itens do MEU conjunto passariam (o conjunto novo);
  (c) mostra os PIORES pares, para o olho julgar se o corte separa.

O QUE ESTE SCRIPT NAO FAZ: nao escreve nada. (18/11) A primeira versao lia o
artefato `heldout3.py`, que o proprio build REESCREVE a cada execucao — dois
processos medindo e gravando o mesmo arquivo ao mesmo tempo davam numeros
diferentes a cada rodada. Agora os dados vem do modulo `build_heldout3`, que
e' a FONTE, e nao do artefato gerado.
"""
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
TRAIN = REPO / "datasets/duplex-gate-v9/combined.jsonl"
CORTES = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)


def norm_str(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def sim(a, b):
    return SequenceMatcher(None, norm_str(a), norm_str(b)).ratio()


def treino():
    out = []
    for ln in TRAIN.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        for m in d.get("messages") or []:
            if (isinstance(m, dict) and m.get("role") == "user"
                    and isinstance(m.get("content"), str)
                    and m["content"].strip()):
                out.append(m["content"])
                break
    return out


def main():
    sys.path.insert(0, str(REPO / "benchmarks/voice"))
    from heldout2 import HELDOUT2
    # a FONTE dos dados: o modulo do build, nao o artefato que ele reescreve
    from build_heldout3 import DADOS

    ft = treino()
    h2 = [t for t, _ in HELDOUT2]
    h3 = [t for t, _, _ in DADOS]
    print(f"treino: {len(ft)} falas | heldout2: {len(h2)} | conjunto novo: {len(h3)}")
    print()
    print(f"{'corte':>6s} {'h2 passa':>10s} {'novo passa':>11s}  leitura")
    for c in CORTES:
        p2 = sum(1 for x in h2 if any(sim(x, t) >= c for t in ft))
        p3 = sum(1 for x in h3 if any(sim(x, t) >= c for t in ft))
        print(f"{c:6.2f} {p2:5d}/{len(h2):<4d} {p3:6d}/{len(h3):<4d}")
    print()
    print("os PIORES pares do conjunto novo no corte 0,55 (para o olho julgar):")
    piores = []
    for x in h3:
        melhor, mt = 0.0, ""
        for t in ft:
            s = sim(x, t)
            if s > melhor:
                melhor, mt = s, t
        piores.append((melhor, x, mt))
    piores.sort(reverse=True)
    for s, x, t in piores[:8]:
        print(f"  {s:.3f} | {x!r}")
        print(f"         ~ {t!r}")
    print()
    print("os PIORES pares do HELDOUT2 (a referencia do que E' template):")
    piores2 = []
    for x in h2:
        melhor, mt = 0.0, ""
        for t in ft:
            s = sim(x, t)
            if s > melhor:
                melhor, mt = s, t
        piores2.append((melhor, x, mt))
    piores2.sort(reverse=True)
    for s, x, t in piores2[:5]:
        print(f"  {s:.3f} | {x!r}")
        print(f"         ~ {t!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
