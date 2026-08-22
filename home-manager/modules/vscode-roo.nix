# ══════════════════════════════════════════════════════════════
# VS Code + Roo Code — instalação 100% declarativa
# ══════════════════════════════════════════════════════════════
# Instala VS Code, extensão Roo Code, custom modes, MCP servers
# e configurações do projeto. Reprodutível em qualquer máquina.
#
# Uso: imports = [ ./nixos/modules/vscode-roo.nix ];
#
# Opções configuráveis:
#   vscode-roo.enable = true;
#   vscode-roo.extensions = [ "github.copilot" ];  # extensões extras
#   vscode-roo.mcpServers = { ... };                # servidores MCP
#   vscode-roo.customModes = [ ... ];               # custom modes YAML
# ══════════════════════════════════════════════════════════════
{ config, lib, pkgs, ... }:

with lib;

let
  cfg = config.vscode-roo;

  # Gera o JSON do mcp_settings a partir da opção mcpServers
  mcpSettingsJson = builtins.toJSON {
    mcpServers = builtins.mapAttrs (name: server: {
      command = server.command;
      args = server.args or [ ];
      env = server.env or { };
      disabled = false;
      alwaysAllow = server.alwaysAllow or [ ];
    }) cfg.mcpServers;
  };

  # Gera o YAML do .roomodes a partir de uma lista de modos
  roomodesYaml = modes: builtins.readFile (pkgs.writeText "roomodes.yaml" modes);
in
{
  options.vscode-roo = {
    enable = mkEnableOption "VS Code + Roo Code installation";

    extensions = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Lista de extensões VS Code adicionais";
    };

    mcpServers = mkOption {
      type = types.attrs;
      default = {
        nixos = {
          command = "${pkgs.mcp-nixos}/bin/mcp-nixos";
          args = [ ];
          alwaysAllow = [ "nix" "nix_versions" ];
        };
        tavily-search = {
          command = "${pkgs.mcp-npx-wrapper}/bin/mcp-npx-wrapper";
          args = [ "-y" "tavily-mcp" ];
          env = {
            TAVILY_API_KEY = config.vscode-roo.tavilyApiKey or "";
          };
          alwaysAllow = [ "tavily_search" "tavily_extract" ];
        };
      };
      description = "Servidores MCP configurados no Roo Code";
    };

    tavilyApiKey = mkOption {
      type = types.str;
      default = "";
      description = "API key para o Tavily Search MCP";
    };

    customModesFile = mkOption {
      type = types.path;
      default = ../.roomodes;
      description = "Caminho para o arquivo .roomodes (custom modes YAML)";
    };

    userSettings = mkOption {
      type = types.attrs;
      default = { };
      description = "Configurações userSettings extras do VS Code";
    };
  };

  config = mkIf cfg.enable {
    home-manager.sharedModules = [{
      # ── VS Code + extensões ────────────────────────────
      programs.vscode = {
        enable = true;
        package = pkgs.vscode;

        # Extensões instaladas automaticamente
        extensions = with pkgs.vscode-extensions; [
          # Roo Code (roo-cline)
          rooveterinaryinc.roo-cline

          # Linguagens
          ms-python.python
          ms-vscode.nix-language-server
          shardulm94.trailing-spaces

          # Git
          eamodio.gitlens

          # Temas e utilitários
          dracula-theme.theme-dracula
        ] ++ cfg.extensions;

        # Configurações de usuário
        userSettings = {
          # ── Roo Code timeouts ────────────────────────────
          "roo-cline.apiRequestTimeout" = 1800;  # 30 min
          "roo-cline.commandExecutionTimeout" = 300;  # 5 min

          # ── Chat nativo VS Code ──────────────────────────
          "chat.agentHost.byokModels.enabled" = true;
          "chat.customEndpoints" = [
            {
              name = "Qwen3 Local 35B";
              url = "http://127.0.0.1:8080/v1";
              models = [
                {
                  id = "qwen3-35b-a3b";
                  name = "Qwen3 35B Local";
                  maxInputTokens = 131072;
                  maxOutputTokens = 8192;
                  toolCalling = true;
                }
              ];
            }
          ];
          "chat.utilityModel" = "customendpoint/qwen3-35b-a3b";
          "chat.utilitySmallModel" = "customendpoint/qwen3-35b-a3b";

          # ── Fontes ───────────────────────────────────────
          "editor.fontFamily" = "'JetBrains Mono', 'Droid Sans Mono', 'Monaco', monospace";
          "editor.fontSize" = 14;
          "editor.inlayHints.fontFamily" = "'JetBrains Mono', monospace";
          "editor.inlineSuggest.fontFamily" = "'JetBrains Mono', monospace";
          "markdown.preview.fontFamily" = "Noto Sans, sans-serif";
          "markdown.preview.fontSize" = 14;
          "notebook.markup.fontFamily" = "Noto Sans, sans-serif";

          # ── Geral ────────────────────────────────────────
          "editor.minimap.sectionHeaderFontSize" = 11;
          "scm.inputFontFamily" = "'JetBrains Mono', monospace";
          "scm.inputFontSize" = 14;
          "screencastMode.fontSize" = 48;
          "terminal.integrated.fontSize" = 14;
          "workbench.colorTheme" = "Dracula";

          # ── Merge das configurações customizadas ─────────
        } // cfg.userSettings;
      };

      # ── MCP Settings — mcp_settings.json ───────────────
      home.file.".config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json" = {
        text = mcpSettingsJson;
      };

      # ── Custom Modes — .roomodes no home ──────────────
      home.file.".roomodes" = {
        text = builtins.readFile cfg.customModesFile;
      };
    }];

    # ── Pacotes necessários ──────────────────────────────
    home.packages = with pkgs; [
      mcp-nixos
      mcp-npx-wrapper
    ];

    # Wrapper mcp-npx-wrapper
    home.file.".local/bin/mcp-npx-wrapper" = {
      text = ''
        #!/bin/sh
        exec npx --yes "$@"
      '';
      executable = true;
    };

    # Wrapper mcp-nixos-wrapper (usa a versão mais recente do store)
    home.file.".local/bin/mcp-nixos-wrapper" = {
      text = ''
        #!/bin/sh
        # Find mcp-nixos in /nix/store (most recent version)
        MCP_NIXOS=$(find /nix/store -name "mcp-nixos" -type f -path "*/bin/mcp-nixos" 2>/dev/null | sort -V | tail -1)
        if [ -z "$MCP_NIXOS" ]; then
          echo "ERROR: mcp-nixos not found in /nix/store" >&2
          exit 1
        fi
        # Use channel cache if available (speeds up startup by ~20s)
        CACHE_DIR=$(dirname "$MCP_NIXOS")/../share/mcp-nixos
        if [ -f "$CACHE_DIR/channels.json" ]; then
          export MCP_NIXOS_CHANNEL_CACHE="$CACHE_DIR/channels.json"
        fi
        exec "$MCP_NIXOS" "$@"
      '';
      executable = true;
    };
  };
}
