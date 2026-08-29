# AGENTS.md — contexto compartilhado do repo

> Formato agents.md (Linux Foundation) — toda IA que trabalhar neste repo
> lê este arquivo. É a fonte de premissas universais.
> Regras de modo específico estão em `.roomodes`.

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
- `git add -A` antes de build (flake só vê arquivos trackeados)
- Commit messages em PT-BR com verbo (`feat:`/`fix:`/`chore:`/`docs:`)

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

- Modelo: Qwen3.6-35B-A3B Q4_K_M, ngl=99, ncmoe=36, ctx=32K
- Serviços: llama-server (8080), embeddings (8081), rerank (8082), qdrant (6333)
- Roo Dev: VSCodium + Roo Code, MCP servers ativos:
  - `jarvis` — shell, file ops, vision, nix eval, chatgpt reader
  - `tavily-search` — pesquisa web
  - `nixos-mcp` — pesquisar nixpkgs
  - `context7` — docs de bibliotecas
  - `playwright` — browser automation

> ⚠️ Este arquivo deve ter <150 linhas. Regras detalhadas ficam em `.roomodes`.
