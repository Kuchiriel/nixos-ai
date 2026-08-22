# Módulo Pi agent management para nixos-ai
#
# Renderiza agentes canônicos do repositório AGENTS e os deploya
# para o Pi agent (~/.pi/agent/).
#
# Usage em home.nix:
#   coding.agents.pi.enable = true;
#   coding.agents.pi.agentsInput = inputs.agents;
#   coding.agents.pi.settings.defaultProvider = "anthropic";
#   coding.agents.pi.settings.defaultModel = "claude-sonnet-4";
{
  config,
  lib,
  pkgs,
  ...
}:
with lib; let
  cfg = config.coding.agents.pi;
  shared = import ./shared/shared-options.nix {inherit lib;};
in {
  imports = [./shared/default.nix];

  options.coding.agents.pi = let
    shared = import ./shared/shared-options.nix {inherit lib;};
    mcpCfg = config.programs.mcp or null;
  in
    with lib; {
      enable = mkEnableOption "Pi agent management via canonical agent.toml definitions";

      mcpServers = mkOption {
        type = types.attrsOf types.anything;
        default =
          if mcpCfg != null
          then mcpCfg.servers
          else {};
        defaultText = literalExpression "config.programs.mcp.servers";
        description = ''
          MCP server configurations for Pi (pi-mcp-adapter).
          Written to ~/.pi/agent/mcp.json.
          Automatically inherits from config.programs.mcp.servers.
        '';
      };

      agentsInput = shared.mkAgentsInputOption ''
        The `agents` flake input (your personal AGENTS repo).
        When set, the primary agent's system prompt is rendered as SYSTEM.md,
        all agents are listed in AGENTS.md, and subagent .md files are deployed.
      '';

      modelOverrides = shared.mkModelOverridesOption;

      primaryAgent = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = ''
          Override which canonical agent is used as primary for SYSTEM.md.
          When null, the first agent with mode="primary" is used.
        '';
      };

      codingRules = mkOption {
        type = types.nullOr (types.submodule {
          options = {
            languages = mkOption {
              type = types.listOf types.str;
              default = [];
              description = ''
                Language-specific coding rules to include
                (e.g. [ "python" "typescript" "nix" ]).
              '';
            };
            concerns = mkOption {
              type = types.listOf types.str;
              default = [
                "coding-style"
                "naming"
                "documentation"
                "testing"
                "git-workflow"
                "project-structure"
              ];
              description = ''
                Concern rules to include from the AGENTS repo.
              '';
            };
            frameworks = mkOption {
              type = types.listOf types.str;
              default = [];
              description = ''
                Framework-specific coding rules to include
                (e.g. [ "react" "fastapi" ]).
              '';
            };
          };
        });
        default = null;
        description = ''
          Coding rules to inject into ~/.pi/agent/AGENTS.md.
        '';
      };

      settings = mkOption {
        type = types.submodule {
          freeformType = types.attrsOf types.anything;
          options = {
            packages = mkOption {
              type = types.listOf types.str;
              default = [];
              description = ''
                Pi packages to install (npm:, git:, or local paths).
              '';
            };
            defaultProvider = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "Default LLM provider (e.g. 'anthropic', 'openai', 'zai').";
            };
            defaultModel = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "Default model ID.";
            };
            defaultThinkingLevel = mkOption {
              type = types.nullOr (types.enum ["off" "minimal" "low" "medium" "xhigh"]);
              default = null;
              description = "Default extended thinking level.";
            };
            theme = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "Pi theme name.";
            };
            hideThinkingBlock = mkOption {
              type = types.nullOr types.bool;
              default = null;
              description = "Hide thinking blocks in output.";
            };
            quietStartup = mkOption {
              type = types.nullOr types.bool;
              default = null;
              description = "Hide startup header.";
            };
            extensions = mkOption {
              type = types.listOf types.str;
              default = [];
              description = "Local extension file paths or directories.";
            };
            skills = mkOption {
              type = types.listOf types.str;
              default = [];
              description = "Local skill file paths or directories.";
            };
          };
        };
        default = {};
        description = ''
          Pi settings written to ~/.pi/agent/settings.json.
        '';
      };
    };

  config = with lib; let
    shared = import ./shared/shared-options.nix {inherit lib;};
    cfg = config.coding.agents.pi;
  in
    mkIf cfg.enable (let
      # Build settings.json by filtering out null values recursively
      filterNulls = attrs:
        lib.filterAttrs (_: v: v != null) (
          builtins.mapAttrs (_: v:
            if builtins.isAttrs v
            then let
              filtered = filterNulls v;
            in
              if filtered == {}
              then null
              else filtered
            else v)
          attrs
        );

      piSettings = filterNulls cfg.settings;

      # Coding rules config for renderForPi
      piCodingRules =
        if cfg.agentsInput != null && cfg.codingRules != null
        then cfg.codingRules // {agents = cfg.agentsInput;}
        else null;

      # Rendered agents
      rendered =
        if cfg.agentsInput != null
        then
          (import "${./../../../lib}" {inherit lib;}).agents.renderForPi {
            inherit pkgs;
            canonical = cfg.agentsInput.lib.loadAgents;
            modelOverrides = cfg.modelOverrides;
            primaryAgent = cfg.primaryAgent;
            codingRules = piCodingRules;
          }
        else null;

      # Dynamic home.file entries for agent .md files
      agentFiles =
        if cfg.agentsInput != null
        then let
          agentNames = builtins.attrNames cfg.agentsInput.lib.loadAgents;
        in
          builtins.listToAttrs (
            map (name: {
              name = ".pi/agent/agents/${name}.md";
              value = {source = "${rendered}/agents/${name}.md";};
            })
            agentNames
          )
        else {};
    in {
      home.file = mkMerge [
        # ── MCP servers from programs.mcp → ~/.pi/agent/mcp.json ───────
        (mkIf (cfg.mcpServers != {}) {
          ".pi/agent/mcp.json".text = builtins.toJSON {mcpServers = cfg.mcpServers;};
          ".pi/agent/mcp.json".force = true;
        })

        # ── ~/.pi/agent/settings.json ──────────────────────────────────
        {
          ".pi/agent/settings.json".text = builtins.toJSON piSettings;
          ".pi/agent/settings.json".force = true;
        }

        # ── AGENTS.md — agent descriptions and specialist listing ──────
        (mkIf (cfg.agentsInput != null) {
          ".pi/agent/AGENTS.md".source = "${rendered}/AGENTS.md";
        })

        # ── SYSTEM.md — primary agent's system prompt ──────────────────
        (mkIf (cfg.agentsInput != null) {
          ".pi/agent/SYSTEM.md".source = "${rendered}/SYSTEM.md";
        })

        # ── Agents — pi-subagents .md files ────────────────────────────
        agentFiles
      ];
    });
}
