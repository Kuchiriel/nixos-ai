#!/usr/bin/env python3
"""check-queue-handoff.py — os ponteiros da fila para o vault existem?

POR QUE (10/11, sweep-2026-11)
O topo da fila aponta para a nota do vault como "este é o original", e o
protocolo de checkpoint escreve a fila ANTES do vault (passo 1 e passo 4).
Se o passo do vault falha, a fila fica com um ponteiro para o nada: medido
10/11, o topo apontava para HANDOFF-2026-11-10-prova-do-wakeword.md e o
arquivo não existia em lugar nenhum do disco.

O Qdrant já aceitou um write com HTTP 200 e não persistiu, e quem confiou
no status perdeu 6 pontos. Mesma regra aqui: o ponteiro só vale se o
arquivo existe.

O QUE ESTE SCRIPT FAZ
  1. lê a fila (padrão ~/projects/AGENTS-QUEUE.md);
  2. extrai todo ponteiro `vault `HANDOFF-...md``;
  3. confere se o arquivo existe no vault;
  4. sai != 0 se houver ponteiro quebrado (com --warn, sai 0 e só avisa).

USO
    python3 scripts/check-queue-handoff.py
    python3 scripts/check-queue-handoff.py --queue ~/projects/AGENTS-QUEUE.md
    python3 scripts/check-queue-handoff.py --warn      # só avisa, não falha

EXEMPLO
    $ python3 scripts/check-queue-handoff.py
    fila: 24 ponteiro(s) | quebrados: 1
    [quebrado] HANDOFF-2026-11-10-prova-do-wakeword.md
"""
import argparse
import os
import re
import sys
from pathlib import Path

DEFAULT_QUEUE = Path.home() / "projects" / "AGENTS-QUEUE.md"
DEFAULT_VAULT = Path.home() / ".local" / "state" / "jarvis" / "vault"
PTR = re.compile(r"vault\s+`([^`]+\.md)`")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=str(DEFAULT_QUEUE))
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    ap.add_argument("--warn", action="store_true",
                    help="avisa sem sair com erro")
    args = ap.parse_args()

    q = Path(args.queue)
    if not q.is_file():
        print(f"fila nao encontrada: {q}", file=sys.stderr)
        return 2
    vault = Path(args.vault)
    text = q.read_text(errors="ignore")
    ptrs = PTR.findall(text)
    # o mesmo ponteiro pode aparecer repetido (a fila guarda o histórico)
    uniq = sorted(set(ptrs))
    broken = [p for p in uniq if not (vault / p).is_file()]
    print(f"fila: {len(uniq)} ponteiro(s) unico(s) | vault: {vault} | "
          f"quebrados: {len(broken)}")
    for p in broken:
        print(f"  [quebrado] {p}")
    # arquivos do vault que a fila nunca menciona (o inverso do problema)
    if vault.is_dir():
        orphans = sorted(p.name for p in vault.glob("HANDOFF-*.md")
                         if p.name not in uniq)
        if orphans:
            print(f"  [órfãos] {len(orphans)} nota(s) no vault sem ponteiro "
                  f"na fila: {', '.join(orphans[:5])}"
                  f"{'...' if len(orphans) > 5 else ''}")
    return 0 if (not broken or args.warn) else 1


if __name__ == "__main__":
    sys.exit(main())
