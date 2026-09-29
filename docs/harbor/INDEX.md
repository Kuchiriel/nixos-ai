# Harbor — calibração externa do harness (índice)

> Entry point p/ "teste harbor" / "evolução de harness". Detalhe de método
> em `.agents/harbor-e-harness.md` (gatilhos: harbor, calibração, trial).

## Placar

| Data | Célula | Modelo | Resultado |
|---|---|---|---|
| 21/09 | A (adapter /tmp) | bonsai | 0/4 |
| 28/09 | A (adapter repo + ponte) | bonsai | ~~2/3~~ → **0/3 honesto** (reward hacking: src sobrescrito; verifiers agora usam sha256 pristino) |
| 28/09 | B (direta :8084) | MoE Qwen3.6-35B | 0/3 (header leak + normalização bytes) |
| 29/09 | C (router :8083) | Qwen3-4B fast | 0/2 (escape-fighting; +1 env flake) |
| 29/09 | task2-bin (binário 0x00-0xFF) | bonsai | 0/4 (sem `cp` não há cópia; flag BINÁRIO adicionada) |
| 29/09 | X-cell (template xLAM obtido) | xLAM-2-8B | incompatível: sem template 400 (parser); com template 500 (output fora do peg-native). Precisa dialeto nativo (formato fc-r + parser de arrays), não tweak. |
| 29/09 | D-cell (byte + bin) | Phi-4-mini-instruct | 0/4 (text-fight, src-overwrite; diag 0.0%) |
| 29/09 | E-cell (Groq, mesmo harness) | gpt-oss-120b | 0/1 (relative-path drift: usa `src.txt`, nunca `/app`; bytes) |
| 29/09 | **F-cell bash-first (tese mini-SWE-agent)** | bonsai | **4/4** (byte+bin; cerca ```bash→shell, chaining liberado no container). Mesmo modelo: 0/25+ → 4/4. |

## Estratégia por modelo (`scripts/grade-harbor.py`)

Só o MoE descobriu `cp` (escreveu `copy.sh`, nunca executou → `cp-written-only`).
Bonsai/fast/Phi: text-fight, src-overwrite, prosa-only. Nenhum executou `cp`.

## Arquivos

| O quê | Onde |
|---|---|
| Adapter F10 | `modules/ai/jarvis/src/jarvis/runtime/harbor_agent.py` |
| `agent_class` no runtime | `modules/ai/jarvis/src/jarvis/runtime/agent_runtime.py` |
| Testes (mock, sem LLM) | `modules/ai/jarvis/tests/test_harbor_adapter.py` |
| Log de auditoria | `docs/audit/HARBOR-INTEGRATION.md` |
| Guia do agente | `.agents/harbor-e-harness.md` |
| Matriz modelo×harness | `docs/benchmarks/MODEL-HARNESS-MATRIX.md` |
| venv Harbor 0.23.0 | `/tmp/harbor-env` (fora do repo; some no reboot — recriar) |
| Tasks + jobs + evidência | `/tmp/harbor-work` (fora do repo) |

## Comandos (resumo; exato em `.agents/harbor-e-harness.md`)

```bash
nix develop --command python3 -m pytest modules/ai/jarvis/tests/test_harbor_adapter.py -q
source /tmp/harbor-env/ldenv.sh
sg docker -c "/tmp/harbor-env/bin/harbor job start --config /tmp/harbor-work/job-acell.json --job-name <nome>"
```
