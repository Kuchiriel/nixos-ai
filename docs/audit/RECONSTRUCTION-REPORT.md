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

## Double-check do briefing (§0–§29, 26/09 pós-sessão)

Item por item do prompt gigante — o que foi cumprido, parcial ou gap:

- §0 fontes: AGENTS/HANDOFF-25-09/BUFFY(  grep kernel: nada a opor)/README
  lidos p/ diretiva conflitante — nenhuma; models.nix/services/flake
  verificados no que o kernel toca (routing/registryJson/endpoints).
  ADRs: 001/002 operacionais, 003 resolvida (F9), 004 operacional (F6).
- §1/§2/§3 forense+tabela+decisão ✓. §4 runtime ✓. §5 sessão ✓.
- §6 registry: metadados completos (handler/verify) + dispatch genérico ✓
  (MCP sem import de devtools).
- §7 disclosure estrutural ✓ (por capability; seleção por modelo = futuro).
- §8 assembler: 1 mecanismo ✓; JIT por referência leve = futuro (ainda
  despeja texto — honesto).
- §9 contratos versionados de Knowledge/Memory: GAP (só providers
  conceituais; próxima fronteira).
- §10 Qdrant (dedupe schema/payload/identity, crc32→sha256): GAP consciente
  (não estética sem contrato; refs híbrido+payload no RAG).
- §11 providers como recursos ✓ parcial (executor único; decisão ainda
  dispersa em callers legados).
- §12 completion ✓ (vocabulário; substratos preservados). §13 supervisor:
  fronteira + veredito ✓, flip F7b pendente.
- §14 dev thin parcial (composição+prompt migrados; loop fica).
- §15 personas ✓. §16 choke point ✓. §17 cadeia models.nix ✓ (teste novo).
- §18 ModelLifecycle formal: GAP (ensure_strong_llm cobre, sem autômato).
- §19 delete: desvio documentado (regra do dono > agressividade; archive).
- §20 matriz de testes parcial (unit+contrato+linter+e2e-via-suite ✓;
  integração runtime+llama/Qdrant como teste, não só probe = futuro).
- §21 modelo-agnóstico ✓ (3 matches só em plumbing).
- §22 Harbor: adapter+docs+trajetória ✓; run real pendente.
- §23 pesquisa: arXiv 4/4 ✓, openai harness ✓ (403, via Tavily),
  agents-api ✓, qdrant híbrido ✓ + payload ✓, harbor 3/3 ✓;
  agents-sdk-evolution 403 (só excerto), chatgpt-share 2× timeout (bridge),
  durable-execution/skills-externas = futuro.
- §24/§25/§26 método e blocos ✓. §27 checkpoints ✓✓✓. §28 checklist ✓
  honesto. §29 autonomia exercida; BLOCKED formal = Harbor real + F7b
  (condições de prova registradas).

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
