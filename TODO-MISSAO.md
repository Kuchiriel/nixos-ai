# TODO — Missão de Recuperação e Hardening

> Atualizado: 2026-08-29
> Status: EM ANDAMENTO

## P0 — Segurança

### P0-1: Credencial Tavily exposta
- **Problema**: `tavilyApiKey` em texto plano em `home-manager/home.nix:95`
- **Evidência**: `grep -rn "tavilyApiKey" home-manager/home.nix`
- **Arquivos**: `home-manager/home.nix`, `home-manager/modules/vscode-roo.nix`
- **Solução**: Mover para EnvironmentFile ou secret injection
- **Testes**: Verificar que a chave não está em mais nenhum lugar
- **Status**: TODO

## P1 — Arquitetura Nix

### P1-1: Importação dinâmica via readDir
- **Problema**: `configuration.nix:14-20` usa `builtins.readDir` para descobrir serviços
- **Evidência**: `grep -n "readDir" hosts/nitro-v15/configuration.nix`
- **Arquivos**: `hosts/nitro-v15/configuration.nix`
- **Solução**: Substituir por imports explícitos ou `modules/services/default.nix`
- **Testes**: `nix flake check` deve passar
- **Status**: TODO

### P1-2: Jarvis package duplicado
- **Problema**: `jarvis` e `jarvis-voice` são idênticos (ambos `.withVoice`)
- **Evidência**: `flake.nix:87-88`
- **Arquivos**: `flake.nix`
- **Solução**: `jarvis` = core (sem voice), `jarvis-voice` = withVoice
- **Testes**: `nix build .#jarvis` e `nix build .#jarvis-voice`
- **Status**: TODO

### P1-3: Jarvis master toggle
- **Problema**: Verificar se `services.jarvis.enable = false` realmente remove tudo
- **Evidência**: Auditoria pendente
- **Arquivos**: Todos os módulos que usam `config.services.jarvis.enable`
- **Solução**: Validar e corrigir se necessário
- **Testes**: Avaliar com enable=true e enable=false
- **Status**: TODO

### P1-4: Systemd target topology
- **Problema**: Verificar topologia real jarvis.target
- **Evidência**: `grep -rn "jarvis.target" modules/services/`
- **Arquivos**: Todos os módulos de serviço
- **Solução**: Documentar e corrigir se necessário
- **Testes**: `systemctl list-dependencies jarvis.target`
- **Status**: TODO

## P2 — Qualidade

### P2-1: checkPhase com || true
- **Problema**: `regression ... || true` no `package.nix:49`
- **Evidência**: `grep -rn "|| true" modules/ai/package.nix`
- **Arquivos**: `modules/ai/package.nix`
- **Solução**: Transformar em advisory ou corrigir o teste
- **Testes**: Verificar se regression.py falha realmente
- **Status**: TODO

### P2-2: MCP security audit
- **Problema**: Auditar todas as 17 tools para path traversal, execução arbitrária
- **Evidência**: Auditoria pendente
- **Arquivos**: `modules/ai/jarvis/src/jarvis/mcp_server.py`
- **Solução**: Adicionar validação onde faltar
- **Testes**: Testes de abuso para cada tool
- **Status**: TODO

### P2-3: Models.nix profiles
- **Problema**: Verificar se profiles estão coerentes com benchmarks
- **Evidência**: `modules/ai/models.nix`
- **Arquivos**: `modules/ai/models.nix`
- **Solução**: Classificar profiles como ACTIVE/EXPERIMENTAL/DEPRECATED
- **Testes**: Verificar que o profile ativo é o benchmarked
- **Status**: TODO

## P3 — Documentação

### P3-1: Documentação refletindo código real
- **Problema**: Atualizar AGENTS.md, HANDOFF.md após correções
- **Arquivos**: `AGENTS.md`, `HANDOFF.md`
- **Status**: TODO (depois das correções)

---

## Commits planejados

```
security: remover tavilyApiKey de home.nix
nix: substituir importação dinâmica por imports explícitos
nix: separar jarvis core de jarvis-voice
systemd: validar topologia jarvis.target
tests: corrigir checkPhase || true
mcp: audit de segurança das tools
docs: atualizar documentação
```
