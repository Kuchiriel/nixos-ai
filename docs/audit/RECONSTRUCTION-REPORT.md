# RECONSTRUCTION REPORT — Kernel F1–F11 (26/09/2026)

> Commits `e23840e..21e6a01` sobre `586ec31`. Executado em 1 sessão, sem
> parar o que funciona (REPL, MCP, nightwatch intactos e operantes).

## O que convergiu (evidência)

| Dimensão | Antes | Depois | Prova |
|---|---|---|---|
| Tool schemas | 4 dialetos | 1 emissão + alias declarado | silent vazio (`dialect_report`), MCP `str_replace` ressuscitado (estava morto) |
| Busca | 4 fachadas, 2 executores | 1 executor (HybridSearch) | teste estrutural+fake |
| Vereditos | 4 palavras, 3 semânticas | 5 palavras, 1 contrato | linter trava vocabulário + Task.verdict |
| Modelo | seleção ×1 real + `route()` morta | 1 funil + morta deprecada | callers travados |
| Personas | matriz c/ dialeto+fantasmas, dual-identity no /mode | matriz canônica, 1 identidade | linter matriz⊆registry |
| Contexto | 2 montagens inline | 1 mecanismo (builders+Assembler) | golden byte-idêntico |
| Composição | 5 `Agent()` espalhados | 1 runtime (+testes) | linter zero-fora |
| Sessão | dicts/env/CLI state | `AgentSession` serializável | roundtrip JSON |
| Supervisor | loop paralelo sem fronteira | fronteira travada (não importa Agent) | linter |
| Calibração | — | adapter Harbor + 2 probes bonsai | trajectory.json |

## O que NÃO convergiu (declarado, não escondido)

- **Loop do dev REPL** ainda próprio (thin total = reescrever o uso diário;
  pede dono acordado + bateria viva). Contador travado em 3.
- **Nightwatch→`runtime.run`** (F7b): substrato patch≠tool-loop; flip exige
  prova em bateria real. Supervisor opera intacto sob contratos.
- **`check_completion` no nightwatch**: forçar seria convergência falsa
  (message-based vs commit-based); contrato = vocabulário + gates.
- **Harbor real**: adapter pronto, run (binário+dataset+docker) = job de
  máquina idle (comando na MATRIX §11).
- **Gap answer-vs-action** (Probe B): completion exige tool-evidence mesmo
  p/ task-resposta — questão aberta, NÃO afrouxar sem A/B (vacuous-pass).

## Bugs vivos encontrados no caminho

1. `jarvis_str_replace` via MCP 100% morto (KeyError) — ressuscitado (F2).
2. `_devtools_semantic_search` importado 0× usado (F8, anotado).
3. `/persona select` não rebuilda prompt (F9, anotado).

## Critério de conclusão (§28) — estado

[x] runtime único existe · [x] MCP sem lógica própria (transporte) ·
[x] 1 registry · [x] 1 assembler (mecanismo) · [x] 1 completion (vocabulário) ·
[x] 1 choke point · [x] contratos memory/knowledge (providers) ·
[x] systemd nos pesados (pré-existente, verificado) · [x] sessão serializável ·
[x] recovery no runtime (herdado do Agent) · [x] progressive-disclosure (estrutura;
pleno = F2+) · [x] modelos trocáveis sem tocar runtime ·
[x] bonsai+forte+CLI+MCP+nightwatch funcionando · [x] testes da arquitetura nova ·
[~] código morto removido (deprecado+anotado, não apagado — regra do dono) ·
[x] docs reconciliadas (ADR-005, plano, forense, este report) ·
[ ] CLI sem loop próprio (parcial: composição migrada, loop REPL fica) ·
[ ] Nightwatch sem loop próprio (fronteira travada, flip F7b pendente) ·
[ ] Harbor (adapter pronto, run pendente) · [ ] Bonsai otimizado (probes iniciais).
