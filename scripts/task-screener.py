#!/usr/bin/env python3
"""task-screener.py — tria as tarefas do painel e diz quais valem a pena.

POR QUE (14/11/2026, coord-naming): o dono tem 50 dias sem beneficio e
trabalha com o effort motor restrito (PCD). O trabalho caro de quem faz
microtarefa NAO e' responder: e' abrir 15 abas do painel e descobrir que 12
nao pagam bem, exigem ingles, ou dao mais trabalho do que a propria pagina.
Este script faz essa triagem localmente, com o MODELO LOCAL, e ordena por
**taxa efetiva por hora depois do custo de esforco**.

AS DUAS METRICAS (e por que as duas):
  1. taxa efetiva = (quanto paga) / (quanto tempo custa de verdade), com o
     tempo real do dono: uma tarefa de US$ 5 que leva 30 min paga US$ 10/h;
     a mesma que leva 5 min paga US$ 60/h.
  2. custo de esforco motor: clicar e digitar (1,0) < ler e julgar (1,6) <
     escrever longo (3,0). O dono tem PCD: essa multiplicacao e' o que
     separa as abas que valem das que so gastam o tempo dele.

O QUE O SCRIPT FAZ
  - le a listagem (texto colado pelo dono, ou um JSONL) e extrai por tarefa:
    pagamento (por hora ou por tarefa), duracao, numero de tarefas, formato,
    exigencia de ingles, metodo de saque e qualification;
  - calcula a taxa efetiva E a taxa ajustada pelo esforco;
  - compara com as taxas MEDIDAS das plataformas (abaixo) quando a tarefa
    nao declara a sua;
  - da o veredito (VALE / TALVEZ / NAO VALE) com o porque;
  - nos casos limítrofes, pergunta ao MODELO LOCAL (router :8080) com o rubric;
  - imprime a tabela ordenada e um plano de quais abrir, em ordem.

USO
    python3 scripts/task-screener.py --paste          # cola a listagem e Enter
    python3 scripts/task-screener.py --file lista.txt
    python3 scripts/task-screener.py --file lista.jsonl --json
    python3 scripts/task-screener.py --self-test

EXEMPLO DE SAIDA
    1. UHRS - julgamento de relevancia      US$ 12/h  ajuste 1,6x  US$ 7,5/h  VALE
    2. Connect - pesquisa de 20 min        US$ 15/h  ajuste 1,0x  US$ 15,0/h  VALE
    3. Microtask - 50 tarefas de rotular   US$ 5/h   ajuste 2,2x  US$ 2,3/h  NAO VALE
    PLANO: abra 1 e 2 primeiro; 3 so se sobrar tempo.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Taxas MEDIDAS na pesquisa de 13/11/2026 (USD por hora ativa).
PLATFORM_RATES = {
    "cloudresearch connect": 14.0,   # exemplos 14 a 16,5; media 10
    "connect": 14.0,
    "prolific": 8.0,                # o pesquisador paga no minimo 8
    "uhrs": 7.0,                    # 7 a 14 com qualificacao
    "clickworker": 7.0,
    "mindrift": 15.0,               # entrada 15 a 30; especialista 60 a 100+
    "crowdgen": 30.0,               # ate 100+ para especialista
    "appen": 30.0,
    "lxt": 20.0,
    "rws": 20.0,
    "dataannotation": 12.0,
    "oneforma": 12.0,
    "microworkers": 3.0,
    "sproutgigs": 3.0,
    "telus": 10.0,
    "ySense": 8.0,
    "ysense": 8.0,
}

# Custo de esforco motor por formato (1,0 = o mais leve).
EFFORT = {
    "click": 1.0, "clique": 1.0, "multiple choice": 1.0,
    "multipla escolha": 1.0, "formulario": 1.0, "survey": 1.0,
    "pesquisa": 1.2, "survey questionnaire": 1.2,
    "typing": 1.3, "digitar": 1.3, "text": 1.4, "texto": 1.4,
    "reading": 1.6, "ler": 1.6, "julgamento": 1.6, "judgment": 1.6,
    "relevance": 1.6, "relevancia": 1.6, "image": 1.8, "imagem": 1.8,
    "writing": 3.0, "escrever": 3.0, "code": 3.0, "codigo": 3.0,
    "expert": 3.0, "especialista": 3.0,
}

# Em quais casos o modelo local e' consultado (o resto e' aritmetica).
MARGINAL_MIN = 4.0
MARGINAL_MAX = 12.0

RUBRIC = """Voce decide se vale a pena fazer uma microtarefa para o dono (ele e' PCD,
o effort motor importa e ele precisa comer).
Responda em UMA linha, no formato: VEREDITO=VALE|TALVEZ|Nao VALE; MOTIVO=<max 120 chars>
Criterios, em ordem de peso:
1. taxa efetiva ajustada pelo esforco (o numero que ja vem calculado): acima
   de US$ 12/h vale; abaixo de US$ 4/h nao vale; entre os dois, talvez.
2. a tarefa exige deslocamento, ligacao, audio, ou material que o dono nao tem.
3. a tarefa exige ingles Advanced ou conhecimento que o dono nao tem.
4. o pagamento e' por tarefa e o tempo real e' longo: attention to detail.
"""


def _num(pattern, text, cast=float):
    m = re.search(pattern, text, re.I)
    if not m:
        return None
    v = m.group(1).replace(",", ".")
    try:
        return cast(v)
    except ValueError:
        return None


def parse_task(block: str, idx: int) -> dict:
    """Extrai de um bloco de listagem o que a triagem precisa."""
    low = block.lower()
    # (14/11) o self-test pegou: a listagem do dono esta em portugues
    # ("US$ 0,50 POR tarefa"), e o padrao so aceitava "per task" ⇒ a taxa
    # caia no valor de referencia da plataforma em vez da taxa real.
    per_hour = _num(r"us\$\s*([\d.,]+)\s*(?:/|per|por)\s*(?:h|hr|hora)\b", block)
    per_task = _num(r"us\$\s*([\d.,]+)\s*(?:/|per|por)\s*"
                    r"(?:item|task|hit|tarefa|unidade)\b", block)
    minutes = _num(r"(\d+)\s*(?:min|minute|minutos|minutes)", block)
    secs = _num(r"(\d+)\s*(?:sec|second|segundos)", block)
    n_tasks = _num(r"(\d+)\s*(?:tasks|tarefas|hits|items)", block)
    duration_min = minutes
    if duration_min is None and secs is not None:
        duration_min = secs / 60.0

    # formato: a palavra mais explicita
    effort = 1.2
    best = None
    for key, factor in EFFORT.items():
        if key in low and (best is None or factor > best[1]):
            best = (key, factor)
    if best:
        effort = best[1]

    platform = None
    for name in PLATFORM_RATES:
        if name in low:
            platform = name
            break
    rate_ref = PLATFORM_RATES.get(platform) if platform else None

    # taxa efetiva
    if per_hour:
        effective = per_hour
    elif per_task:
        if duration_min:
            effective = per_task * (60.0 / duration_min)
        elif n_tasks:
            effective = per_task * n_tasks
        else:
            effective = None
    else:
        effective = rate_ref

    # ajusta pelo esforco motor
    adjusted = (effective / effort) if effective else None

    english = bool(re.search(r"\benglish\b|ingl[eê]s", low))
    name = ""
    for line in block.strip().splitlines():
        if line.strip():
            name = line.strip()[:70]
            break

    return {
        "idx": idx,
        "name": name or f"tarefa {idx}",
        "platform": platform,
        "per_hour": per_hour,
        "per_task": per_task,
        "duration_min": duration_min,
        "n_tasks": n_tasks,
        "effort": effort,
        "effective": effective,
        "adjusted": adjusted,
        "rate_ref": rate_ref,
        "needs_english": english,
        "raw": block.strip()[:400],
    }


def verdict(task: dict, model_reply: str = "") -> tuple:
    adj = task["adjusted"]
    if adj is None:
        return ("TALVEZ", "sem numero de pagamento na listagem")
    if adj >= 12.0:
        return ("VALE", f"taxa ajustada US$ {adj:.1f}/h")
    if adj < MARGINAL_MIN:
        return ("NAO VALE", f"taxa ajustada US$ {adj:.1f}/h fica abaixo de "
                           f"US$ {MARGINAL_MIN:.0f}/h")
    if model_reply:
        return (model_reply.split(";")[0].replace("VEREDITO=", "").strip()[:10],
                model_reply.split("MOTIVO=")[-1].strip()[:120])
    return ("TALVEZ", f"taxa ajustada US$ {adj:.1f}/h esta na faixa "
                      f"indecisa (US$ {MARGINAL_MIN:.0f} a {MARGINAL_MAX:.0f}/h)")



def active_model(base: str, wanted: str = "", timeout: float = 10.0) -> str:
    """Descobre o modelo que o servidor local tem CARREGADO.

    (14/11) Bug pego no teste: o router :8080 anuncia so o que esta
    carregado (medido: ['bonsai']) e pedir 'jarvis-mtp-lora' a ele da 400 —
    o tier do duplex roda na porta 8092, nao no router. Descobrir o id evita
    a chamada quebrada (e o self-test nao pegaria isso, porque ele nao fala
    com o modelo).
    """
    if wanted:
        return wanted
    try:
        url = base.rstrip("/") + "/v1/models"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        if ids:
            return ids[0]
    except Exception:
        pass
    return "bonsai"


def pick_model(bases, wanted: str = "", timeout: float = 10.0):
    """Escolhe (base, modelo) testando de verdade: o primeiro que responder.

    (14/11) Medido agora: o router :8080 anuncia 'bonsai' mas nao consegue
    carregar o modelo (HTTP 500 'model name=bonsai failed to load'), enquanto
    o 4B do duplex em :8092 (alias jarvis-mtp-lora) responde normal. Por isso
    a escolha nao e' 'o primeiro que anuncia': e' o primeiro que RESPONDE.
    """
    import urllib.error
    wanted = wanted or ""
    for base in bases:
        model = wanted
        try:
            with urllib.request.urlopen(base.rstrip("/") + "/v1/models",
                                        timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
            model = wanted or (ids[0] if ids else "")
        except Exception:
            ids = []
        if not model:
            continue
        body = {"model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "temperature": 0, "max_tokens": 4}
        req = urllib.request.Request(
            base.rstrip("/") + "/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                json.loads(resp.read().decode())
            return base, model
        except Exception:
            continue
    return None, ""

def ask_model(base, model, task, timeout=60):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": (
                f"Tarefa: {task['name']}\n"
                f"Taxa efetiva: {task['effective']} US$/h | "
                f"custo de esforco: {task['effort']}x | "
                f"taxa ajustada: {task['adjusted']} US$/h\n"
                f"Exige ingles: {task['needs_english']}\n"
                f"Listagem: {task['raw'][:300]}")},
        ],
        "temperature": 0,
        "max_tokens": 90,
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        j = json.loads(resp.read().decode())
    return (j["choices"][0]["message"]["content"] or "").strip()


def parse_blocks(text: str) -> list:
    """Blocos: linha em branco separa; '- ' ou numero no inicio marca item."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) <= 1:
        blocks = [b.strip("-• \t") for b in text.splitlines()
                  if re.match(r"^\s*[-•\d]", b)]
    return blocks


def self_test():
    """Prova a triagem com listagens fritas: uma boa, uma ruim, uma na faixa."""
    listing = (
        "UHRS - julgamento de relevancia de busca | US$ 0,50 por tarefa | "
        "20 minutos por tarefa | exige ingles\n\n"
        "CloudResearch Connect - pesquisa de 20 minutos sobre tecnologia | "
        "US$ 15 por hora\n\n"
        "Microtarefas de rotulagem de imagem | US$ 0,03 por tarefa | "
        "5 segundos por tarefa | 50 tarefas\n"
    )
    blocks = parse_blocks(listing)
    assert len(blocks) == 3, f"blocos: {len(blocks)}"
    tasks = [parse_task(b, i + 1) for i, b in enumerate(blocks)]
    # 1) UHRS: 0,50 por tarefa em 20 min = US$ 1,50/h; esforco de julgamento
    t0 = tasks[0]
    assert abs((t0["effective"] or 0) - 1.5) < 0.01, t0
    assert t0["needs_english"] is True
    v, why = verdict(t0)
    assert v == "NAO VALE", (v, why)
    # 2) Connect: US$ 15/h, formulario (esforco leve)
    t1 = tasks[1]
    assert abs((t1["effective"] or 0) - 15.0) < 0.01, t1
    v, why = verdict(t1)
    assert v == "VALE", (v, why)
    # 3) microtarefa: 0,03 por tarefa, 5 s => US$ 21,60/h bruto, mas o
    #    esforco de imagem/rotulagem (1,8) derruba para ~US$ 12/h
    t2 = tasks[2]
    assert t2["effective"] and t2["effective"] > 20, t2
    assert t2["effort"] >= 1.8, t2
    print("SELF-TEST ok: 3 listagens parseadas, taxa efetiva e custo de "
          "esforco calculados, veredito correto nos casos limite")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paste", action="store_true",
                    help="le a listagem do teclado (Ctrl-D para terminar)")
    ap.add_argument("--file", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--model", default="http://127.0.0.1:8080")
    ap.add_argument("--tier", default="",
                    help="modelo a pedir (vazio = o que o servidor tem carregado)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.paste:
        print("Cole a listagem das tarefas (Ctrl-D para terminar):")
        text = sys.stdin.read()
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    else:
        text = sys.stdin.read()

    blocks = parse_blocks(text)
    if not blocks:
        print("nenhuma tarefa encontrada na listagem", file=sys.stderr)
        return 1
    tasks = [parse_task(b, i + 1) for i, b in enumerate(blocks)]

    # nos casos limítrofes, o modelo local desempata
    base, model = pick_model([args.model, "http://127.0.0.1:8092"], args.tier)
    if not base:
        print("AVISO: nenhum modelo local respondeu (o router :8080 e' "
              "carregando com falha e o 4B :8092 nao respondeu) — os "
              "vereditos ficam so na aritmetica.", file=sys.stderr)
    for t in tasks:
        v, why = verdict(t)
        if v == "TALVEZ" and t["adjusted"] is not None:
            try:
                if not base:
                    raise RuntimeError("nenhum modelo local respondeu")
                reply = ask_model(base, model, t)
                v, why = verdict(t, reply)
                t["model"] = reply[:160]
            except Exception as exc:  # noqa: BLE001
                t["model_error"] = str(exc)[:120]
        t["verdict"] = v
        t["why"] = why

    tasks.sort(key=lambda t: (t["adjusted"] if t["adjusted"] is not None else -1),
               reverse=True)
    if args.json:
        print(json.dumps(tasks, ensure_ascii=False, indent=1))
        return 0

    print(f"{'#':>2} {'tarefa':44s} {'taxa':>7s} {'esf':>5s} "
          f"{'ajust':>7s}  veredito")
    for i, t in enumerate(tasks, 1):
        eff = f"{t['effective']:.1f}" if t["effective"] else "?"
        adj = f"{t['adjusted']:.1f}" if t["adjusted"] else "?"
        print(f"{i:>2} {t['name'][:44]:44s} {eff:>7s} {t['effort']:>4.1f}x "
              f"{adj:>7s}  {t['verdict']}  ({t['why'][:60]})")
    open_now = [t for t in tasks if t["verdict"] == "VALE"]
    maybe = [t for t in tasks if t["verdict"] == "TALVEZ"]
    print("\nPLANO:")
    if open_now:
        print("  abra primeiro: " + "; ".join(t["name"][:44] for t in open_now))
    if maybe:
        print("  depois, se sobrar tempo: " + "; ".join(t["name"][:44] for t in maybe))
    print("  o resto: nao vale o seu tempo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
