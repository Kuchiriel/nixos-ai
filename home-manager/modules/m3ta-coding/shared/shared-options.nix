# Shared option definitions for agent modules.
# Prevents copy-pasting the externalSkills submodule across opencode/claude-code/pi.
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
        "chiron-forge" = "anthropic/claude-sonnet-4";
      }
    '';
  };

  # External skills submodule — used by opencode, claude-code, and pi modules.
  externalSkillsOption = mkOption {
    type = types.listOf (types.submodule {
      options = {
        src = mkOption {
          type = types.anything;
          description = "Flake input pointing to a skills repository root.";
        };
        skillsDir = mkOption {
          type = types.str;
          default = "skills";
          description = ''
            Subdirectory inside src that contains skill folders.
          '';
        };
        selectSkills = mkOption {
          type = types.nullOr (types.listOf types.str);
          default = null;
          description = ''
            List of skill names to cherry-pick from this source.
            null means include every skill found in skillsDir.
          '';
        };
      };
    });
    default = [];
    description = ''
      External skill sources passed to mkSkills.
      Each entry maps directly to an element of the externalSkills
      list accepted by the AGENTS flake's lib.mkSkills.
    '';
    example = literalExpression ''
      [
        { src = inputs.skills-anthropic; selectSkills = [ "claude-api" ]; }
        { src = inputs.basecamp; }
      ]
    '';
  };

  # Helper to map externalSkills from module config to mkSkills format.
  mapExternalSkills = cfgEntries:
    map (
      entry:
        {inherit (entry) src skillsDir;}
        // lib.optionalAttrs (entry.selectSkills != null) {inherit (entry) selectSkills;}
    )
    cfgEntries;
}
