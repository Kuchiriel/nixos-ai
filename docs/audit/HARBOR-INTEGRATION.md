# HARBOR INTEGRATION (21/09 — primeira calibração externa real)

Infra: Harbor 0.23.0 em /tmp/harbor-env (venv isolada); docker via
`sg docker` (usermod aplicado; declarativo em configuration.nix +
rebuild); libstdc++ via LD_LIBRARY_PATH (nix gcc).
Task própria: `myorg/bytecopy-task` (E1-shape: /app/src.txt 37 bytes
tricky → /app/o.txt, verifier pytest cmp) em /tmp/harbor-work.
Job: terminus-2 + `openai/bonsai` + api_base :8080/v1 + dummy key.

Trial 1: reward 0.0. Trajetória (3 steps): Bonsai emitiu Analysis/Plan
em PROSA, zero batches JSON `{"commands":[...]}` → harness não executou
nada → verifier falhou. Classe: INTEGRATION (protocolo terminus-JSON
vs prosa Bonsai), NÃO capacidade.
opencode-agent: BLOCKED (precisa model=provider/name + auth no container).
Adapter próprio (BaseAgent.run(instruction, environment, context)):
interface mapeada (`harbor/agents/nop.py`); requer bridge exec+paths
container ↔ nosso Agent (P1 próximo). Células C/D seguem NOT INTEGRATED;
A-vs-B Harbor real pendente do adapter.
Evidência: /tmp/harbor-work/jobs/2026-09-21__14-45-19/ (trajectory.json,
trial.log, verifier/).
