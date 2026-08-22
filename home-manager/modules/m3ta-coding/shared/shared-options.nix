# Shared option definitions for agent modules.
# Biblioteca pura — importa com: import ./shared-options.nix { inherit lib; }
{lib}: let
  inherit (lib) mkOption mkEnableOption types literalExpression;
in {
  # Common agentsInput option used by all agent modules.
  mkAgentsInputOption = description:
    mkOption {
      type = types.nullOr types.anything;
      default = null;
      inherit description;
    };

  # Common modelOverrides option.
  mkModelOverridesOption = mkOption {
    type = types.attrsOf types.str;
    default = {};
    description = ''
      Per-agent model overrides. Maps agent slug to model string.
      Example: { chiron = "anthropic/claude-sonnet-4"; }
    '';
    example = literalExpression ''
      {
        chiron = "anthropic/claude-sonnet-4";
      }
    '';
  };
}
