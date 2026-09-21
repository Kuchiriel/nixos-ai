# CAPABILITY MATRIX A-Z (Ciclo 4 — status + dependências)

Legenda: ✅ GRADUATED · 🔶 PARTIAL/VERIFIED · 🔴 MODEL-LIMITED ·
🛠 HARNESS-LIMITED · ❓ UNVERIFIED.

| ID | Capability | Status | Atribuição | Depende de |
|---|---|---|---|---|
| A | filesystem discovery | 🔶 | modelo acha c/ list; Ga mostra palpite sem busca | I |
| B | filesystem mutation | 🔶 | write funciona; approval jail enforced | I,X |
| C | file reading | ✅ | reads paralelos ok; Gb grounded | I |
| D | code generation | 🔴 | repr-hábito em loop (probe ok) | H,X |
| E | shell execution | ✅ | shlex+killpg+allowlist; testado | I |
| F | debugging | 🔶 | validator hints; recovery parcial | A,E,X |
| G | JSON/schema | 🔴 | aspas/simplessome; mold 0/63 | X |
| H | multi-step | 🔶 | chain 3-8 turns ok; L9 alvo | I,X |
| I | tool selection | 🛠 | entropia→disclosure (E2 9/9) | — |
| J | tool sequencing | 🔶 | loops funcionam; STUCK honesto | I |
| K | RAG retrieval | ✅ | P/R/NDCG + hit 11/11 C2 | — |
| L | RAG grounding | ✅ | chunk→ação 5/5 (R1) | K,X |
| M | episodic recall | 🔶 | recall funciona; seleção confusa | I |
| N | lesson retrieval | ✅ | lessons() + supersede + idade | — |
| O | lesson application | 🛠 | value-free 3/3; c/ números 1/5 | N |
| P | self-knowledge | 🔶 | só c/ leitura (Gb 2/3; Ga 0/3) | C |
| Q | Git knowledge | 🔶 | E2-only ok; c/ menu falha | I |
| R | Vault knowledge | 🔶 | idem Q; verbo próprio falta | I |
| S | knowledge-state | ✅ | módulo + idade + outage emit | — |
| T | provenance | 🔶 | meta preservada; UI mínima | S |
| U | negative knowledge | ❓ | NO EVIDENCE não testado aqui | K |
| V | temporal | 🔶 | [Nd ago] + CURRENT/HISTORICAL | S |
| W | outage handling | ✅ | lessons_unavailable; propaga | S |
| X | completion verify | ✅ | evidence-gated + world_check | — |
| Y | failure recovery | 🔶 | retry/STUCK; cascade 1× | X |
| Z | long-horizon | 🔴 | P3 0/12; horizonte 3 steps (H2) | H |

Dependência crítica: quase tudo passa por I (tool selection) → por isso
Contract A é P1. O (lesson application) passa por representação (Contract B).
