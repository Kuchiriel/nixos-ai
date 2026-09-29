#!/usr/bin/env python3
"""ab-prompt.sh — A/B de prompt com métrica HONESTA (bytes, não RC).

29/09: RC honesto e entrega real são coisas diferentes. Um A/B medido
só por RC leu "EN 1×0, PT 0×1" quando o EN entregou 0 bytes e o PT
entregou os 8 certos. Aqui a métrica primária é o **conteúdo
entregue**; o RC entra como coluna, não como veredito.

Uso:
  ./scripts/ab-prompt.sh <modelo> <tier|task> [--runs N]
Ex.: ./scripts/ab-prompt.sh bonsai extract-line --runs 2

Não altera o runtime: fixa o fixture, roda N vezes por variante com
semente/reset, e imprime uma tabela. Verdade do mundo: o verifier.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(os.environ.get("AB_BASE", "/tmp/opencode/ab"))


def build_fixture(root: Path) -> None:
    """Fixture de extração de linha (a task que discrimina)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.txt").write_text("alpha one\nbeta two\ngamma three\n")


def variants() -> list[tuple[str, str]]:
    """(nome, prompt). Hipótese central: pedir o CONTEÚDO explicitamente
    em EN fecha o gap do 'shape-only' (criar arquivo ≠ entregar)."""
    return [
        ("en-plain", "read data.txt and write its second line to out.txt"),
        ("en-ONLY", "read data.txt and write ONLY its second line to "
                    "out.txt (no headers, no extra lines, the file must "
                    "contain the text)"),
        ("en-then-verify", "read data.txt, then write ONLY its second line "
                           "to out.txt, then read out.txt back to confirm "
                           "it is non-empty"),
        ("pt-plain", "leia data.txt e escreva a segunda linha em out.txt"),
    ]


def run_once(model: str, prompt: str, root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    out = root / "out.txt"
    if out.exists():
        out.unlink()
    env = dict(os.environ)
    env["JARVIS_LLM_BASE_URL"] = "http://127.0.0.1:8080"
    env["JARVIS_LLM_MODEL"] = model
    env["JARVIS_PROMPT_PROFILE"] = "minimal"
    env["JARVIS_SAMPLING"] = "registry"
    t0 = time.monotonic()
    code = (
        "from jarvis.cli.dev import dev_once; "
        f"raise SystemExit(dev_once({prompt!r}, project_root={str(root)!r}, "
        "approve=True))"
    )
    # nix develop NESTADO nao resolve (cwd ephemeral) — o script ja roda
    # dentro do dev shell; invoca o mesmo interprete.
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, cwd=root, timeout=900)
    wall = round(time.monotonic() - t0, 1)
    content = out.read_text() if out.exists() else None
    return {
        "rc": proc.returncode,
        "wall_s": wall,
        "delivered": content is not None,
        "bytes": len(content.encode()) if content is not None else 0,
        "correct": content == "beta two\n" or content == "beta two",
        "content": (content or "")[:80],
    }


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "bonsai"
    runs = 2
    if "--runs" in sys.argv:
        runs = int(sys.argv[sys.argv.index("--runs") + 1])
    results = []
    for name, prompt in variants():
        for i in range(runs):
            r = run_once(model, prompt, BASE)
            r.update({"variant": name, "run": i + 1})
            results.append(r)
            flag = "OK " if r["correct"] else "FALHA"
            print(f"[{flag}] {name:<14} run{i+1} "
                  f"bytes={r['bytes']:<3} rc={r['rc']} "
                  f"wall={r['wall_s']}s | {r['content']!r}", flush=True)

    print("\n=== resumo ===")
    print(f"{'variant':<14}{'entregas':<10}{'bytes_med':<11}{'rc0':<6}{'wall'}")
    for name, _ in variants():
        rs = [r for r in results if r["variant"] == name]
        if not rs:
            continue
        ok = sum(r["correct"] for r in rs)
        med = sorted(r["bytes"] for r in rs)[len(rs) // 2]
        rc0 = sum(r["rc"] == 0 for r in rs)
        wall = round(sum(r["wall_s"] for r in rs) / len(rs), 1)
        print(f"{name:<14}{ok}/{len(rs):<8}{med:<11}{rc0}/{len(rs):<5}{wall}s")

    Path("/tmp/opencode/ab").mkdir(parents=True, exist_ok=True)
    Path("/tmp/opencode/ab/results.json").write_text(
        json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
