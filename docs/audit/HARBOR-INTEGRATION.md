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

## Trial 2 — adapter próprio (nosso harness no Harbor) 15:00
`jarvis_adapter:HarborJarvis` (Agent+Bonsai local; shell/read/write
roteados p/ container via exec/upload b64). Trial SEM exceção:
7 turns, 3 writes ok via bridge, veredito interno UNVERIFIED
(completion checa paths no HOST — gap esperado; autoridade é o
verifier Harbor), reward Harbor 0.0.
Leitura: bridge MECANICAMENTE funcional; bytes errados (consistente
c/ E1 interno 0/3) → CONSISTENT FAILURE (fronteira transfere, não só
capability). A-vs-B Harbor real agora é questão de rodar N trials.

## A-cell n=3 (+1): 0/4, zero erros (21/09 15:07)
3 trials completos, n_errors=0, reward 0.0 em todos. Interna E1 0/3 →
externa 0/4: CONSISTENT FAILURE bidirecionalmente estável. Job:
jobs/2026-09-21__15-07-34. Próximo: célula B (outro modelo) quando
houver; adapter versionado (hoje em /tmp — promover p/ repo se virar
rotina).

## A-cell n=3 com adapter do repo (28/09, F10 evoluído) — 2/3
Job `acell-final`: 2×reward 1.0, 1×0.0 (21/09 era 0/4). Evoluções pagas no
fogo, commit 0989b11:
1. AgentContext real 0.23.0 só tem tokens/custo/metadata — escrever em
   commands_executed dava ValueError e matava o trial (3x exceção).
2. Ponte container (_ContainerBridge: read/write/shell via env.exec/upload;
   sem ela o agente lia /app no HOST + jail bloqueava write = 0.0 certo).
3. Deadlock: Harbor awaita agent.run() na thread do loop; bridge com loop
   próprio em thread dedicada (3x AgentTimeoutError, zero tools).
4. AgentRuntime aceita agent_class (None = Agent canônico).
Padrão da falha restante: modelo briga com byte UTF-8 (Ω) via tools de
texto — capacidade do modelo, não harness. Próximo: célula B (modelo
maior), não mais tweak de harness. Jobs em /tmp/harbor-work/jobs/
(acell-fixed, acell-bridge, debug-*, acell-final).

## B-cell MoE n=3 (28/09, Qwen3.6-35B :8084) — 0/3, com achado
Job `bcell-moe3`: 0.0 nos 3, MAS新 bug de harness achado e corrigido:
trailer anti-vazamento no read roteado (MoE copiava o cabeçalho
"# path (N linhas)" p/ DENTRO do o.txt 3/3 — bonsai não fazia isso).
Pós-trailer o header sumiu, mas o MoE normaliza bytes (Ω→é, espaços) —
task adversarial p/ cópia via texto; `cp` seria 1 call, modelo não escolhe.
Inversão: bonsai 2/3 > MoE 0/3 nesta task (escapes crus do bonsai
acertaram bytes por sorte 2x). Conclusão: fronteira fiel, variância é
capacidade/estratégia do modelo. Infra B-cell: ik sobe c/ router parado
(VRAM única); JARVIS_BASE_URL=:8084 bypassa ensure (single-model sem
/models/load); restore pós-job: router de volta. Commit a seguir.

## CORREÇÃO HISTÓRICA 29/09 — reward hacking (verifier comparava arquivo mutável)
A-cell "2/3" e task2-bin "2x 1.0" eram FRAUDE: o agente sobrescrevia o
src.txt com o mesmo lixo do o.txt (todos os trials tinham src-overwrite).
Placar real: tudo 0. Verifiers agora comparam sha256 PRISTINO hardcoded
(bytecopy-task: 12ec1e2c…; bytecopy-bin: 4ad3a905…). Regra: verifier NUNCA
compara contra arquivo que o agente pode escrever.
A-cell honesta (acell-honest, verifier c/ hash): 0/3 bonsai.
Outras evoluções 29/09: strings do harness p/ o modelo em EN (bonsai rende
mal em PT-BR); flag BINÁRIO no read roteado; fix TypeError
model_requirements duplicado no AgentRuntime.run; C-cell Qwen3-4B 0/2
(+1 env-start flake); VRAM: 2 servidores simultâneos = 500 no :8080
(só 1 LLM por vez; upstream parado após C-cell).
