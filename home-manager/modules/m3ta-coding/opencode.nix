# Módulo OpenCode agent management para nixos-ai
#
# Renderiza agentes canônicos do repositório AGENTS e os symlinka
# para ~/.config/opencode/agents/.
#
# Usage em home.nix:
#   coding.agents.opencode.enable = true;
#   coding.agents.opencode.agentsInput = inputs.agents;
#   coding.agents.opencode.modelOverrides = { chiron = "anthropic/claude-sonnet-4"; };
{
  config,
  lib,
  pkgs,
  ...
}: {
  imports = [./shared/default.nix];

  options.coding.agents.opencode = let
    shared = import ./shared/shared-options.nix {inherit lib;};
  in
    with lib; {
      enable = mkEnableOption "OpenCode agent management via canonical agent.toml definitions";

      agentsInput = shared.mkAgentsInputOption ''
        The `agents` flake input (your personal AGENTS repo).
        When set, agents are rendered from canonical agent.toml files
        and symlinked to ~/.config/opencode/agents/.
      '';

      modelOverrides = shared.mkModelOverridesOption;
    };

  config = with lib; let
    cfg = config.coding.agents.opencode;
  in
    mkIf cfg.enable {
      # Rendered agent files symlinked to ~/.config/opencode/agents/
      xdg.configFile."opencode/agents" = let
        agentsLib = (import "${./../../../lib}" {inherit lib;}).agents;
      in
        mkIf (cfg.agentsInput != null) {
          source = agentsLib.renderForOpencode {
            inherit pkgs;
            canonical = cfg.agentsInput.lib.loadAgents;
            modelOverrides = cfg.modelOverrides;
          };
        };

      # Static config dirs from AGENTS repo
      xdg.configFile."opencode/context" = mkIf (cfg.agentsInput != null) {
        source = "${cfg.agentsInput}/context";
      };
      xdg.configFile."opencode/commands" = mkIf (cfg.agentsInput != null) {
        source = "${cfg.agentsInput}/commands";
      };
      xdg.configFile."opencode/prompts" = mkIf (cfg.agentsInput != null) {
        source = "${cfg.agentsInput}/prompts";
      };
    };
}
