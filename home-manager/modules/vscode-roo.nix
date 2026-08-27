# ══════════════════════════════════════════════════════════════
# VS Codium + Roo Code — instalação 100% declarativa (NixOS)
# ══════════════════════════════════════════════════════════════
# Instala VSCodium, extensão Roo Code, custom modes (.roomodes),
# MCP servers (Tavily, Context7, Playwright, GitHub) e
# configurações do projeto. Reprodutível em qualquer instalação.
#
# Uso no home.nix:
#   imports = [ ./modules/vscode-roo.nix ];
#   vscode-roo = {
#     enable = true;
#     tavilyApiKey = "tvly-dev-...";
#   };
# ══════════════════════════════════════════════════════════════
{
  config,
  lib,
  pkgs,
  ...
}:
with lib; let
  cfg = config.vscode-roo;

  # ═══ Caminhos VSCodium ═══
  # VSCodium armazena dados em ~/.config/VSCodium/
  rooGlobalStorage = ".config/VSCodium/User/globalStorage/rooveterinaryinc.roo-cline";
  rooSettingsDir = "${rooGlobalStorage}/settings";

  # ═══ Gera mcp_settings.json a partir da opção mcpServers ═══
  mcpSettingsJson = builtins.toJSON {
    mcpServers =
      builtins.mapAttrs (_name: server: {
        command = server.command;
        args = server.args or [];
        env = server.env or {};
        disabled = server.disabled or false;
        alwaysAllow = server.alwaysAllow or [];
      })
      cfg.mcpServers;
  };

  # ═══ Servidores MCP pré-configurados ═══
  defaultMcpServers = {
    # ── Tavily Search (web search) ──
    tavily-search = {
      command = "${pkgs.bash}/bin/bash";
      args = [
        "-c"
        "${pkgs.coreutils}/bin/env PATH=${pkgs.nodejs}/bin:$PATH exec ${pkgs.nodejs}/bin/npx -y mcp-remote https://mcp.tavily.com/mcp/?tavilyApiKey=${cfg.tavilyApiKey}"
      ];
      env = {};
      alwaysAllow = ["tavily_search" "tavily_extract"];
    };

    # ── Context7 (library documentation) ──
    context7 = {
      command = "${pkgs.bash}/bin/bash";
      args = [
        "-c"
        "${pkgs.coreutils}/bin/env PATH=${pkgs.nodejs}/bin:$PATH exec ${pkgs.nodejs}/bin/npx -y @upstash/context7-mcp@latest"
      ];
      env = {};
      alwaysAllow = ["resolve-library-id" "get-library-docs"];
    };

    # ── Playwright (browser automation) ──
    playwright = {
      command = "${pkgs.playwright-mcp}/bin/playwright-mcp";
      args = [];
      env = {};
      alwaysAllow = [];
    };

    # ── GitHub (repo operations — desabilitado por padrão) ──
    github = {
      command = "${pkgs.github-mcp-server}/bin/github-mcp-server";
      args = [];
      env = {
        GITHUB_PERSONAL_ACCESS_TOKEN = cfg.githubToken;
      };
      disabled = cfg.githubToken == "";
      alwaysAllow = [];
    };
  };

  # ═══ Merge: defaultMcpServers ++ cfg.mcpServers (override manual) ═══
  finalMcpServers = defaultMcpServers // cfg.mcpServers;
in {
  options.vscode-roo = {
    enable = mkEnableOption "VSCodium + Roo Code installation";

    extensions = mkOption {
      type = types.listOf types.str;
      default = [];
      description = "Extensões VSX adicionais (IDs)";
    };

    mcpServers = mkOption {
      type = types.attrs;
      default = {};
      description = "Servidores MCP extras ou overrides dos defaults";
    };

    tavilyApiKey = mkOption {
      type = types.str;
      default = "";
      description = "API key do Tavily Search";
    };

    githubToken = mkOption {
      type = types.str;
      default = "";
      description = "GitHub Personal Access Token (vazio = desabilitado)";
    };

    customModesFile = mkOption {
      type = types.path;
      default = ../../.roomodes;
      description = "Caminho para o arquivo .roomodes (custom modes YAML)";
    };

    userSettings = mkOption {
      type = types.attrs;
      default = {};
      description = "Configurações userSettings extras do VSCodium";
    };
  };

  config = mkIf cfg.enable {
    # ════════════════════════════════════════════════════════
    # 1. VSCODIUM + EXTENSÕES
    # ════════════════════════════════════════════════════════
    programs.vscode = {
      enable = true;
      package = pkgs.vscodium;

      extensions = with pkgs.vscode-extensions;
        [
          # ── Roo Code (coding agent) ──
          rooveterinaryinc.roo-cline

          # ── Linguagens ──
          ms-python.python
          shardulm94.trailing-spaces

          # ── Git ──
          eamodio.gitlens

          # ── Tema ──
          dracula-theme.theme-dracula
        ]
        ++ cfg.extensions;

      userSettings =
        {
          # ── Roo Code ──
          "roo-cline.apiRequestTimeout" = 1800;
          "roo-cline.commandExecutionTimeout" = 300;
          "roo-cline.useAgentRules" = true;

          # ── VS Code Chat (llama.cpp local) ──
          "chat.agentHost.byokModels.enabled" = true;
          "chat.customEndpoints" = [
            {
              name = "Qwen3 Local 35B";
              url = "http://127.0.0.1:8080/v1";
              models = [
                {
                  id = "qwen3.6-35b-a3b";
                  name = "Qwen3 35B Local";
                  maxInputTokens = 32768;
                  maxOutputTokens = 8192;
                  toolCalling = true;
                }
              ];
            }
          ];



          # ── Merge das configs customizadas ──
        }
        // cfg.userSettings;
    };

    # ════════════════════════════════════════════════════════
    # 2. MCP SETTINGS (mcp_settings.json)
    # ════════════════════════════════════════════════════════
    home.file."${rooSettingsDir}/mcp_settings.json".text = mcpSettingsJson;

    # ════════════════════════════════════════════════════════
    # 3. CUSTOM MODES (.roomodes)
    # ════════════════════════════════════════════════════════
    # Roo Code lê .roomodes do workspace root, mas também aceita
    # o arquivo no global storage. Colocamos nos dois locais.
    home.file."${rooSettingsDir}/custom_modes.yaml".source = cfg.customModesFile;
    home.file.".roomodes".source = cfg.customModesFile;

    # ════════════════════════════════════════════════════════
    # 4. PACOTES NECESSÁRIOS
    # ════════════════════════════════════════════════════════
    home.packages = with pkgs; [
      # MCP servers que são chamados diretamente
      playwright-mcp
      github-mcp-server

      # Node.js para npx (mcp-remote, context7)
      nodejs
    ];

    # ════════════════════════════════════════════════════════
    # 5. WRAPPERS (para paths estáveis)
    # ════════════════════════════════════════════════════════
    home.file.".local/bin/vscodium-wrapper" = {
      text = ''
        #!/bin/sh
        exec ${pkgs.vscodium}/bin/codium "$@"
      '';
      executable = true;
    };

    # Desktop entry para VSCodium
    home.file.".local/share/applications/codium.desktop" = {
      text = ''
        [Desktop Entry]
        Name=VSCodium
        Comment=Open Source Editor (VS Code without Microsoft branding)
        GenericName=Text Editor
        Exec=${pkgs.vscodium}/bin/codium %F
        Icon=codium
        Type=Application
        StartupNotify=false
        StartupWMClass=VSCodium
        Categories=Utility;TextEditor;Development;IDE;
        MimeType=text/plain;inode/directory;application/x-code-workspace;
        Actions=new-empty-window;
        Keywords=vscodium;vscode;

        [Desktop Action new-empty-window]
        Name=New Empty Window
        Exec=${pkgs.vscodium}/bin/codium --new-window %F
        Icon=codium
      '';
    };
  };
}
