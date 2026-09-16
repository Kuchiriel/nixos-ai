# AGENTS.md — contexto compartilhado do repo

> Formato agents.md (Linux Foundation) — toda IA que trabalhar neste repo
> lê este arquivo. É a fonte de premissas universais.
> Regras de modo específico estão em `.roomodes`.
>
> Tags: #status/active #type/rules #project/nixos-ai
>
> **Graph:** [[HANDOFF]] | [[BUFFY.md]] | [[README]] | [[CONTEXT-ENGINEERING]]

## Comandos

```bash
# Testes (SEMPRE usar nix develop, NÃO nix-shell)
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# Build
git add -A && nix build .#jarvis --no-link && nix flake check

# Rebuild do sistema
./rebuild-host.sh    # HOST (bare metal) — NUNCA nixos-rebuild direto!
./rebuild-lab.sh     # LAB (VM)

# Limpeza Nix
./clean.sh
```

## Boundaries

**Always do:**
- Rodar testes antes de commitar
- `git add -A` antes de build (flake só vê arquivos trackeados) + confira `git ls-files` p/ arquivos novos criados na sessão
- Commit messages em PT-BR com verbo (`feat:`/`fix:`/`chore:`/`docs:`)
- Tasks do harness em inglês (o modelo local rende mais; PT-BR só p/ docs e chat)

**Ask first:**
- Mudar `configuration.nix` do host
- Alterar flags do llama-server
- Adicionar dependências novas

**Never do:**
- `nixos-rebuild` direto (usar rebuild-host.sh)
- Editar arquivos do `/nix/store/`
- `git add .` sem verificar o que está sendo adicionado
- Reiniciar o LLM durante sessão ativa

## Regras críticas

1. **`models.nix` é a única fonte de verdade** dos modelos/perfis.
2. **VRAM budget (RTX 4050 6GB)**: Main LLM ~4.6GB, mmproj em CPU, embeddings/rerank sem CUDA.
3. **NixOS-first**: tudo declarativo e reprodutível via flake.
4. **Git sync**: commits pequenos e frequentes > trabalho longo sem commit.
5. **Qualidade medida**: testes e benchmark guiam otimização — nunca "achismo".

## Estrutura do repo

```
modules/ai/jarvis/      # Código Python do agente (core, providers, mcp)
modules/services/       # Módulos NixOS (llama-cpp, qdrant, fan-control)
home-manager/modules/   # Configs do usuário (vscode-roo, hyprland)
hosts/nitro-v15/        # Config do host físico
docs/benchmarks/        # Resultados de benchmark
m3ta-nixpkgs/           # Submodule: pacotes (sidecar, stt-ptt, talk),
                        #   módulos NixOS (ports), libs (agents, coding-rules)
                        #   Detalhes: m3ta-nixpkgs/AGENTS.md
scripts/                # Scripts auxiliares
```

## Perfil do usuário

- PT-BR — responda e documente em português
- Pragmático e minimalista — extrair o máximo do mínimo
- Local-first e privacy-first
- Hardware: Acer Nitro V15 (RTX 4050 6GB / 32GB RAM)
- NixOS: declarativo e reprodutível

## Estado do sistema

- Router nativo llama-server (:8080, `--models-max 1`); tiers em
  `models.nix:routing`: `bonsai` (speed, default), `jarvis-fast`
  (Qwen3-4B), `jarvis-strong` (Qwen3.6-MoE). Default NÃO muda sem decisão.
- Serviços: router/chat (8080), embeddings (8081), rerank (8082), qdrant (6333)
- Registry: `/etc/jarvis/model-registry.json` (gerado; override
  `JARVIS_MODEL_REGISTRY`); vence param-count em profiles e model-id.
- Harness (evidência A/B n=5): `TOOL_USE_DISCIPLINE` no system SEMPRE;
  thinking OFF p/ tool-use (`JARVIS_LLM_DISABLE_THINKING=1` funciona!);
  `strict_tools` opt-in por tier (Bonsai/Gemma sim, Qwen não precisa);
  validator+LoopDetector no REPL; rc honesto (stuck ≠ done).
- Agent: DONE só com evidência (`completion.py`: trailing-error,
  artefato-existe+AST, sem afirmação sem escrita); erro idêntico 3x →
  STUCK; reads paralelos ok (shell/escrita jamais); write_file/
  str_replace exigem aprovação (jail de projeto).
- Roo Dev: VSCodium + Roo Code, MCP servers ativos:
  - `jarvis` — shell, file ops, vision, nix eval, chatgpt reader
  - `tavily-search` — pesquisa web
  - `nixos-mcp` — pesquisar nixpkgs
  - `context7` — docs de bibliotecas
  - `playwright` — browser automation

> ⚠️ Este arquivo deve ter <150 linhas. Regras detalhadas ficam em `.roomodes`.
- When patching files, the old_text must be an EXACT substring of the file content. Read the file first, then use the exact text.
- After generating code, verify it has no syntax errors before returning. Use python -c 'compile()' to check.
- Always run validation checks on generated code before returning it.
- Testes sandbox-safe: `JARVIS_STATE_DIR` global no tests/conftest.py;
  `rg` no nativeCheckInputs; sem HOME writes (sandbox read-only).
- Nightwatch: binário do serviço rebuildado via `./rebuild-host.sh`
  após mudar `modules/ai/jarvis/` (store congela código!); protocolo
  manhã em BUFFY §39; ponte p/ GuiaRenamer em BUFFY §42.

## Doutrina de tooling agentes (dono 16/09)
- Caminho oficial: MCPs (rag/memory/lessons/vault) + harness (`LLMClient`,
  safe_editor, validator, checkpoint) + personas com handoff. Ver BUFFY §50.
- Personas: `jarvis persona --list`; auditoria áudio = `forensic_audio_auditor`.
- Timers: `audiobook-audit` 01:00 (applio-lab); `nightwatch` DESABILITADO.
- MCP discoverability: descrições com gatilho (WHEN primeiro) + tool `jarvis_persona`.

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
