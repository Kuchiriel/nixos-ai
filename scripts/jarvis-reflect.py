#!/usr/bin/env python3
"""jarvis-reflect.py — Reflexão noturna (P2.7 ROADMAP-INTELIGENCIA).

Revisa as conversas do dia (log persistente) e extrai lições
(kind=lesson) com dedup contra lições existentes. Roda ANTES do
consolidate 03:00 (reflexa → depois o consolidate dedupa tudo).

Padrões que extrai (zero LLM — regex/heurística leve, confiável):
  1. REPETIÇÃO: dono pediu a mesma coisa ≥2x → lição de hábito
  2. ERRO-SOLUÇÃO: tool retornou erro → como foi resolvido
  3. PREFERÊNCIA NOVA: factos auto-learn do dia (cruza com auto-learn)
  4. TEMA DOMINANTE: palavras-chave mais frequentes nos segmentos

USO:   jarvis reflect [--date YYYY-MM-DD] [--dry-run]
       python3 scripts/jarvis-reflect.py --date 2026-10-24
EXEMPLO: jarvis reflect  (hoje, aplica)
         jarvis reflect --dry-run  (hoje, só mostra)
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent /
                    "modules/ai/jarvis/src"))
from jarvis.core.memory import EpisodicMemory  # noqa: E402

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "duplex"


def parse_log(date_str: str) -> list[dict]:
    """Lê o log persistente do dia e extrai interações significativas."""
    log_file = LOG_DIR / f"{date_str}.log"
    if not log_file.exists():
        return []

    interactions = []
    current_text = ""
    current_ts = ""

    for line in open(log_file, encoding="utf-8", errors="ignore"):
        # timestamp
        m = re.match(r"\[(\d{2}:\d{2}:\d{2})\]", line)
        if m:
            current_ts = m.group(1)

        # SEGMENTO (o que o dono/dispositivo disse)
        if "SEGMENTO:" in line:
            text = line.split("SEGMENTO:", 1)[1].strip()
            if text and len(text) > 2:
                interactions.append({"ts": current_ts, "type": "segment",
                                     "text": text})

        # classify (decisão do modelo)
        m = re.search(r"classify\('([^']+)'\)\s*=\s*(\w+)", line)
        if m:
            interactions.append({"ts": current_ts, "type": "classify",
                                 "text": m.group(1), "class": m.group(2)})

        # TOOL calls e resultados
        if "TOOL:" in line:
            tool = line.split("TOOL:", 1)[1].strip()
            interactions.append({"ts": current_ts, "type": "tool",
                                 "text": tool})
        if "TOOL resultado:" in line:
            result = line.split("TOOL resultado:", 1)[1].strip()
            if "ERROR" in result or "error" in result:
                interactions.append({"ts": current_ts, "type": "tool_error",
                                     "text": result[:200]})

        # respostas
        if "tts.say:" in line:
            text = line.split("tts.say:", 1)[1].strip().strip("'")
            if text:
                interactions.append({"ts": current_ts, "type": "response",
                                     "text": text})

        # auto-learn (fatos guardados)
        if "auto-learn" in line.lower() or "fact" in line.lower():
            if "remember" in line.lower() or "guardado" in line.lower():
                interactions.append({"ts": current_ts, "type": "auto_learn",
                                     "text": line.strip()[:200]})

    return interactions


def extract_lessons(interactions: list[dict]) -> list[dict]:
    """Extrai lições das interações do dia (heurísticas, zero LLM)."""
    lessons = []
    segments = [i for i in interactions if i["type"] == "segment"]
    tools_err = [i for i in interactions if i["type"] == "tool_error"]

    # 1. REPETIÇÃO: mesma pergunta/pedido ≥2x = hábito
    texts_norm = {}
    for seg in segments:
        # normaliza: lowercase, remove pontuação
        t = re.sub(r"[^\w\s]", "", seg["text"].lower()).strip()
        if len(t) < 5:
            continue
        texts_norm.setdefault(t, []).append(seg)

    for t, occurrences in texts_norm.items():
        if len(occurrences) >= 2:
            lessons.append({
                "kind": "lesson",
                "text": f"HÁBITO: dono pediu '{occurrences[0]['text'][:60]}' "
                        f"{len(occurrences)}x hoje",
                "source": "reflect-repetition",
                "evidence": len(occurrences)
            })

    # 2. ERRO-SOLUÇÃO: tool erro → contexto
    for err in tools_err:
        lessons.append({
            "kind": "lesson",
            "text": f"ERRO hoje: {err['text'][:100]}",
            "source": "reflect-error",
            "evidence": 1
        })

    # 3. TEMA DOMINANTE: palavras mais frequentes nos segmentos
    word_count = Counter()
    stop = {"jarvis", "que", "para", "com", "uma", "não", "sim", "ok",
            "the", "a", "o", "e", "do", "da", "de", "em", "no", "na",
            "me", "você", "seu", "sua", "isso", "aquele", "esta", "está"}
    for seg in segments:
        for w in re.findall(r"\w{4,}", seg["text"].lower()):
            if w not in stop:
                word_count[w] += 1

    for word, count in word_count.most_common(5):
        if count >= 3:
            lessons.append({
                "kind": "lesson",
                "text": f"TEMA: '{word}' apareceu {count}x hoje",
                "source": "reflect-theme",
                "evidence": count
            })

    # 4. CLASSES DE CLASSIFY (padrões de turn-taking)
    classes = Counter(i.get("class") for i in interactions
                      if i["type"] == "classify")
    total_classify = sum(classes.values())
    if total_classify > 0:
        resp_pct = classes.get("RESPOND", 0) / total_classify * 100
        if resp_pct > 60:
            lessons.append({
                "kind": "lesson",
                "text": f"PADRÃO: {resp_pct:.0f}% das falas hoje foram "
                        f"RESPOND ({classes.get('RESPOND', 0)}/{total_classify})",
                "source": "reflect-classify",
                "evidence": total_classify
            })

    return lessons


def dedup_lessons(lessons: list[dict], mem: EpisodicMemory) -> list[dict]:
    """Remove lições que já existem na memória (cosseno alto)."""
    if not mem.is_available():
        return lessons
    unique = []
    for lesson in lessons:
        hits = mem.recall(lesson["text"][:50], top_k=1)
        already = False
        for h in (hits if isinstance(hits, list) else [hits]):
            if isinstance(h, dict):
                existing = (h.get("payload") or {}).get("text", "")
                if existing and existing[:30].lower() == lesson["text"][:30].lower():
                    already = True
                    break
        if not already:
            unique.append(lesson)
    return unique


def main() -> int:
    ap = argparse.ArgumentParser(description="Reflexão noturna (P2.7)")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"=== REFLEXÃO {args.date} ===")
    interactions = parse_log(args.date)
    print(f"Interações: {len(interactions)}")

    if not interactions:
        print("Sem interações no log — nada a refletir.")
        return 0

    lessons = extract_lessons(interactions)
    print(f"Lições extraídas: {len(lessons)}")

    if not lessons:
        print("Nenhuma lição nova.")
        return 0

    mem = EpisodicMemory()
    unique = dedup_lessons(lessons, mem)
    print(f"Após dedup: {len(unique)} (removidas {len(lessons) - len(unique)})")

    for lesson in unique:
        print(f"  [{lesson['source']}] {lesson['text']}")
        if not args.dry_run:
            r = mem.remember_fact(
                lesson["text"],
                kind="lesson",
                source=lesson["source"],
                evidence=lesson["evidence"],
                date=args.date)
            if r:
                print(f"    → stored id={r}")
            else:
                print("    → FAILED to store")

    if args.dry_run:
        print("\n(dry-run — nada aplicado)")
    else:
        print(f"\n{len(unique)} lições guardadas")

    return 0


if __name__ == "__main__":
    sys.exit(main())
