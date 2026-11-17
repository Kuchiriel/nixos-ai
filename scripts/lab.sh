#!/bin/bash
# lab.sh — PONTO DE ENTRADA UNICO do laboratorio A/B (dungeon x modelos).
#
# POR QUE EXISTE: o laboratorio tinha 6 arquivos, 4 servicos, 3 armadilhas de
# shell e um historico de 537 medicoes invalidas. Um modelo novo (ou o dono
# com pressa) nao deveria precisar reconstruir esse mapa a cada sessao: este
# script e' o mapa executavel. Se algo aqui mentir, `lab.sh doctor` acusa.
#
# Uso:
#   lab.sh status [--json]   estado: loop, nivel, GPU, ultimas medicoes, matriz
#   lab.sh doctor            RE-VALIDA o instrumento (checkers nos dois sentidos)
#   lab.sh run [L1|L2|L3]    roda agora (nivel opcional)
#   lab.sh level L1|L2|L3    forca o nivel do proximo ciclo
#   lab.sh arm bonsai|mtp|api  roda SO um braco
#   lab.sh pause|resume|stop|restart
#   lab.sh logs [N]          ultimas N linhas do log do loop
#   lab.sh gpu               VRAM, quem ocupa, quem esta no ar
#   lab.sh checkers          tabela dos 3 checkers + hashes
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$HOME/.local/state/jarvis/nightwatch"
CTL="$STATE/ab_loop.control"
PIDF="$STATE/ab_loop.pid"
RES="$HOME/logs/ab_loop/results.jsonl"
LOG="$HOME/logs/ab_loop/ab_loop.log"
SWAP="$REPO/scripts/llm-swap.sh"

alive() {
    local pid
    pid=$(cat "$PIDF" 2>/dev/null) || return 1
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

ctl() { printf '%s' "$1" > "$CTL"; }

status_json() {
    python3 - "$RES" "$LOG" "$PIDF" "$CTL" << 'PY'
import json, os, sys, datetime
res, log, pidf, ctl = sys.argv[1:5]
rows = []
try:
    for l in open(res, encoding="utf-8"):
        l = l.strip()
        if l:
            try: rows.append(json.loads(l))
            except Exception: pass
except FileNotFoundError:
    pass

def veredito(r):
    if r.get("erro"): return "erro"
    c = str(r.get("checker") or "")
    if not c: return "erro"
    import re
    m = re.search(r"(\d+) failed", c)
    if m: return "pass" if int(m.group(1)) == 0 else "fail"
    return "pass" if "passed" in c else "erro"

v3 = [r for r in rows if r.get("ck") == "v3"]
matriz, modelos = {}, {}
for r in v3:
    m, n, v = r.get("modelo", "?"), r.get("nivel", "L3"), veredito(r)
    matriz.setdefault(m, {}).setdefault(n, {"pass": 0, "fail": 0, "erro": 0, "ciclos": 0})
    c = matriz[m][n]; c["ciclos"] += 1; c[v] += 1
    d = modelos.setdefault(m, {"modelo": m, "ciclos": 0, "pass": 0, "fail": 0, "erro": 0})
    d["ciclos"] += 1; d[v] += 1

pid = None
try: pid = int(open(pidf).read().strip())
except Exception: pass
vivo = False
if pid:
    try: os.kill(pid, 0); vivo = True
    except Exception: vivo = False

linhas = []
try: linhas = [l for l in open(log, encoding="utf-8").read().splitlines() if l][-60:]
except FileNotFoundError: pass
ciclo = nivel = atual = None
for l in reversed(linhas):
    import re
    m = re.search(r"CICLO\s+(\d+)(?:\s*\(nivel\s+(\w+)\))?", l)
    if m and ciclo is None:
        ciclo = int(m.group(1)); nivel = m.group(2) or nivel
        continue
    m = re.search(r"A/B (?:para )?(\S+)(?:\s+@\s+(\w+))?", l)
    if m and atual is None:
        atual = m.group(1); nivel = m.group(2) or nivel

try: controle = open(ctl).read().strip() or "run"
except Exception: controle = "run"

out = {
    "loop": {"pid": pid, "alive": vivo, "cycle": ciclo, "current": atual,
             "nivel": nivel, "control": controle},
    "medicoes_v3": len(v3),
    "legado_v2": len(rows) - len(v3),
    "modelos": sorted(modelos.values(), key=lambda x: x["modelo"]),
    "matriz": matriz,
    "ultimas": [{**{k: r.get(k) for k in ("modelo", "nivel", "dur", "patch_bytes", "erro", "checker", "motivo", "ts")},
                 "veredito": veredito(r)} for r in v3[-8:]][::-1],
}
print(json.dumps(out, ensure_ascii=False, indent=1))
PY
}

status() {
    if [ "${1:-}" = "--json" ]; then status_json; return; fi
    echo "── laboratorio A/B ─────────────────────────────────────────"
    local pid
    pid=$(cat "$PIDF" 2>/dev/null)
    if alive; then echo "loop: VIVO (pid $pid) · controle=$(cat "$CTL" 2>/dev/null || echo run)"; else echo "loop: PARADO (controle=$(cat "$CTL" 2>/dev/null || echo run))"; fi
    echo
    echo "── GPU ─────────────────────────────────────────────────────"
    bash "$SWAP" status 2>/dev/null | sed 's/^/  /'
    echo
    echo "── matriz (ck=v3) ─────────────────────────────────────────"
    status_json | python3 -c '
import json, sys
d = json.load(sys.stdin)
ms = d["modelos"]
if not ms:
    print("  sem medicoes v3 ainda")
else:
    niveis = ["L1", "L2", "L3"]
    print("  modelo    " + "  ".join(n.rjust(7) for n in niveis) + "   total")
    for m in ms:
        cels = []
        for n in niveis:
            c = d["matriz"].get(m["modelo"], {}).get(n)
            cels.append((str(c["pass"]) + "/" + str(c["ciclos"])).rjust(7) if c else "      .")
        print("  " + m["modelo"].ljust(9) + " " + "  ".join(cels) + "   " + str(m["pass"]) + "/" + str(m["ciclos"]))
    print()
    print("  medicoes v3: " + str(d["medicoes_v3"]) + " . legado v2 (checker invalido): " + str(d["legado_v2"]))
    print()
    print("  ultimas:")
    for r in d["ultimas"][:6]:
        ic = {"pass": "OK  ", "fail": "FAIL", "erro": "ERRO"}[r["veredito"]]
        dur = r.get("dur") or 0
        pb = r.get("patch_bytes") or 0
        ck = str(r.get("checker") or r.get("erro") or "")[:44]
        # (17/11, coord-naming) o MOTIVO: por que o ciclo nao passou.
        # Sem ele, "FAIL" e "ERRO" sao a mesma coisa no olho: nao se sabe
        # se o modelo errou (checker), se o revisor abortou (review) ou se
        # a maquina/API falhou (infra). Sem a separacao, o A/B mede a
        # maquina em vez do modelo.
        mot = str(r.get("motivo") or "-")
        print("    " + ic + " " + str(r["modelo"]).ljust(8) + " " + str(r.get("nivel") or "L3").ljust(3)
              + " " + str(dur).rjust(4) + "s patch=" + str(pb).rjust(5) + "B  "
              + "motivo=" + mot.ljust(13) + ck)
'
}

doctor() {
    echo "── doctor: o instrumento ainda e' valido? ─────────────────"
    echo "1) checkers contra solucao de referencia (precisa 5/5 em todos)"
    if timeout 900 python3 "$REPO/scripts/prova_checkers.py" 2>&1 | tail -6; then :; fi
    echo
    echo "2) estado do loop"
    alive && echo "   OK loop vivo (pid $(cat "$PIDF"))" || echo "   AVISO loop parado"
    echo
    echo "3) integridade das medicoes novas (ck=v3)"
    status_json | python3 -c '
import json, sys
d = json.load(sys.stdin)
n = d["medicoes_v3"]
print(f"   {n} medicoes v3")
if n == 0: print("   AVISO: nenhuma medicao v3 — o loop ainda nao mediu com o checker novo")
soma = sum(m["ciclos"] for m in d["modelos"])
if soma and abs(soma - n) > 0: print("   ERRO: contagem inconsistente")
'
    echo
    echo "4) hub respondendo"
    local tok; tok=$(cat "$HOME/.config/opencode/agent-hub.token" 2>/dev/null)
    if curl -s -m 5 -o /dev/null -w "%{http_code}" -H "x-agent-hub-token: $tok" http://127.0.0.1:8091/api/ab/live | grep -q 200; then
        echo "   OK /api/ab/live 200"
    else
        echo "   AVISO hub nao respondeu (systemctl --user restart agent-hub.service)"
    fi
}

case "${1:-status}" in
    status) shift || true; status "${1:-}" ;;
    doctor) doctor ;;
    run)
        nivel="${2:-}"
        if [ "$nivel" = "L1" ] || [ "$nivel" = "L2" ] || [ "$nivel" = "L3" ]; then ctl "level:$nivel"; else ctl now; fi
        echo "pedido enviado ao loop (controle=$(cat "$CTL"))"
        ;;
    level)
        case "${2:-}" in
            L1|L2|L3) ctl "level:$2"; echo "proximo ciclo em $2" ;;
            *) echo "uso: lab.sh level L1|L2|L3" >&2; exit 2 ;;
        esac ;;
    arm)
        case "${2:-}" in
            bonsai|mtp|api) ctl "run:$2"; echo "rodando so $2 (proximo ciclo)" ;;
            *) echo "uso: lab.sh arm bonsai|mtp|api" >&2; exit 2 ;;
        esac ;;
    pause)  ctl pause;  echo "pausado" ;;
    resume) ctl run;    echo "retomado" ;;
    stop)
        ctl stop
        if alive; then kill -TERM "$(cat "$PIDF")" 2>/dev/null; fi
        sleep 2
        alive && echo "ainda vivo — use: kill -9 $(cat "$PIDF")" || echo "loop parado"
        bash "$SWAP" release >/dev/null 2>&1
        ;;
    restart) bash "$REPO/scripts/restart-ab.sh" ;;
    logs)    tail -n "${2:-30}" "$LOG" ;;
    gpu)     bash "$SWAP" status ;;
    checkers)
        for f in dungeon-checker.py dungeon-checker-l1.py dungeon-checker-l2.py; do
            printf "%-26s %s  %s\n" "$f" "$(sha256sum "$REPO/scripts/$f" | cut -c1-12)" "$(grep -m1 '^L[0-9] =' "$REPO/scripts/$f" || echo '')"
        done
        echo "(o veredito da lane e' copiado destes arquivos e travado em 444)"
        ;;
    -h|--help|help)
        sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
    *) echo "comando desconhecido: $1 (use lab.sh help)" >&2; exit 2 ;;
esac
