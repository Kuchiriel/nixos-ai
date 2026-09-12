# NIGHT SHIFT 2 — Convergence attack: relatório de saída (2026-09-12)

## 1. Caminho operacional canônico

`jarvis dev "tarefa"` (dev_once/dev_repl → _run_agent_loop próprio).
`jarvis agent` (Core Agent) = outro loop, outro contrato (API/headless).

## 2. Por que dois loops (evidência, não inferência)

| Boundary | `jarvis dev` | Core Agent |
|---|---|---|
| Entry point | CLI REPL/once, terminal humano | API programática, nightwatch, `jarvis agent` |
| LLM client | `_call_llm` direto + profiles | `LLMClient.chat_with_tools` + registry/routing |
| Tool registry | 21 inline (files/shell/browser/memory/nix) | fixo (read/write/str_replace/books) + MCP |
| Tool policy | Confirm.ask interativo por tool | allowlist + human_approve + jail |
| Observation | `_validated_output` + diff impresso | tool msgs + completion.py verdicts |
| Loop detector | core LoopDetector (repetição) | + verify-turns + identical-error STUCK + budget |
| Completion | terminava em texto (F1); promise-catcher agora | P0.2 evidence verdicts, STUCK/FAILED honestos |
| Audit | EDIT_HISTORY/undo, transcript JSON | EventBus, telemetry, AgentResult |
| Browser | tool `browser` (esta sessão) | AUSENTE |
| OS list | list_directory | AUSENTE (só read_file) |
| Books/RAG | AUSENTE | book_search/resume |

Causa: dev loop = shell de interação (spinners, prompts PTY,
auto-commit, sessão persistente, slash commands); core = motor
headless. UX-específico + linhagem REPL (Aider-like), não acidente
puro. Convergência correta: núcleo de execução compartilhado
(tools+validators+verdicts) com shells de interação separados.
NÃO apagar um loop; portar capacidades (browser→core,
verdicts→dev).

## 3. Convergência possível? Sim, parcial executada

- Discipline + heartbeat no choke point `_default_call_llm`.
- Evidence gate no Step 6 do harness; LoopDetector já ligado.
- Parse tolerante + JSON-grammar no patcher (abaixo).
- Scope `--projects` (produção fora do alvo).

## 4. Falha do baseline 7/8

T3 (pasta+3 arquivos): 0/5 determinístico. Modelo escreve nomes
como conteúdo em arquivo-no-lugar-da-pasta; mkdir negado; tarefa
ambígua sem nomes. Limite arquitetural, não estocástico.

## 5. F6: harness, não modelo (PROVADO)

Causa = approval: click exigia flag, modelo alucinava (A) ou
mendigava (B). Fix: Confirm.ask interativo no REPL → B2/B3 passam
(open→click→estado real). Qwen A/B: UNVERIFIED (CPU não serve
prompt gigante; GPU adiada com motivo).

## 6. Browser observation suficiente? Sim, com aprovação

open livre + click/fill aprovados + estado DOM retornado.
Cadeia E completa e verificada por servidor independente.

## 7. OS action→observation→verification? Sim, com lacunas

Cadeia D completa quando policy permite. Lacunas: sem mkdir tool,
core sem list_directory, dev sem verdicts.

## 8. Taxa real (bonsai, prompts humanos, driver PTY)

Suite 12 tasks: **11/12**, mean 2.2 turns, 3.8s, p95 5.7s,
false_done 1 (T3). Core Agent sozinho: alucina path (UNVERIFIED
honesto) / usa book_search onde dev usa shell — comportamentos
divergentes medidos.

## 9. Bugs novos → corrigidos (todos com regressão)

F1 promise-catcher; F2 write_file dir+pais; F3 mensagem;
F4 approval-PTX; F5 mkdir-allowlist (mitigado em descrição);
F6 approval-browser; parse cercas/EOF/bare----; scope produção;
JSON-patch-grammar; upload PUT; release permissions.

## 10. Não corrigido / próximo experimento

Heartbeat/timeout-hard no harness; unificar patcher no Agent;
Qwen-GPU A/B; warmup router (análise pronta, sem execução);
B3-fill fino; WebUI via Playwright; Roo-vs-JARVIS.

## 11. GOVERNANÇA (nova regra da missão)

`pytest green` ≠ funcional. Camadas: UNIT / INTEGRATION / AGENT /
USER-FAITHFUL / WORLD-STATE. Suite em scripts/ux-*.py + lab em
scripts/ux-lab-site/. Transcripts em /tmp/ux-*.json.
