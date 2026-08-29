# REPL Improvements — Backlog

> Aplicar após a missão de recuperação estrutural.
> Estas melhorias foram pesquisadas mas não implementadas ainda.

## 1. LSP Integration (OpenCode-style)

**Status**: HYPOTHESIS
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

**Status**: HYPOTHESIS
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

**Status**: HYPOTHESIS
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

**Status**: HYPOTHESIS
**Impacto**: Baixo
**Complexidade**: Média

Links compartilháveis para:
- Handoff entre equipes
- Debug de problemas
- Review de mudanças

## Prioridade de Implementação

1. **LSP** — maior impacto na qualidade do código gerado
2. **Git auto-commit** — maior impacto na traceabilidade
3. **Multi-session** — maior impacto na produtividade
4. **Session sharing** — menor impacto, pode esperar
