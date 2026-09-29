# Harbor e harness (CARREGUE SÓ SE O GATILHO CASAR)

Gatilhos: harbor, calibração externa, A-cell, B-cell, trial, verifier, adapter.

## O que é
Calibração externa do AgentRuntime via Harbor 0.23.0 (venv isolada em
`/tmp/harbor-env`, bin `harbor`). Task própria `myorg/bytecopy-task`
(bytecopy p/ /app/o.txt, verifier pytest). Adapter F10 no repo:
`modules/ai/jarvis/src/jarvis/runtime/harbor_agent.py`
(`JarvisHarborAgent`, `SUPPORTS_ATIF`, trajetória ATIF em `trajectory.json`).

## Rodar (ordem exata)
```bash
source /tmp/harbor-env/ldenv.sh   # libstdc++ nix p/ docker
export PYTHONPATH=$PWD/modules/ai/jarvis/src JARVIS_STATE_DIR=/tmp/harbor-work/jarvis-state
# A-cell (bonsai via router :8080 — router precisa estar no ar):
sg docker -c "/tmp/harbor-env/bin/harbor job start --config /tmp/harbor-work/job-acell.json --job-name <nome>"
# B-cell (MoE: PARA o router antes — VRAM única — e usa URL direta):
sudo systemctl stop llama-cpp-server && sudo systemctl start llama-cpp-ik
export JARVIS_BASE_URL=http://127.0.0.1:8084
sg docker -c "/tmp/harbor-env/bin/harbor job start --config /tmp/harbor-work/job-acell.json --job-name <nome>"
sudo systemctl stop llama-cpp-ik && sudo systemctl start llama-cpp-server  # restore
```
Configs de job: `/tmp/harbor-work/job-{acell,one}.json` (n=3 / n=1).
Evidência: `/tmp/harbor-work/jobs/<nome>/` (result.json, trial.log,
`bytecopy-task__*/agent/trajectory.json`).

## Regras pagas (não redescobrir)
- AgentContext real 0.23.0 só tem tokens/custo/metadata — veredito no
  `metadata`; UNVERIFIED nunca levanta (verifier decide).
- Tools roteadas p/ o container (`_ContainerBridge` via `env.exec/upload`);
  sem isso o agente opera no HOST = 0.0 certo.
- Bridge com loop próprio em thread dedicada (Harbor awaita `agent.run()`
  na thread do loop; bloquear nela = deadlock → `AgentTimeoutError`).
- Servidor single-model (:8084) não tem `/models/load` — `JARVIS_BASE_URL`
  bypassa o ensure; `JARVIS_MODEL_REQUIREMENTS` (tier) só vale no router.
- Modelo maior ≠ melhor: MoE 0/3 vs bonsai 2/3 no bytecopy (header leak +
  normalização de bytes). Atribuir antes de tunar.
- Nunca adaptar o runtime p/ passar numa task (otimizar o instrumento).

## Placar e história
- Placar: `docs/harbor/INDEX.md`. Log de auditoria: `docs/audit/HARBOR-INTEGRATION.md`.
- Testes: `modules/ai/jarvis/tests/test_harbor_adapter.py` (mockados, sem LLM).
