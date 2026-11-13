#!/usr/bin/env python3
"""uhrs-practice.py — treino do rubric de relevancia (e as primeiras labels do dono).

POR QUE (13/11/2026, coord-naming): o UHRS (Microsoft) paga US$ 7 a 14/h e
exige um teste de ingles + um assessment + 50 a 100 itens de qualificacao. Duas
coisas acontecem aqui ao mesmo tempo: (a) o dono treina a REGRA (o rubric de
relevancia da Microsoft) antes do teste real, e (b) cada resposta que ele da
vira uma LABEL (no formato de data/judgments/SCHEMA.md) — que e' o dataset do
Laya treinado com as judgments DELE, ou seja, a resposta que o modelo vai
"responder por procuracao" depois.

COMO RESPONDE (o que importa para quem e' PCD):
  - por TECLADO: o bench imprime o item e le a resposta do teclado;
  - por VOZ: com --from-duplex, o bench le a transcricao direto do log do
    cliente de voz (logs/duplex/<data>.log, marca "SEGMENTO:"), ou seja, o
    dono FALA o veredito e o bench pega. Nao precisa mouse.

O QUE ELE FAZ:
  1) imprime o rubric (curto, em ingles, como o teste real) e o item;
  2) le a resposta do dono (teclado ou voz);
  3) compara com o gabarito do item e explica o por que (o rubric, nao a
     opinion);
  4) grava a label no dataset (JSONL) e atualiza o placar.

USO
    python3 scripts/uhrs-practice.py                 # treino por teclado
    python3 scripts/uhrs-practice.py --from-duplex   # treino por voz
    python3 scripts/uhrs-practice.py --items 5       # so 5 itens
    python3 scripts/uhrs-practice.py --show-rubric   # so o rubric (revisar)

O RUBRIC E O DO MICROSOFT (dominio publico, o mesmo do teste UHRS): a
relevancia e' "a pagina responde a pergunta?" com os niveis Highly Relevant /
Moderately Relevant / Slightly Relevant / Not Relevant, e ha criterios
especificos (qualidade, quantidade de informacao, atualidade, autoridade).
As perguntas de pratica aqui sao escritas por mim no MESMO formato, com o
gabarito no rubric — sao itens de TREINO, nao o teste real.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "judgments"
LABELS = DATA / "labels.jsonl"
ITEMS = DATA / "uhrs-practice-items.jsonl"

RUBRIC = """RUBRIC (Microsoft relevance judgments)

Question to ask: does the page satisfy the user intent of the query?

Highly Relevant (3)
  - The page answers the query directly and completely.
  - It is the best possible result for that query: a single page with the
    answer, with the detail the user asked for.
Moderately Relevant (2)
  - The page answers the query and is a good page, but a better result exists
    (another page is more complete, clearer, fresher, or more authoritative).
Slightly Relevant (1)
  - The page is on the same topic and useful in part, but it does not answer
    the query; the user would still have to click and dig.
Not Relevant (0)
  - The page does not answer the query and does not help the user get to the
    answer (different intent, only a mention, or an empty landing page).

Tie-breakers (Microsoft):
  - Prefer the page that GIVES the information over the page that PROMISES it.
  - Prefer the fresher page when the content is time-sensitive.
  - Prefer the authoritative page (primary source) over the aggregator.
  - A page that is a single direct answer beats a long page with the answer
    buried.
"""

SEED_ITEMS = [
    {"id": "p01",
     "query": "how long does a passport renewal take",
     "snippet": "Passport renewal processing times: 4-6 weeks for routine "
                "renewals by mail, 2-3 weeks for in-person appointments. "
                "Expedited service is 2-3 weeks. Most applications are "
                "reviewed within 10 business days.",
     "answer": "3", "why": "Gives the answer directly, with the variants the "
                           "user needs (mail vs in person vs expedited)."},
    {"id": "p02",
     "query": "how long does a passport renewal take",
     "snippet": "Renew your passport: complete the form, gather your "
                "documents and mail it to us. Appointments are available if "
                "you need to travel in the next 8 weeks.",
     "answer": "1", "why": "Same topic (renewal) but it does not answer how "
                           "long it takes; the user must dig for the answer."},
    {"id": "p03",
     "query": "how long does a passport renewal take",
     "snippet": "Passport renewal guide: everything about eligibility, "
                "fees, forms, appointments, tracking and what to do if your "
                "passport was stolen. See our help centre for the full list "
                "of frequently asked questions and contact options.",
     "answer": "0", "why": "A landing page full of links about renewal that "
                           "never gives the time: it does not answer the "
                           "query."},
    {"id": "p04",
     "query": "q3 2025 adjusted quarterly earnings payment date",
     "snippet": "The IRS announced that the Q3 2025 estimated tax payment "
                "for the quarter ending September 30, 2025, will be due on "
                "January 15, 2026. The Q4 2025 payment is due April 15, 2026.",
     "answer": "3", "why": "Direct answer from the primary source (IRS) with "
                           "the adjacent quarter for context."},
    {"id": "p05",
     "query": "q3 2025 adjusted quarterly earnings payment date",
     "snippet": "Q3 2025 estimated tax payment schedule: Q3 2025 is due on "
                "January 15, 2026. Q4 2025 is due April 15, 2026. Q1 2026 is "
                "due June 15, 2026.",
     "answer": "2", "why": "It does give the date, but it is a schedule "
                           "page, not the announcement: the IRS page is the "
                           "better result for this query."},
    {"id": "p06",
     "query": "error e1702 steam disk write permission",
     "snippet": "E1702 usually means Steam cannot write to the library "
                "folder: check that the drive is not read-only, that the "
                "folder is owned by your user, and that antivirus is not "
                "blocking writes. Moving the library to a non-system drive "
                "fixes most cases.",
     "answer": "3", "why": "Explains the cause and gives the concrete fixes "
                           "for this exact error code."},
    {"id": "p07",
     "query": "error e1702 steam disk write permission",
     "snippet": "Steam error codes: E1702, E1703, E1708 and E1709 explained, "
                "plus how to verify files, clear download history and fix "
                "the library folder. Updated for the latest client.",
     "answer": "1", "why": "Covers the code but as one entry in a list of "
                           "many; the page above is the better result."},
    {"id": "p08",
     "query": "does vitamin d interact with warfarin",
     "snippet": "Vitamin K (found in leafy greens and in vitamin D "
                "supplements) reduces the effect of warfarin. People on "
                "warfarin should keep vitamin K intake consistent and "
                "discuss supplements with their prescriber.",
     "answer": "3", "why": "Direct answer to the interaction, with the "
                           "practical consequence (consistency) and the "
                           "safety route (the prescriber)."},
    {"id": "p09",
     "query": "does vitamin d interact with warfarin",
     "snippet": "Warfarin and other blood thinners: what you should know "
                "about diet, medication interactions and monitoring. Our "
                "pharmacists answer common questions on our blog and in our "
                "free webinar series.",
     "answer": "1", "why": "On topic, mentions interactions in general, but "
                           "does not answer whether vitamin D interacts."},
    {"id": "p10",
     "query": "how to change the default terminal in windows 11",
     "snippet": "To change the default terminal app in Windows 11: open "
                "Settings, go to Apps, then Default apps, search for Windows "
                "Terminal and set it as the default handler. You can also "
                "right-click a .ps1 file, choose Open with and pick Terminal.",
     "answer": "3", "why": "Step-by-step and complete, with the shortcut "
                           "variant."},
    {"id": "p11",
     "query": "how to change the default terminal in windows 11",
     "snippet": "Windows 11 tips and tricks: 40 shortcuts that save you "
                "time, how to move the taskbar, how to use multiple "
                "desktops, and how to personalize the Start menu.",
     "answer": "0", "why": "Different intent: general tips, not the default "
                           "terminal setting."},
    {"id": "p12",
     "query": "ibex 101 server status",
     "snippet": "IBEX-101 (prod, eu-west-1): all checks green as of 09:41 "
                "UTC. p99 latency 212 ms, error rate 0.02%, queue depth 3. "
                "Last deploy 3 hours ago, no incidents in the last 30 days.",
     "answer": "3", "why": "Exactly the status asked for, with the numbers "
                           "and the freshness."},
]


def load_items(path):
    rows = []
    p = Path(path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append(json.loads(line))
    return rows or list(SEED_ITEMS)


def norm(s):
    return " ".join(str(s or "").lower().replace(".", " ").replace(",", " ")
                    .split())


LEVELS = {
    "3": "highly relevant", "2": "moderately relevant",
    "1": "slightly relevant", "0": "not relevant",
    "altamente relevante": "3", "moderadamente relevante": "2",
    "levemente relevante": "1", "nao relevante": "0", "irrelevante": "0",
    "muito relevante": "3", "relevante": "2", "sim": "2", "nao": "0",
    "high": "3", "moderate": "2", "slight": "1", "none": "0",
}


def parse_answer(text):
    t = norm(text)
    if not t:
        return None
    if t in LEVELS:
        return LEVELS[t]
    m = re.search(r"\b([0-3])\b", t)
    if m:
        return m.group(1)
    for word, val in LEVELS.items():
        if word in t:
            return val
    return None


def read_from_duplex(log_path):
    """Le a ultima transcricao do cliente de voz (o dono FALA o veredito)."""
    p = Path(log_path)
    if not p.is_file():
        return ""
    last = ""
    for line in p.read_text(errors="ignore").splitlines()[-400:]:
        if "SEGMENTO:" in line:
            last = line.split("SEGMENTO:", 1)[1].strip()
    return last


def record_label(item, answer, via):
    DATA.mkdir(parents=True, exist_ok=True)
    row = {
        "id": item["id"],
        "context": (f"Query: {item['query']}\nPage: {item['snippet']}\n"
                    f"Answer by the owner: {item.get('answer')}"),
        "answer": item["answer"],
        "source": "uhrs-practice",
        "via": via,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with LABELS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return LABELS


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", type=int, default=0,
                    help="quantos itens de pratica (0 = todos)")
    ap.add_argument("--from-duplex", action="store_true",
                    help="le a resposta da voz no log do cliente de voz")
    ap.add_argument("--duplex-log", default="")
    ap.add_argument("--show-rubric", action="store_true")
    ap.add_argument("--items-file", default=str(ITEMS))
    ap.add_argument("--answer", default="",
                    help="responde um item e sai (para teste automatico)")
    args = ap.parse_args()

    if args.show_rubric:
        print(RUBRIC)
        return 0

    items = load_items(args.items_file)
    if args.items:
        items = items[: args.items]

    log = args.duplex_log or str(
        REPO / "logs" / "duplex" / (time.strftime("%Y-%m-%d") + ".log"))

    print(RUBRIC)
    print(f"itens de pratica: {len(items)} | labels em: {LABELS}")
    if args.from_duplex:
        print(f"modo voz: a resposta e' lida do log do cliente ({log}).")
        print("Fale o veredito ('highly', 'moderately', 'slightly' ou 'not', "
              "ou o numero 3/2/1/0). Ctrl-C para sair.\n")

    right = 0
    for it in items:
        print("-" * 72)
        print(f"QUERY: {it['query']}")
        print(f"PAGE : {it['snippet']}")
        print("sua resposta (3 highly / 2 moderately / 1 slightly / 0 not):",
              end=" ", flush=True)
        if args.answer:
            ans = args.answer
            print(ans)
        elif args.from_duplex:
            ans = ""
            for _ in range(150):
                time.sleep(2)
                ans = read_from_duplex(log)
                if ans:
                    break
            print(ans or "(sem transcricao no log)")
        else:
            ans = input().strip()
        got = parse_answer(ans)
        if got is None:
            print("  nao entendi a resposta; conta como erro.")
        else:
            ok = (got == it["answer"])
            right += ok
            print(f"  gabarito: {it['answer']} ({LEVELS[it['answer']]}) | "
                  f"sua: {got} -> {'ok' if ok else 'erro'}")
            print(f"  porque: {it['why']}")
        record_label(it, got or "unparsed", "voice" if args.from_duplex else "teclado")
    total = len(items)
    print("-" * 72)
    print(f"placar: {right}/{total} = {right/max(1,total):.0%}")
    print(f"labels gravadas em: {LABELS}")
    if right < total:
        print("dica: o erro que mais custa e' chamar de 'relevante' o que so "
              "responde pela metade; releia os criterios de desempate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
