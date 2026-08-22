# Git identity configuration for coding agents
#
# Configura identidade Git (name + email) usada por todos os agents
# de coding (OpenCode, Pi, Claude Code).
{
  config,
  lib,
  pkgs,
  ...
}:
with lib; let
  cfg = config.coding.agents.shared.gitIdentity;
in {
  options.coding.agents.shared.gitIdentity = {
    enable = mkEnableOption "git identity for coding agents";
    name = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Git name for coding agents.";
    };
    email = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Git email for coding agents.";
    };
  };

  config = mkIf (cfg.enable && cfg.name != null && cfg.email != null) {
    programs.git = {
      userName = cfg.name;
      userEmail = cfg.email;
    };
  };
}
