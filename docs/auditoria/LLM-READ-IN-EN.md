# Auditoria LLM-read: tudo que o modelo lê, em inglês (2026-11-02)

Regra da casa (AGENTS.md §Language rule): **tudo que um LLM lê é inglês**. O modelo
não entende pt-BR (bonsai é pequeno); o **idioma de saída** continua pt-BR quando o
produto exige (a persona JARVIS fala com o dono em português) — o que muda é o
**enunciado**: em inglês, com o idioma de resposta declarado explicitamente.

## Como auditar (não é grep de "palavra pt-BR")

Docstrings e comentários em pt-BR são **livres** (humanos leem, não o modelo). O que
chega ao modelo é: prompts de sistema, descrições de tool, persona blocks, tool
results e schemas de tool. Auditoria usada: extrair via `ast` as strings passadas
como `system_prompt_additions` / `description` / `content` + as constantes de prompt
(`SYSTEM_PROMPT_TEMPLATE`, `PLAN_PROMPT`, `MINIMAL_PROMPT`, `TOOL_USE_DISCIPLINE`) e
caçar marcadores pt-BR **dentro** delas.

## Traduzido nesta era (lane `voice-flags-en`)

| arquivo | o que era pt-BR | como ficou |
|---|---|---|
| `modules/ai/jarvis/src/jarvis/cli/dev.py` | `SYSTEM_PROMPT_TEMPLATE` (bloco "LIMITES DE OUTPUT (OBRIGATÓRIO)"), `PLAN_PROMPT`, `MINIMAL_PROMPT`, header "Direto.", "PERSONA ATIVA", bloco de claim falso (`write_file NUNCA gravou`) | "OUTPUT LIMITS (MANDATORY)", "Read the files you need and return pure JSON", "ACTIVE PERSONA", "ATTENTION: you claimed that … write_file NEVER wrote that path …" |
| `modules/ai/jarvis/src/jarvis/core/persona.py` | personas `marketing` (tabela de preços + REGRAS), `jarvis` (label VOICE & TONE), `uncensored` (role/description/responsibilities), `forensic_audio_auditor` (description) | tabelas → EN; idioma de resposta declarado ("reply in Brazilian Portuguese") |
| `modules/ai/jarvis/src/jarvis/core/vault.py` | `_SUMMARY_PROMPT` ("Você é o JARVIS, a IA de bordo…") | "You are JARVIS, the onboard AI of a NixOS system. … written in Brazilian Portuguese" |
| `modules/ai/jarvis/src/jarvis/core/agent.py` | prompt TASK MODE: SECRET-SANITIZATION | "The secrets live in the WORKING FILES … DO NOT use git reflog/recovery/merge" |
| `modules/ai/jarvis/src/jarvis/core/loop_detector.py` | aviso de busca repetida | "The search worked — repeating it filters nothing. … call read_file on one of them NOW" |
| `modules/ai/jarvis/src/jarvis/core/gameinput.py` | descrição do param `window_title` | "Fragment of the target window title (e.g. OTClient). Required in practice." |
| `modules/ai/jarvis/src/jarvis/core/model_registry.py` | guidance do tier | "… NEVER answer in Brazilian Portuguese here; Brazilian Portuguese goes to the fast tier" |

Teste updated junto: `tests/test_persona.py` (assert de "PROIBIDO" → "FORBIDDEN").
O golden `test_dev_prompt_byte_identical_to_template` continua verde porque os dois
blocos (template e `_DEV_LIMITS_SECTION`) receberam o **mesmo** texto.

Estado: `41 passed` (test_persona + test_runtime_context) · suíte completa
`1818 passed, 24 skipped, 5 xfailed` (2 falhas = LLM :8092 parado durante a ladder da
peer, não é regressão).

## Fora desta lane (donos)

- `AGENTS.md` (raiz e nixos-ai) — já em EN pela peer `coord-naming` (seção "Model
  identity" inclusa).
- `home-manager/files/opencode/plugins/memory.js` — peer.
- `modules/ai/jarvis/src/jarvis/mcp_server.py` — peer.
- `home-manager/files/opencode/plugins/rtk.ts` — **já em EN** (verificado: zero
  ocorrência pt-BR).

## Achado lateral (corrigido junto)

`SYSTEM_PROMPT_TEMPLATE` e o bloco montado por `_build_system_prompt` são comparados
**byte a byte** por um golden test → os dois blocos de limites precisam do mesmo texto.
Ao traduzir um, o outro tem de mudar junto, senão o teste quebra (aconteceu: o
header "Direto."/"Direct." vivia em 3 lugares).

## Regra para o futuro

1. Prompts de sistema, tool descriptions e persona blocks: **EN**.
2. Se a resposta precisa ser em pt-BR → declarar em inglês ("reply in Brazilian
   Portuguese", "written in Brazilian Portuguese").
3. Docstrings/comentários em pt-BR: sem problema.
4. Se um teste asserta uma string de prompt, o teste asserta a **string em inglês**.
