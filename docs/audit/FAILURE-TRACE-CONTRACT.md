# FAILURE-TRACE-CONTRACT (Ciclo 5 — PHASE 9)

Toda falha de benchmark preserva diagnóstico sem reexecução:
- harness: trajectory_summary (tools+args+outputs 200ch) + criteria_met
  (incl. `stale_artifact:*`, `l9_world`) + error + turns/time/tokens.
- crash: runner captura traceback + prompt (sem segredos/env) em
  `/tmp/l9repo-trace-<pid>.log` (implementado em benchmarks/l9/run_l9.py;
  estender aos demais runners ao tocar).
- mundo: artifact inventory (ls do dir) + world-check output.
- modelo: provider metadata (bonsai :8080) + elapsed.
Proibido: segredos, env inteiro, dumps gigantes. Suficiência: L9-0..2
e write-0..2 foram diagnosticados SÓ do jsonl (attractor, fidelidade,
no-pivot) sem rerun — contrato ATENDIDO. Crash tardio é a exceção
(traceback ainda não capturado; OPEN).
