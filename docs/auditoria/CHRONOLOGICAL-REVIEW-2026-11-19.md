# Revisão cronológica do nixos-ai (início: 2026-11-19)

Objetivo: entender o sistema desde o nascimento, em ordem cronológica, corrigindo bugs e melhorando oportunidades à medida que cada camada é lida. Tudo que estiver pendente deve terminar com status explícito, evidência e commit.

## Fontes de cronologia

- Git: datas de autor (`git log --all --format='%aI|%H|%s'`), primeira introdução de arquivo (`--diff-filter=A`).
- RAG/Qdrant: `ingested_at` / `ts` das coleções.
- Memória episódica: `memory/episodic/nixos-ai.jsonl`.
- Vault: handoffs mais recentes em `~/.local/state/jarvis/vault/`.
- Backlog: `scripts/backlog list --all`.

## Marcos iniciais medidos

| Ordem | Marco | Data | Evidência |
|---:|---|---|---|
| 1 | Primeiro commit do repositório (`flake.nix`, `home-manager`, `nixos`) | 2024-11-23 | `ae8789fac... here we go again` |
| 2 | Primeira documentação versionada (`README.md`) | 2024-12-14 | `git log --diff-filter=A -- '*.md'` |
| 3 | Primeiro código Python/JARVIS | 2026-08-19 | `git log --diff-filter=A -- '*.py'` |
| 4 | Primeira memória RAG (`memories`, `ts`) | 2026-08-19 | Qdrant `memories` |
| 5 | Primeiro código RAG/indexação | 2026-08-29 | commits `fix: RAG indexing...` |
| 6 | Primeiro índice `code_index` | 2026-09-18 | Qdrant `code_index.ingested_at` |
| 7 | Primeiro índice `vault` | 2026-09-25 | Qdrant `vault.ingested_at` |
| 8 | Primeiro índice `books` | 2026-10-21 | Qdrant `books.ingested_at` |
| 9 | Primeiro índice `offline_survival` | 2026-11-08 | Qdrant `offline_survival.ingested_at` |
| 10 | Primeira memória episódica versionada | 2026-11-18 | `memory/episodic/nixos-ai.jsonl` |

## Status legend

- `LIDO`: arquivo/camada lida.
- `TESTADO`: validação executada com evidência.
- `CORRIGIDO`: bug corrigido e revalidado.
- `MELHORADO`: melhoria aplicada sem mudar contrato.
- `PENDENTE`: ainda não tratado.

## Fases

### Fase 0 — Baseline

- [ ] Capturar `git status` limpo por escopo antes de cada onda.
- [ ] Registrar testes existentes e falhas conhecidas.
- [ ] Registrar backlog aberto e itens já resolvidos.
- [ ] Confirmar serviços locais relevantes (`opencode`, Qdrant, embeddings) sem assumir estado.

### Fase 1 — Origem NixOS (2024-11 → 2026-07)

- [ ] Ler commits iniciais e módulos Nix (`flake.nix`, `hosts/*`, `nixos/*`, `home-manager/*`).
- [ ] Identificar decisões de arquitetura iniciais e dívidas.
- [ ] Verificar `nix flake check` no estado atual.
- [ ] Corrigir inconsistências encontradas.

### Fase 2 — Nascimento do JARVIS (2026-08)

- [ ] Ler `modules/ai/jarvis` desde o primeiro commit de IA.
- [ ] Entender CLI, MCP, RAG, memória, configuração.
- [ ] Rodar suíte focada dos módulos alterados.
- [ ] Corrigir bugs com evidência.

### Fase 3 — Coordenação, voz, redteam e offline (2026-09 → 2026-11)

- [ ] Ler coordenação multiagente, voz, redteam, offline.
- [ ] Validar contratos de hooks/plugins.
- [ ] Resolver itens pendentes do backlog e TODOs reais.
- [ ] Atualizar documentação e memória episódica.

### Fase 4 — Fechamento

- [ ] Rodar validação ampla.
- [ ] Atualizar `AGENTS.md`/docs com regras que nasceram de erros reais.
- [ ] Criar handoff e commit por escopo.

## Pendências iniciais conhecidas

- Backlog aberto: `#18` (chunking com verifier por subtarefa).
- Repositório com modificações e arquivos não rastreados; antes de cada mudança, separar escopo e validar `git status`.
- Testes e serviços precisam ser medidos, não assumidos.

## Regra de execução

Nenhuma afirmação de "está funcionando" sem comando atual. Nenhuma correção sem teste/evidência. Nenhuma mudança destrutiva sem backup ou caminho de reversão.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.

## Era 0 — Origem NixOS (2024-11-23)

Commit inicial lido: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (`here we go again`, 2024-11-23).

Arquivos introduzidos:
- `flake.nix`, `flake.lock`
- `nixos/configuration.nix`, `nixos/hardware-configuration.nix`
- `nixos/modules/{bluetooth,boot,env,zram}.nix`
- `nixos/packages.nix`
- `home-manager/home.nix`, `tmux.nix`, `zsh.nix`, `waybar.nix`

Leitura inicial:
- Sistema nasceu como configuração NixOS + home-manager para um host pessoal (`amper`, Tashkent), com Hyprland, PipeWire, NH, Waybar, Zsh/Tmux.
- `flake.nix` apontava `nixosConfigurations.nixos` e `homeConfigurations.amper`.
- `nixos/configuration.nix` duplicava configuração de boot já presente em `nixos/modules/boot.nix` (observação histórica; não alterar sem validar host atual).
- `zramSwap.memoryPercent = 100` no commit inicial é agressivo para zram; versão atual usa 50%, indicando evolução posterior.
- `nh.flake = "/home/amper/flake"` era específico do host inicial.
- `home-manager/home.nix` usava `stateVersion = "23.11"` e usuário `amper`.

Status: `LIDO` para commit inicial. Pendente: validar se padrões perigosos desse commit sobrevivem no código atual.
