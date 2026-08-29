# Coding rules management utilities
#
# This module provides functions to configure Opencode agent rules across
# multiple projects. Rules are defined in the AGENTS repository and can be
# selectively included based on language, framework, and concerns.
#
# Usage in your configuration:
#
#   # In your flake or configuration:
#   let
#     projectLib = ...;
#
#     rules = projectLib.coding-rules.mkCodingRules {
#       agents = inputs.agents;
#       languages = [ "python" "typescript" ];
#       concerns = [ "coding-style" "naming" "documentation" ];
#       frameworks = [ "react" "fastapi" ];
#     };
#   in {
#     # Use in your devShell:
#     devShells.default = pkgs.mkShell {
#       shellHook = rules.shellHook;
#       inherit (rules) instructions;
#     };
#   }
#
# The shellHook creates:
#   - A `.opencode-rules/` symlink pointing to the AGENTS repository rules directory
#   - A `coding-rules.json` file with a $schema reference and instructions list
#   - (Optional) Appends coding rules to `AGENTS.md` for Pi agent discovery
#
# The instructions list contains paths relative to the project root, all prefixed
# with `.opencode-rules/`, making them portable across different project locations.
{lib}: let
  # Create Opencode rules configuration from AGENTS repository
  #
  # Args:
  #   agents: Path to the AGENTS repository (non-flake input)
  #   languages: Optional list of language-specific rules to include
  #              (e.g., [ "python" "typescript" "rust" ])
  #   concerns: Optional list of concern rules to include
  #             Default: [ "coding-style" "naming" "documentation" "testing" "git-workflow" "project-structure" ]
  #   frameworks: Optional list of framework-specific rules to include
  #               (e.g., [ "react" "fastapi" "django" ])
  #   extraInstructions: Optional list of additional instruction paths
  #                      (for custom rules outside standard locations)
  #   forPi: Whether to also append rules to AGENTS.md for Pi agent (default: true)
  #          Pi discovers AGENTS.md files by walking parent dirs + cwd and concatenates them.
  #          When enabled, a delimited block is appended to (or created in) AGENTS.md.
  #
  # Returns:
  #   An attribute set containing:
  #     - shellHook: Bash code to create symlink and coding-rules.json
  #     - instructions: List of rule file paths (relative to project root)
  #
  # Example:
  #   mkCodingRules {
  #     agents = inputs.agents;
  #     languages = [ "python" ];
  #     frameworks = [ "fastapi" ];
  #   }
  #   # Returns:
  #   # {
  #   #   shellHook = "...";
  #   #   instructions = [
  #   #     ".opencode-rules/concerns/coding-style.md"
  #   #     ".opencode-rules/concerns/naming.md"
  #   #     ".opencode-rules/concerns/documentation.md"
  #   #     ".opencode-rules/concerns/testing.md"
  #   #     ".opencode-rules/concerns/git-workflow.md"
  #   #     ".opencode-rules/concerns/project-structure.md"
  #   #     ".opencode-rules/languages/python.md"
  #   #     ".opencode-rules/frameworks/fastapi.md"
  #   #   ];
  #   # }
  mkCodingRules = {
    agents,
    languages ? [],
    concerns ? [
      "coding-style"
      "naming"
      "documentation"
      "testing"
      "git-workflow"
      "project-structure"
    ],
    frameworks ? [],
    extraInstructions ? [],
    rulesDir ? ".opencode-rules",
    forPi ? false,
  }: let
    # Build instructions list by mapping concerns, languages, frameworks to their file paths
    # All paths are relative to project root via the rulesDir symlink
    instructions =
      (map (c: "${rulesDir}/concerns/${c}.md") concerns)
      ++ (map (l: "${rulesDir}/languages/${l}.md") languages)
      ++ (map (f: "${rulesDir}/frameworks/${f}.md") frameworks)
      ++ extraInstructions;

    # Generate JSON configuration for coding rules
    rulesConfig = {
      "$schema" = "https://opencode.ai/config.json";
      inherit instructions;
    };

    # Pi rules content (concatenated markdown) — only computed when forPi is true
    piRulesSection =
      if forPi
      then mkRulesMdSection {inherit agents languages concerns frameworks;}
      else "";

    # Bash snippet to append rules to AGENTS.md for Pi discovery.
    # Uses HTML comment markers for idempotent updates:
    #   - Removes any existing CODING-RULES block
    #   - Appends the new block
    #   - Creates AGENTS.md if it doesn't exist
    # Note: Uses plain if-then-else instead of lib.optionalString to avoid
    # forcing the `lib` argument (which may come from import <nixpkgs/lib>)
    # when forPi is false.
    piShellHook =
      if forPi && piRulesSection != ""
      then ''
        # Pi agent: append coding rules to AGENTS.md
        if [ -f AGENTS.md ]; then
          # Remove existing coding-rules block (if any)
          sed -i '/<!-- CODING-RULES:START -->/,/<!-- CODING-RULES:END -->/d' AGENTS.md
          # Append new coding-rules block
          cat >> AGENTS.md <<'PIRULES_EOF'
        ${piRulesSection}
        PIRULES_EOF
        else
          # Create AGENTS.md with just the coding rules
          cat > AGENTS.md <<'PIRULES_EOF'
        ${piRulesSection}
        PIRULES_EOF
        fi
      ''
      else "";
  in {
    inherit instructions;

    # Shell hook to set up rules in the project
    # Creates a symlink to the AGENTS rules directory and generates coding-rules.json
    # Optionally appends rules to AGENTS.md for Pi agent discovery
    shellHook = ''
      # Create/update symlink to AGENTS rules directory
      ln -sfn ${agents}/rules ${rulesDir}

      # Generate coding-rules.json configuration file
      cat > coding-rules.json <<'RULES_EOF'
      ${builtins.toJSON rulesConfig}
      RULES_EOF

      ${piShellHook}
    '';
  };
  # Concatenate selected rule files from the AGENTS repository into a single
  # markdown string. Used by Pi (append to AGENTS.md) and could be used by
  # other tools that don't support an instructions list.
  #
  # Args:
  #   agents: Path to the AGENTS repository (non-flake input)
  #   languages: Optional list of language-specific rules to include
  #   concerns: Optional list of concern rules to include
  #             Default: [ "coding-style" "naming" "documentation" "testing" "git-workflow" "project-structure" ]
  #   frameworks: Optional list of framework-specific rules to include
  #
  # Returns: A single concatenated markdown string with all selected rules.
  #
  # Example:
  #   concatRulesMd {
  #     agents = inputs.agents;
  #     languages = [ "python" ];
  #     concerns = [ "coding-style" ];
  #   }
  #   # Returns: "\n# Coding Style\n\n...python rules...\n"
  concatRulesMd = {
    agents,
    languages ? [],
    concerns ? [
      "coding-style"
      "naming"
      "documentation"
      "testing"
      "git-workflow"
      "project-structure"
    ],
    frameworks ? [],
  }: let
    rulePaths =
      (map (c: {
          kind = "concerns";
          name = c;
        })
        concerns)
      ++ (map (l: {
          kind = "languages";
          name = l;
        })
        languages)
      ++ (map (f: {
          kind = "frameworks";
          name = f;
        })
        frameworks);

    readRule = rule: builtins.readFile "${agents}/rules/${rule.kind}/${rule.name}.md";
    ruleContents = map readRule rulePaths;
  in
    lib.concatStringsSep "\n\n" ruleContents;

  # Build a coding rules section suitable for appending to AGENTS.md.
  # Wraps concatRulesMd output with a header and HTML comment markers
  # for idempotent updates in project-level shellHooks.
  #
  # Args: Same as concatRulesMd
  #
  # Returns: A markdown string with start/end markers and a header.
  mkRulesMdSection = args: let
    content = concatRulesMd args;
  in
    if builtins.stringLength content == 0
    then ""
    else ''
      <!-- CODING-RULES:START -->
      # Coding Rules

      ${content}
      <!-- CODING-RULES:END -->
    '';
in {
  inherit mkCodingRules concatRulesMd mkRulesMdSection;
}
