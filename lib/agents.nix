# Harness-agnostic agent management utilities
#
# This module provides functions to load canonical agent definitions and
# render them for different AI coding tools (OpenCode, Claude Code, Pi).
#
# Usage in your configuration:
#
#   let
#     m3taLib = inputs.m3ta-nixpkgs.lib.${system};
#     canonical = m3taLib.agents.loadCanonical { agentsInput = inputs.agents; };
#
#     # Render for a specific tool
#     rendered = m3taLib.agents.renderForOpencode {
#       inherit pkgs canonical;
#       modelOverrides = { chiron = "anthropic/claude-sonnet-4"; };
#     };
#   in { ... }
{lib}: let
  # ── Shared helpers ─────────────────────────────────────────────
  # Split a rule string on the LAST colon to get { pattern, action }.
  # e.g. "rm -rf *:ask" → pattern="rm -rf *", action="ask"
  # e.g. "/run/agenix/**:deny" → pattern="/run/agenix/**", action="deny"
  parseRule = ruleStr: let
    parts = lib.strings.splitString ":" ruleStr;
    action = lib.last parts;
    pattern = lib.concatStringsSep ":" (lib.init parts);
  in {inherit pattern action;};

  # ── Shared renderer primitives ──────────────────────────────────
  # Render agent files from canonical definitions into a directory.
  # Each agent gets a "<name>.md" file containing mkContent name agent.
  #
  # Args:
  #   pkgs       — Nixpkgs package set with linkFarm
  #   canonical  — Attribute set of agent definitions (keyed by slug)
  #   mkContent  — Function: name: agent → string (file content)
  #   name       — Derivation name (e.g. "opencode-agents")
  #
  # Returns:
  #   A store path containing all agent *.md files.
  renderAgentFiles = pkgs: canonical: mkContent: name:
    pkgs.linkFarm name (
      lib.mapAttrsToList (n: a: {
        name = "${n}.md";
        path = pkgs.writeText "${n}.md" (mkContent n a);
      })
      canonical
    );

  agentsLib = {
    # ── loadCanonical ─────────────────────────────────────────────
    #
    # Load canonical agent definitions from the AGENTS flake input.
    # Returns the canonical attrset from lib.loadAgents (keyed by slug).

    loadCanonical = {agentsInput}: agentsInput.lib.loadAgents;

    # ── OpenCode renderer ─────────────────────────────────────────
    #
    # Produces a directory of agent *.md files suitable for
    #   ~/.config/opencode/agents/   (system-level)
    #   .opencode/agents/            (project-level)
    #
    # Each file has YAML frontmatter (description, mode, optional model,
    # optional permission) followed by the agent's systemPrompt content.
    # The filename (without .md) becomes the agent name in OpenCode.

    renderForOpencode = {
      pkgs,
      canonical,
      modelOverrides ? {},
    }: let
      # Render one permission section to YAML lines.
      # intent-only → single line: "  <tool>: <intent>"
      # intent+rules → nested block
      renderPermSection = tool: section:
        if !(section ? rules) || section.rules == []
        then ["  ${tool}: ${section.intent}"]
        else let
          parsedRules = map parseRule section.rules;
          wildcardLine = "    \"*\": ${section.intent}";
          ruleLines = map (r: "    \"${r.pattern}\": ${r.action}") parsedRules;
        in
          ["  ${tool}:"] ++ [wildcardLine] ++ ruleLines;

      renderPermBlock = permissions:
        if permissions == {} || permissions == null
        then []
        else
          ["permission:"]
          ++ lib.concatLists (
            lib.mapAttrsToList renderPermSection permissions
          );

      mkFrontmatter = name: agent: let
        descLine = "description: \"${agent.description}.\"";
        modeLine = "mode: ${agent.mode}";
        modelLine =
          lib.optionalString
          (modelOverrides ? ${name})
          "model: ${modelOverrides.${name}}\n";
        permBlock = renderPermBlock (agent.permissions or {});
        permLines =
          if permBlock == []
          then ""
          else lib.concatStringsSep "\n" permBlock + "\n";
      in "---\n${descLine}\n${modeLine}\n${modelLine}${permLines}---\n";

      mkAgentContent = name: agent:
        (mkFrontmatter name agent) + agent.systemPrompt;
    in
      renderAgentFiles pkgs canonical mkAgentContent "opencode-agents";

    # ── Claude Code renderer ──────────────────────────────────────
    #
    # Produces a directory containing:
    #   .claude/agents/<name>.md   — one per agent with YAML frontmatter
    #   .claude/settings.json      — permission rules in Claude Code DSL
    #
    # Claude Code requires:
    #   - name field: [a-z0-9-]+ (kebab-case)
    #   - description field: required
    #   - All agents are subagents (no primary/subagent distinction)

    renderForClaudeCode = {
      pkgs,
      canonical,
      modelOverrides ? {},
    }: let
      # Claude Code permission DSL format: "Tool(pattern)" or just "Tool"
      # Canonical bash rules → "Bash(pattern)" entries
      # Canonical edit rules → "Edit(pattern)" entries
      renderPermAllow = permissions: let
        bashRules =
          if !(permissions ? bash)
          then []
          else if permissions.bash.intent == "allow"
          then ["Bash"]
          else
            map
            (r: let parsed = parseRule r; in "Bash(${parsed.pattern})")
            (lib.filter (r: (parseRule r).action == "allow") (permissions.bash.rules or []));
        editRules =
          if !(permissions ? edit)
          then []
          else if permissions.edit.intent == "allow"
          then ["Edit"]
          else
            map
            (r: let parsed = parseRule r; in "Edit(${parsed.pattern})")
            (lib.filter (r: (parseRule r).action == "allow") (permissions.edit.rules or []));
        webRules =
          lib.optional (permissions.webfetch.intent or "" == "allow") "WebFetch";
      in
        bashRules ++ editRules ++ webRules;

      renderPermDeny = permissions: let
        bashRules =
          if !(permissions ? bash)
          then []
          else
            map
            (r: let parsed = parseRule r; in "Bash(${parsed.pattern})")
            (lib.filter (r: (parseRule r).action == "deny") (permissions.bash.rules or []));
        editRules =
          if !(permissions ? edit)
          then []
          else
            map
            (r: let parsed = parseRule r; in "Edit(${parsed.pattern})")
            (lib.filter (r: (parseRule r).action == "deny") (permissions.edit.rules or []));
      in
        bashRules ++ editRules;

      # Build YAML frontmatter for one Claude Code agent .md file.
      mkClaudeFrontmatter = name: agent: let
        descLine = "description: \"${agent.description}\"";
        modelLine =
          lib.optionalString
          (modelOverrides ? ${name})
          "model: ${modelOverrides.${name}}\n";
        skillsLine =
          if (agent ? skills) && agent.skills != []
          then "skills:\n" + lib.concatStringsSep "\n" (map (s: "  - ${s}") agent.skills) + "\n"
          else "";
      in "---\n${descLine}\n${modelLine}${skillsLine}---\n";

      mkClaudeAgentContent = name: agent:
        (mkClaudeFrontmatter name agent) + agent.systemPrompt;

      agentFiles = renderAgentFiles pkgs canonical mkClaudeAgentContent "claude-code-agent-files";

      # Build settings.json with permission rules aggregated from all agents.
      allAllows = lib.flatten (lib.mapAttrsToList (_: agent: renderPermAllow (agent.permissions or {})) canonical);
      allDenies = lib.flatten (lib.mapAttrsToList (_: agent: renderPermDeny (agent.permissions or {})) canonical);

      settingsJson = builtins.toJSON {
        permissions = {
          allow = lib.unique (lib.sort (a: b: a < b) allAllows);
          deny = lib.unique (lib.sort (a: b: a < b) allDenies);
        };
      };

      settingsFile = pkgs.writeText "claude-settings.json" settingsJson;
    in
      pkgs.runCommand "claude-code-agents" {} ''
        mkdir -p $out/.claude/agents
        cp -r ${agentFiles}/* $out/.claude/agents/
        cp ${settingsFile} $out/.claude/settings.json
      '';

    # ── Pi renderer ───────────────────────────────────────────────
    #
    # This renderer produces:
    #   AGENTS.md              — concatenated agent descriptions + specialist listing
    #   SYSTEM.md              — primary agent's system prompt (replaces Pi default)
    #   agents/{name}.md       — one per agent for pi-subagents (YAML frontmatter + prompt)
    #
    # The agents/ files use pi-subagents frontmatter format:
    #   name, description, tools, extensions, model, thinking, skill,
    #   output, defaultReads, defaultProgress, interactive, maxSubagentDepth

    renderForPi = {
      pkgs,
      canonical,
      modelOverrides ? {},
      primaryAgent ? null,
      codingRules ? null,
    }: let
      # Import coding-rules lib for concatRulesMd when codingRules is provided
      codingRulesLib = import ./coding-rules.nix {inherit lib;};
      # Find the primary agent (there should be exactly one).
      primaryAgents = lib.filterAttrs (_: a: a.mode == "primary") canonical;
      primaryNames = lib.attrNames primaryAgents;
      primaryName =
        if primaryAgent != null
        then primaryAgent
        else if primaryNames == []
        then throw "lib.agents.renderForPi: no primary agent found"
        else builtins.head primaryNames;
      primary = builtins.getAttr primaryName primaryAgents;

      # Subagents for the specialist listing.
      subagents = lib.filterAttrs (_: a: a.mode != "primary") canonical;

      # ── Permission → Pi tool mapping ──────────────────────────────
      #
      # Pi built-in tools: read, bash, edit, write, grep, find, ls,
      #                     mcp, subagent, web_search, fetch_content, etc.
      # Canonical tools:   bash, edit, webfetch, websearch, question, external_directory
      #
      # We map canonical permissions to Pi's tool list.
      # intent=allow → include tool; intent=deny → exclude; intent=ask → include (Pi has no ask granularity)
      # When specific allow rules exist, the tool is always included (Pi can't restrict by pattern).

      piToolsForAgent = agent: let
        perms = agent.permissions or {};
        tools = [];
        # Always available: read (no permission concept in Pi)
        addIf = tool: section:
          if section.intent == "allow" || section.intent == "ask"
          then [tool]
          else [];
        # bash → bash
        withBash = tools ++ (addIf "bash" (perms.bash or {intent = "ask";}));
        # edit → edit
        withEdit = withBash ++ (addIf "edit" (perms.edit or {intent = "deny";}));
        # webfetch → fetch_content
        withFetch = withEdit ++ (addIf "fetch_content" (perms.webfetch or {intent = "deny";}));
        # websearch → web_search
        withSearch = withFetch ++ (addIf "web_search" (perms.websearch or {intent = "deny";}));
      in
        lib.unique (withSearch ++ ["read" "grep" "find" "ls"]);

      # ── Build YAML frontmatter for pi-subagents .md files ──────────
      mkPiFrontmatter = name: agent: let
        tools = piToolsForAgent agent;
        descLine = "description: \"${agent.description}\"";
        toolsLine = "tools: ${lib.concatStringsSep ", " tools}";
        model =
          if modelOverrides ? ${name}
          then "model: ${modelOverrides.${name}}"
          else "";
        skillsLine =
          if (agent ? skills) && agent.skills != []
          then "skill: ${lib.concatStringsSep ", " agent.skills}"
          else "";
      in
        "---\n"
        + "name: ${name}\n"
        + "${descLine}\n"
        + "${toolsLine}\n"
        + (lib.optionalString (model != "") "${model}\n")
        + (lib.optionalString (skillsLine != "") "${skillsLine}\n")
        + "---\n";

      mkPiAgentContent = name: agent:
        (mkPiFrontmatter name agent) + agent.systemPrompt;

      piAgentFiles = renderAgentFiles pkgs canonical mkPiAgentContent "pi-agent-files";

      # ── Build AGENTS.md content ───────────────────────────────────
      primaryDn = primary.display_name or primaryName;
      specialistEntries = let
        mkEntry = name: agent: let
          dn = agent.display_name or name;
        in
          "- **" + dn + "**: " + agent.description;
      in
        lib.mapAttrsToList mkEntry subagents;
      # ── Coding rules section (optional) ────────────────────────
      # When codingRules is provided, append selected rules to AGENTS.md.
      # codingRules attrset: { agents, languages, concerns, frameworks }
      codingRulesSection =
        if codingRules != null
        then let
          section = codingRulesLib.mkRulesMdSection codingRules;
        in
          if section != ""
          then "\n" + section
          else ""
        else "";

      agentsMd =
        "# Agent Instructions\n"
        + "\n"
        + "## "
        + primaryDn
        + "\n"
        + "\n"
        + primary.description
        + "\n"
        + "\n"
        + (
          if subagents == {}
          then ""
          else "## Available Specialists\n\n" + lib.concatStringsSep "\n" specialistEntries + "\n"
        )
        + codingRulesSection;

      agentsMdFile = pkgs.writeText "AGENTS.md" agentsMd;
      systemMdFile = pkgs.writeText "SYSTEM.md" primary.systemPrompt;
    in
      pkgs.runCommand "pi-agents" {} ''
        mkdir -p $out/agents
        cp ${agentsMdFile} $out/AGENTS.md
        cp ${systemMdFile} $out/SYSTEM.md
        cp -r ${piAgentFiles}/* $out/agents/
      '';

    # ── renderForTool dispatcher ──────────────────────────────────
    #
    # Dispatches to the correct renderer by tool name.
    # tool: "opencode" | "claude-code" | "pi"

    renderForTool = {
      pkgs,
      agentsInput,
      tool,
      modelOverrides ? {},
      codingRules ? null,
    }: let
      canonical = agentsInput.lib.loadAgents;
    in
      if tool == "opencode"
      then
        agentsLib.renderForOpencode {
          inherit pkgs canonical modelOverrides;
        }
      else if tool == "claude-code"
      then
        agentsLib.renderForClaudeCode {
          inherit pkgs canonical modelOverrides;
        }
      else if tool == "pi"
      then
        agentsLib.renderForPi {
          inherit pkgs canonical modelOverrides codingRules;
        }
      else throw "lib.agents.renderForTool: unknown tool '${tool}'. Must be opencode, claude-code, or pi.";

    # ── shellHookForTool ──────────────────────────────────────────
    #
    # Generates a shellHook string for use in devShells that symlinks
    # rendered agent files into the project directory.
    #
    # Usage:
    #   devShells.default = pkgs.mkShell {
    #     shellHook = m3taLib.agents.shellHookForTool {
    #       inherit pkgs;
    #       agentsInput = inputs.agents;
    #       tool = "opencode";
    #       modelOverrides = { chiron = "anthropic/claude-sonnet-4"; };
    #     };
    #   };

    shellHookForTool = {
      pkgs,
      agentsInput,
      tool,
      modelOverrides ? {},
      codingRules ? null,
    }: let
      rendered = agentsLib.renderForTool {
        inherit pkgs agentsInput tool modelOverrides codingRules;
      };
    in
      if tool == "opencode"
      then ''
        # Agent files for OpenCode
        mkdir -p .opencode/agents
        ln -sfn ${rendered}/* .opencode/agents/
      ''
      else if tool == "claude-code"
      then ''
        # Agent files for Claude Code
        mkdir -p .claude/agents
        ln -sfn ${rendered}/.claude/agents/* .claude/agents/
        ln -sfn ${rendered}/.claude/settings.json .claude/settings.json
      ''
      else if tool == "pi"
      then ''
        # Agent files for Pi
        ln -sfn ${rendered}/AGENTS.md AGENTS.md
        mkdir -p .pi
        ln -sfn ${rendered}/SYSTEM.md .pi/SYSTEM.md
        mkdir -p .pi/agents
        ln -sfn ${rendered}/agents/* .pi/agents/
      ''
      else throw "lib.agents.shellHookForTool: unknown tool '${tool}'";
  };
in
  agentsLib
