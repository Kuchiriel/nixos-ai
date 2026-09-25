#!/usr/bin/env python3
"""MemoryArena-lite: o H1 no formato de USO ATIVO (25/09).

Por que este script existe: o H1 (16/09) testou "escreve e lê de volta" e
deu INCONCLUSIVE. Esse formato é *recall passivo* — e a régua honesta da
literatura (MemoryArena, He et al. 2026) é uso ativo: tarefa multi-sessão
interdependente onde um passo posterior só acerta se o agente USOU o que
aprendeu antes. Modelos quase perfeitos em recall passivo caem a 40-60% em
uso ativo. Então o INCONCLUSIVE do H1 não era "memória não importa": era
instrumento medindo a coisa errada.

Design (3Fatores, deliberadamente barato para rodar em CPU+bonsai):
  - FATO learns: o agente recebe um fato no meio da tarefa (ex.: a pessoa
    prefere que a resposta final venha em PT-BR e sem emoji).
  - DECIDE: depois, ele tem que produzir uma decisão que VIOLA o padrão
    default se não tiver usado o fato (default do sistema = inglês + emoji).
  - A pontuação é binária e mecânica: a decisão final está no formato que o
    fato mandou? Não há LLM-judge, então o veredito não é opinião.

Braços:
  C0  controle — sem ferramenta de memória (não pode recuperar nada)
  C1  memória  — com recall/lessons disponíveis
n por braço é configurável; n=1 não decide nada (variância do agente
domina — lição medida em 16/09: mesma task 4s / 300s timeout / false_done).

Uso:
  nix develop --command python3 scripts/memory-arena-lite.py --n 3
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

EVIDENCE = Path("scripts/overnight-24-09/memory-arena-lite.json")

# Fatos: cada um define uma restrição que o DEFAULT do agente viola.
# Se o agente não usar o fato, ele produz a resposta default (português
# não, emoji sim) e a checagem mecânica reprova.
FACTOS = [
    {
        "id": "en_sem_emoji",
        "fato": "IMPORTANTE: neste projeto o dono trabalha em INGLES e NUNCA usa "
                "emoji. Responda em ingles, sem emoji.",
        "proibido": [r"[\U0001F300-\U0001FAFF\u2600-\u27BF]"],
        # >=2 palavras que EXISTEM em ingles e NAO em portugues. A primeira
        # versao aceitava "status do projeto hoje" porque 'status' existe
        # nos dois idiomas — falsava o veredito e inflava o C0.
        "exigido_min": ["the", "and", "is", "are", "we", "today", "currently",
                        "finished", "updated", "this"],
    },
    {
        "id": "sem_emoji",
        "fato": "IMPORTANTE: neste projeto e PROIBIDO usar emoji, sem excecao, em "
                "qualquer resposta.",
        "proibido": [r"[\U0001F300-\U0001FAFF\u2600-\u27BF]"],
        "exigido": None,
    },
    {
        "id": "minusculas",
        "fato": "IMPORTANTE: neste projeto TODAS as respostas devem ser escritas "
                "inteiramente em minusculas, sem nenhuma letra maiuscula.",
        "proibido": [r"[A-Z]"],
        "exigido": None,
    },
    {
        "id": "sem_numeros",
        "fato": "IMPORTANTE: neste projeto e PROIBIDO usar algarismos em qualquer "
                "resposta. Escreva as quantidades por extenso.",
        "proibido": [r"\d"],
        "exigido": None,
    },
    {
        "id": "tres_itens",
        "fato": "IMPORTANTE: neste projeto toda resposta final deve ser uma lista "
                "com TRES itens, cada um comecando com '- '.",
        "proibido": [],
        "exigido": r"(?m)^- .+\n- .+\n- ",
    },
    {
        "id": "sem_aspas",
        "fato": "IMPORTANTE: neste projeto e PROIBIDO usar aspas nas respostas.",
        "proibido": ["\u201c", "\u201d", "\u2018", "\u2019"],
        "exigido": None,
    },
]

PERGUNTA = ("Escreva um paragrafo curto de status do projeto de hoje, "
            "obedecendo o formato que o dono definiu para este projeto.")

REGRAS = [
    # (regex, violação)  — mecânico, sem LLM-judge
    (r"[😀-🙏🌀-🫿]", "emoji presente (fato proíbe)"),
]


@dataclass
class Resultado:
    braço: str
    n: int
    acertos: int = 0
    falhas: list[str] = field(default_factory=list)
    duracoes: list[float] = field(default_factory=list)
    erro: str | None = None


def avalia(texto: str, item: dict) -> tuple[bool, str | None]:
    """Veredito MECANICO: as restricoes do item foram obedecidas?

    Sem LLM-judge de proposito: se o juiz fosse o proprio modelo sob
    teste, o numero passaria a medir o humor do juiz.
    """
    import re

    for padrao in item.get("proibido") or []:
        m = re.search(padrao, texto)
        if m:
            return False, f"violou proibido {m.group(0)!r}"
    exigido = item.get("exigido")
    if exigido and not re.search(exigido, texto):
        return False, f"nao atende exigido {exigido!r}"
    minimo = item.get("exigido_min")
    if minimo:
        palavras = set(re.findall(r"[a-z']+", texto.lower()))
        achadas = palavras & set(w.lower() for w in minimo)
        if len(achadas) < 2:
            return False, f"so {len(achadas)} palavra(s) de ingles: {sorted(achadas)}"
    return True, None

def roda_braço(agent, braço: str, n: int) -> Resultado:
    r = Resultado(braço=braço, n=n)
    for i in range(n):
        fato = FACTOS[i % len(FACTOS)]
        t0 = time.time()
        try:
            # passo 1: o agente "aprende" o fato
            agent.learn(fato["fato"])
            # passo 2: a decisão posterior depende do fato
            texto = agent.decide(PERGUNTA,use_memory=(braço == "C1"))
        except Exception as exc:  # noqa: BLE001
            r.erro = f"{type(exc).__name__}: {exc}"
            r.falhas.append(r.erro)
            continue
        r.duracoes.append(time.time() - t0)
        ok, motivo = avalia(texto, fato)
        if ok:
            r.acertos += 1
        else:
            r.falhas.append(motivo or "formato default (fato ignorado)")
    return r


class _Agente:
    """Plug no stack real: EpisodicMemory (Qdrant) + LLM do router.

    Cada episodio e um CONTEXTO FRESCO (uma chamada, sem historico): e isso
    que separa "sabe a resposta" de "usa a memoria". C1 grava o fato e o
    recupera por recall; C0 nao tem memoria - a diferenca observada e o
    efeito da memoria, nao a sorte do modelo.
    """

    def __init__(self, usar_memoria: bool) -> None:
        import dataclasses as _dc
        from jarvis.core.config import Config
        from jarvis.core.memory import EpisodicMemory
        from jarvis.providers.llm_llama_cpp import LlamaCppBackend

        self.usar = usar_memoria
        import os as _os
        # o router aceita o NOME do tier (bonsai/qwen4b/moe); "default"
        # nao existe e devolve 400 "model not found".
        self.llm = LlamaCppBackend(model=_os.environ.get("JARVIS_ARENA_MODEL", "bonsai"),
                                   enable_thinking=False)
        cfg = _dc.replace(Config(), qdrant_collection_code="memories")
        self.mem = EpisodicMemory(cfg) if usar_memoria else None
        self._fato = ""

    def learn(self, fato: str) -> None:
        self._fato = fato
        if self.mem is not None:
            self.mem.remember_fact(fato, source="memory-arena-lite")

    def decide(self, pergunta: str, *, use_memory: bool) -> str:
        ctx = ""
        if use_memory and self.mem is not None:
            hits = self.mem.recall(self._fato[:80], top_k=2)
            # recall devolve dicts (id/score/kind/text), não objetos
            ctx = "@@".join(str(h.get("text", "")) if isinstance(h, dict)
                             else str(getattr(h, "text", "")) for h in hits)
        msgs = []
        if ctx:
            msgs.append({"role": "system",
                         "content": "Contexto recuperado da sua memoria: " + ctx})
        msgs.append({"role": "user", "content": pergunta})
        resp = self.llm.chat(msgs, temperature=0.0, max_tokens=200)
        # o backend devolve ChatResponse; o veredito é sobre o TEXTO
        return getattr(resp, "text", None) or str(resp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3, help="episódios por braço")
    ap.add_argument("--dry", action="store_true", help="mostra o plano e sai")
    args = ap.parse_args()

    if args.dry:
        print(f"n={args.n} por braço; braços: C0 (sem memória) / C1 (com memória)")
        print(f"fatos: {[f['id'] for f in FACTOS]}")
        print(f"evidência -> {EVIDENCE}")
        return 0

    from jarvis.core.memory import EpisodicMemory  # noqa: F401  (valida o plug)

    print(f"n={args.n} por braço | C0=controle C1=memória | evidência -> {EVIDENCE}")
    resultados = []
    for braco, usar in (("C0", False), ("C1", True)):
        r = roda_braço(_Agente(usar), braco, args.n)
        resultados.append(r)
        pct = 100.0 * r.acertos / max(r.n, 1)
        print(f"  {braco}: {r.acertos}/{r.n} ({pct:.0f}%) falhas={r.falhas or '—'}"
              f"{' ERRO=' + r.erro if r.erro else ''}")
        if r.duracoes:
            print(f"      t_mediano={statistics.median(r.duracoes):.1f}s")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({
        "n_por_braco": args.n,
        "instrumento": "memory-arena-lite (uso ativo, Mechanical, sem LLM-judge)",
        "resultados": [
            {"braco": r.braço, "n": r.n, "acertos": r.acertos,
             "falhas": r.falhas, "erro": r.erro,
             "t_mediano": (statistics.median(r.duracoes) if r.duracoes else None)}
            for r in resultados
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("evidencia -> " + str(EVIDENCE))
    return 0 if all(r.erro is None for r in resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
