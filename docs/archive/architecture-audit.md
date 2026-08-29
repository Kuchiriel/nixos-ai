# 🔍 Auditoria de Arquitetura — nixos-ai

## 📊 Visão Geral

| Métrica | Valor |
|---------|-------|
| Total de arquivos .nix | 74 |
| home-manager modules | 28 |
| nixos modules | 15 |
| services | 8 |
| hosts | 2 |

---

## ✅ Sessão 2026-08-24 — Correções de Arquitetura

### Problemas encontrados e corrigidos

| # | Problema | Causa | Correção | Arquivo |
|---|----------|-------|----------|---------|
| 1 | `execute_shell` duplicado (TOOL + DEV_TOOL) | Mesma tool em 2 módulos | Removido de devtools.py | `devtools.py` |
| 2 | Sem output truncation | stdout retornado inteiro (MB) | TOOL_OUTPUT_MAX_CHARS=8000 | `agent.py` |
| 3 | Sem duplicate tool detection | Modelo chamava mesma tool infinitamente | Tracking + warning após 3x | `agent.py` |
| 4 | Circuit breaker quebrado | `json.loads()` em resposta de texto | Simplificado: retorna só texto | `agent.py` |
| 5 | RAG chunk 300 (muito pequeno) | Embeddings perdiam contexto | Aumentado para 2000 | `rag.py` |
| 6 | RAG sem change detection | Re-indexava tudo sempre | mtime cache | `rag.py` |
| 7 | RAG sparse_terms sem acentos | Regex [a-zA-Z0-9_] | Trocado para \w+ | `rag.py` |
| 8 | Self-heal sem max restarts | Loop infinito possível | MAX_RESTARTS=5 | `heal.py` |
| 9 | Self-heal sem verify | systemctl retornava 0 sem confirmar | _verify_service_up() | `heal.py` |
| 10 | Doctor pgrep -f muito amplo | Falsos positivos | Trocado para pgrep -x | `doctor.py` |
| 11 | Doctor check_network frágil | Socket 1.1.1.1:53 bloqueável | HTTP check | `doctor.py` |
| 12 | Memory dedup agressiva | Chave 200 chars falsos positivos | Aumentado para 500 | `memory.py` |

### Arquitetura NixOS

| Componente | Antes | Depois |
|------------|-------|--------|
| Controle de serviços | Sem toggle global | `services.jarvis.enable` (mkIf) |
| Target systemd | Sem target | `jarvis.target` (multi-user.target) |
| Serviços Jarvis | `wantedBy = ["multi-user.target"]` | `PartOf = ["jarvis.target"]` |
| zram default | 100% (perigoso) | 50% |
| rebuild-host.sh | Sem validação | `nix eval` antes do switch |
| models.nix | Parcialmente comentado | Todos os modelos restaurados |
| ranger.nix | Quebrado (ueberzug) | Corrigido (sixel), reativado |
| UPower | Não habilitado | Habilitado (bateria waybar) |

---

---

## 🚨 Problemas Encontrados

### 1. FONTE — 4 locations hardcoded, nenhuma single source

```
foot.nix:      "JetBrainsMono Nerd Font:size=14"     ← mkForce
waybar.nix:    "JetBrainsMono Nerd Font"             ← CSS hardcoded
rofi.rasi:     "JetBrainsMono Nerd Font 12"          ← hardcoded
stylix.nix:    "JetBrains Mono" (size 13)            ← conflita com foot
```

**Problema:** 4 fontes diferentes, 4 tamanhos diferentes. Trocar a fonte exige editar 4 arquivos.

**Solução:** Criar `lib/fonts.nix` com single source of truth:
```nix
{
  mono = {
    name = "JetBrainsMono Nerd Font";
    size = 14;
    package = pkgs.jetbrains-mono;
  };
  sans = {
    name = "Noto Sans";
    package = pkgs.noto-fonts;
  };
  emoji = {
    name = "Noto Color Emoji";
    package = pkgs.noto-fonts-color-emoji;
  };
}
```

### 2. CORES — stylix vs manual, conflito permanente

```
stylix.nix:     base16Scheme = "oceanicnext.yaml"    ← define cores globais
waybar.nix:     #00ffff hardcoded no CSS             ← ignora stylix
hyprlock.nix:   rgba(235, 219, 178, 1.0)             ← hardcoded
hyprland/main:  rgba(00ffffcc)                        ← hardcoded
```

**Problema:** Stylix define um esquema de cores (oceanicnext), mas waybar/hyprland/hyprlock ignoram e usam #00ffff hardcoded. Se mudar o esquema no stylix, 80% do setup continua cyan.

**Solução:** Ou confia no stylix (remove hardcodes) ou não usa stylix (define tudo manual). Misturar causa confusão.

### 3. PORTS — parcialmente centralizado

```
lib/ports.nix:       ✅ Existe (mkPortHelpers)
launcher.sh:         ❌ 8080, 8081, 6333 hardcoded
models.nix:          ❌ Usa inline
python config.py:    ❌ Defaults hardcoded
```

**Problema:** O `lib/ports.nix` existe mas não é usado por todos. O launcher.sh e Python usam defaults hardcoded.

### 4. PATHS — hardcoded em vários lugares

```
launcher.sh:     PROJECT_DIR="$HOME/projects/nixos-ai"   ← hardcoded
rclone-sync:     /home/nixos/projects                     ← hardcoded
binds.nix:       ${launcherScript}/bin/nixos-ai-launcher  ← hardcoded
```

### 5. CSS do waybar — não usa variáveis

O waybar.nix tem ~200 linhas de CSS com cores hardcoded. Poderia usar variáveis CSS:
```css
@define-color bg #0a0a0a;
@define-color fg #00ffff;
window#waybar { background: @bg; color: @fg; }
```

---

## 🏗️ Arquitetura Proposta

### Estrutura atual vs proposta

```
ATUAL:                              PROPOSTA:
home-manager/                       home-manager/
├── home.nix (286 linhas)           ├── home.nix (~80 linhas, import-only)
├── home-packages.nix               ├── home-packages.nix
└── modules/                        └── modules/
    ├── default.nix                     ├── default.nix
    ├── foot.nix                        ├── foot.nix
    ├── waybar.nix                      ├── waybar.nix
    ├── hyprland/                       ├── hyprland/
    │   ├── main.nix                    │   ├── main.nix
    │   └── ...                         │   └── ...
    └── ...                             └── ...
                                    lib/
                                    ├── fonts.nix      ← NOVO: single font source
                                    ├── colors.nix     ← NOVO: single color palette
                                    ├── ports.nix      ← EXISTE: já centraliza
                                    └── paths.nix      ← NOVO: centraliza paths
```

### Novos arquivos

#### `lib/fonts.nix` — Single source para fontes
```nix
{ pkgs, ... }:
{
  mono = {
    name = "JetBrainsMono Nerd Font";
    size = 14;
    package = pkgs.jetbrains-mono;
  };
  sans = {
    name = "Noto Sans";
    package = pkgs.noto-fonts;
  };
  emoji = {
    name = "Noto Color Emoji";
    package = pkgs.noto-fonts-color-emoji;
  };

  # Helpers para diferentes contextos
  footFont = "${self.mono.name}:size=${toString self.mono.size}";
  cssFamily = "${self.mono.name}, sans-serif";
}
```

#### `lib/colors.nix` — Single source para paleta
```nix
{
  # Paleta principal (cyberpunk)
  primary = "00ffff";     # ciano
  background = "0a0a0a";  # preto
  text = "ffffff";         # branco

  # Status colors
  success = "50FA7B";     # verde
  warning = "FFB86C";     # laranja
  error = "FF5555";       # vermelho
  info = "6699CC";        # azul

  # Compatibilidade com CSS
  css = {
    bg = "#0a0a0a";
    fg = "#00ffff";
    success = "#50FA7B";
    warning = "#FFB86C";
    error = "#FF5555";
  };

  # Compatibilidade com Hyprland rgba
  hypr = {
    activeBorder = "rgba(00ffffcc) rgba(0088ffcc) 45deg";
    inactiveBorder = "rgba(595959aa)";
    shadow = "rgba(00ffff33)";
  };
}
```

#### `lib/paths.nix` — Single source para paths
```nix
{ home, ... }:
{
  projectDir = "${home}/projects/nixos-ai";
  configDir = "${home}/.config";
  dataDir = "${home}/.local/share";
}
```

### Mudanças por arquivo

| Arquivo | Mudança necessária |
|---------|-------------------|
| **foot.nix** | Usar `fonts.mono.footFont` em vez de string hardcoded |
| **waybar.nix** | Usar `colors.css.*` em vez de #00ffff hardcoded |
| **rofi.rasi** | Usar `fonts.mono.name` + `fonts.mono.size` |
| **stylix.nix** | Remover `targets.foot.enable = false`, deixar stylix gerenciar foot |
| **hyprland/main.nix** | Usar `colors.hypr.*` em vez de rgba hardcoded |
| **hyprlock.nix** | Usar `colors.*` em vez de rgba hardcoded |
| **launcher.sh** | Usar variável `NIXOS_AI_DIR` em vez de hardcoded |

---

## ⚡ Prioridades de Implementação

### 🔴 Alta — Elimina conflitos imediatos
1. Criar `lib/fonts.nix` e unificar fontes
2. Decidir: stylix OU manual (não ambos)
3. Mover CSS do waybar para variáveis

### 🟡 Média — Melhora manutenção
4. Criar `lib/colors.nix` para paleta centralizada
5. Mover paths hardcoded para `lib/paths.nix`
6. Integrar `lib/ports.nix` no launcher.sh e Python

### 🟢 Baixa — Polimento
7. Adicionar `lib` ao flake outputs
8. Criar testes de config (nix flake check)
9. Documentar arquitetura no README

---

## ❓ Decisões Pendentes

1. **Stylix ou manual?**
   - **Opção A:** Manter stylix, remover todos os hardcodes de cor → cores globais consistentes
   - **Opção B:** Remover stylix, definir tudo manualmente → mais controle, mais trabalho
   - **Recomendação:** Opção B (o setup já é muito customizado, stylix limita)

2. **Fonte: 12 ou 14?**
   - foot.nix atual: 14
   - stylix forçava: 13
   -.waybar: 14
   - Qual padrão?

3. **Paleta: cyan ou stylix scheme?**
   - Atual: cyan (#00ffff) em tudo
   - Stylix: oceanicnext (azul mais discreto)
   - Qual manter?
