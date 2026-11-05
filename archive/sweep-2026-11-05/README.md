# Sweep 05/11/2026 — código morto e duplicado

Varredura do `nixos-ai` (05/11): 12 arquivos sem consumidor real foram
movidos para cá. **Nenhum foi apagado** — `git mv` preserva o histórico
(`git log --follow` continua funcionando).

## Como cada um foi julgado morto

A verificação foi por **import real**, não por menção em texto: cada
candidato foi procurado por `from X import` / `import X` e por uso como
subprocesso. Só o que teve **zero** consumidor saiu. Dois falsos positivos
do reconhecimento inicial foram **mantidos**:

| Mantido | Por quê |
|---|---|
| `jarvis/core/classify.py` | importado por `scripts/jarvis-cli.sh` (`classify_file`, `get_security_summary`) |
| `jarvis/core/websearch.py` **e** `scripts/websearch.py` | o módulo é importado pelo `mcp_server.py`/`cli/dev.py`; o script é chamado como subprocesso pelo `duplex-voice.py` — a duplicação entre os dois é uma **consolidação futura**, não código morto |

## O que foi arquivado

### Nix

| Arquivo | Motivo |
|---|---|
| `modules/services/vision-siglip.nix` | nunca importado por nenhum módulo (grep por `vision-siglip` = 0 fora do próprio arquivo) |

### Scripts

| Arquivo | Motivo |
|---|---|
| `scripts/bench-final.py` | só citado nos índices; nenhum chamador |
| `scripts/fix_refs.py` | só citado no TOOLS-INDEX; nenhum chamador |
| `scripts/read_chatgpt.py` | duplicata de `jarvis/core/multi_ai_reader.py` (`read_chatgpt_conversation`), que é o que os testes usam |
| `scripts/charger-watch.sh` | duplicata do script inline em `modules/services/charger-watch.nix` (é esse que a unit `charger-watch.service` executa) |
| `rebuild-lab.sh` (raiz) | duplicata do harness Linux/Wine em `backtest/` **e** usava `git add -A` (a regra da casa é stage explícito) |

### Python (nightwatch / jarvis)

| Arquivo | Motivo |
|---|---|
| `jarvis/core/audiobook_ui.py` (+ `tests/test_audiobook_ui.py`) | a UI não tinha consumidor; o teste era órfão (o módulo já não existia no código) |
| `jarvis/core/github_mcp.py` | GitHub MCP próprio, não registrado em nenhum servidor MCP; o acesso a GitHub é via `gh` |
| `nightwatch/learning.py` | só citado em docs de 2026; o aprendizado real vive no `jarvis/` (memórias/RAG) |
| `nightwatch/goal_loop.py` | superseded pelo `jarvis/core/mission/` + `task_queue.py` |
| `nightwatch/three_agent.py` | superseded pelo `nightwatch/harness.py` (o comentário que o citava no harness foi ajustado) |

## Como reviver

```bash
git mv archive/sweep-2026-11-05/<caminho> <caminho-original>
```
