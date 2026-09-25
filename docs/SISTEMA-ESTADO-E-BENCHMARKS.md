# Estado e benchmarks do sistema (histórico — referência, não instrução)

Extraído do AGENTS.md em 25/09 porque é *rationale* e resultado de
medição, não regra operacional. A pesquisa (wilbeibi/skills,
arXiv 2602.11988) diz: post-mortem e histórico vão para doc
linkado; o arquivo de contexto fica só com o que muda comportamento.

## Benchmark do sistema (dono 16/09)
## Benchmark do sistema (dono 16/09) — resultados H1/H2/H3

### H1 — Memória/RAG como fator diferencial
Teste: `ux_driver` + `ux_world` verification (world_state). Tarefa: write+read.
Resultado: **INCONCLUSIVE** — ambas condições (controle vs +memória) criaram o arquivo. Memória não é fator diferencial para tasks que o modelo já sabe executar. Injeção automática de lessons (agent.py:477) já é o mecanismo primário.
**Revisão 16/09 (2ª opinião Buffy):** INCONCLUSIVE confirmado, mas a causa é VARIÂNCIA do agente local, não ausência de efeito. Evidência: mesma task de escrita deu sucesso em 4s (lote6/7), timeout 300s (lote4/5) e false_done (run novo 16/09, /tmp/ux-m5-buffy.json). n=1 por braço não decide; rodar n>=5 por braço com EvalHarness.compare antes de concluir. H1 permanece ABERTA.

### H2 — Persona vs Regra vs Neutro
Teste: `ux_driver` classificação falante.
Resultado: **persona PERTURBA** (respondeu NARRADOR quando deveria ser KLEIN); neutro e regras ACERTARAM. Persona só é usada para tasks de domínio específico (forensic/áudio/auditoria). Regras são mais eficazes para tasks genéricas.

### H3 — reasoning_effort gate
Teste: `ux_driver` com /no_think vs pense vs pense extensivamente.
Resultado: **higher effort = 3× turns sem ganho** em tasks curtas/classificação. Gate implementado em `llm.py`: tasks curtas (<80 chars ou keywords como "uma palavra"/"quem fala") downgrade para `low`.

### Providers free do opencode (2ª opinião 16/09)
- Causa raiz do "opencode quebrado": default `openrouter/free` = slug morto ("No endpoints available"). Fix: default = `google/gemini-2.5-flash` (E2E validado).
- Validados E2E: google, nvidia NIM (82 modelos, estava fora do config). Válidas mas inúteis no opencode: groq (ITPM 7000 < system prompt 13205), openrouter (cota free diária esgota). Billing wall: cerebras, together (US$5, recusado pelo dono). Endpoint morto: GitHub Models (410).
- HF: baseURL corrigido p/ router.huggingface.co (api-inference é legado; router validado HTTP 200).
- Checklist: rodar verify/ux scripts exige `source lab-env.sh` (libstdc++) — no nixos-ai, o kvenv puro falha com NumPy.

### A/B observação acionável anti-false_done (Buffy 16/09, commit 5422dc0)
Task natural "cria pasta+arquivo" (bonsai, PTY real, mundo verificado). **Braço A (HEAD sem fix): 0/3.** Transcripts expuseram 6 elos: (1) modelo verifica antes de criar e "File not found" é beco sem saída; (2) promise-guard genérico fazia escolher a tool ERRADA; (3) args vazios → KeyError cru `ERROR: 'path'`; (4) write_file tentado como comando shell sem ensino da interface; (5) cycle/duplicate guard vagos devolviam pro mesmo loop; (6) sucesso declarado sem verificação (path errado + "ola.txt foi escrito"). Cada elo virou correção de observação (validator, devtools, loop_detector, dev.py) + 1 âncora no TOOL_USE_DISCIPLINE + claim-checker + cap de list_directory (21k itens soterravam hints). **Braço B: 0/9 world-state exato** (variância do modelo domina; mas progresso mecânico: write_file passou de 0 para 2 chamadas reais em 9 runs). Falso-verde do próprio driver corrigido: `ux_driver --world-check` (rc=0 sozinho não prova sucesso — B4 tinha rc=0 com mundo AUSENTE). Próximo: se a stack nova não mover world-state com n≥5, o gargalo é a camada de geração do modelo fraco (read-first inato), e a alavanca certa é gate de rota (tool_forced first write) testado como experimento, não mais observação.

## Doutrina de tooling agentes (dono 16/09)
## Doutrina de tooling agentes (dono 16/09)
- Caminho oficial: MCPs (rag/memory/lessons/vault) + harness (`LLMClient`,
  safe_editor, validator, checkpoint) + personas com handoff. Ver BUFFY §50.
- Personas: `jarvis persona --list`; auditoria áudio = `forensic_audio_auditor`.
- Timers: `audiobook-audit` 01:00 (applio-lab); `nightwatch` DESABILITADO.
- MCP discoverability: descrições com gatilho (WHEN primeiro) + tool `jarvis_persona`.

