# REPL Improvements — Backlog

> Aplicar após a missão de recuperação estrutural.
> Estas melhorias foram pesquisadas mas não implementadas ainda.

## 1. LSP Integration (OpenCode-style)

**Status**: HYPOTHESIS — NOT YET IMPLEMENTED
**Impacto**: Alto — modelo recebe type information
**Complexidade**: Alta

OpenCode usa LSP para:
- Auto-detectar language server do projeto
- Fornecer type info, symbol definitions, diagnostics
- Reduzir erros de tipo em código gerado

**Para implementar:**
- Integrar `pylsp` (Python), `nil` (Nix), `clangd` (C/C++)
- Injetar diagnostics no contexto do modelo
- Usar `textDocument/publishDiagnostics` para erros reais

## 2. Git Auto-Commit (Aider-style)

**Status**: HYPOTHESIS — NOT YET IMPLEMENTED
**Impacto**: Médio — traceabilidade de mudanças
**Complexidade**: Média

Aider faz:
- Cada edit vira commit automático
- Branch por sessão
- Rollback fácil via git revert

**Para implementar:**
- Após cada `str_replace`/`write_file`, auto-commit
- Message: "jarvis: {descrição da mudança}"
- Branch: `jarvis/{session-id}`

## 3. Multi-Session (OpenCode-style)

**Status**: HYPOTHESIS — NOT YET IMPLEMENTED
**Impacto**: Médio — paralelismo
**Complexidade**: Alta

OpenCode permite:
- Múltiplos agentes no mesmo projeto
- Session sharing via links
- Coordenção entre sessões

**Para implementar:**
- Sessions em `~/.local/share/jarvis/sessions/`
- IDs únicos por sessão
- `jarvis dev --continue {session-id}`

## 4. Session Sharing

**Status**: HYPOTHESIS — NOT YET IMPLEMENTED
**Impacto**: Baixo
**Complexidade**: Média

Links compartilháveis para:
- Handoff entre equipes
- Debug de problemas
- Review de mudanças

## IMPLEMENTED IN THIS SESSION

### ✅ Context File Discovery (2026 Standard)
- Walks up from CWD (no hardcoded paths)
- Discovers: AGENTS.md, CLAUDE.md, GEMINI.md, .cursorrules
- Follows AGENTS.md spec (Linux Foundation): nearest wins
- Home-level: `~/.agents.md` via home-manager

### ✅ .jarvismodes (Custom Modes)
- Format inspired by .roomodes
- 5 modes: code, architect, nightwatch, organizer, research
- Declarative via home-manager (`~/.jarvismodes`)
- REPL commands: /modes, /mode <slug>

### ✅ All 20 MCP Tools in REPL
- Added: lessons, read_chatgpt, rag_index
- Full parity with MCP server

### ✅ Pipe/Semicolon Support
- `find ... -o ... | head -20` now works
- Safe pipe validation (blocks `| rm`, etc.)
- Updated: agent.py, devtools.py, mcp_server.py

### ✅ Slash Commands
- /reasoning (low|medium|high)
- /lessons (search learned lessons)
- /vault (list persistent notes)
- /modes (list available modes)
- /mode <slug> (switch mode)

### ✅ System Prompt
- Full 20-tool list documented
- Output limits enforced
- Context-aware rules

## Prioridade de Implementação (remaining)

1. **LSP** — maior impacto na qualidade do código gerado
2. **Git auto-commit** — maior impacto na traceabilidade
3. **Multi-session** — maior impacto na produtividade
4. **Session sharing** — menor impacto, pode esperar
