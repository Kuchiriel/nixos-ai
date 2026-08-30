{pkgs, lib, ...}: let
  vaultDir = "$HOME/vaults/nixos-ai";
  
  gitSyncObsidian = pkgs.writeScriptBin "git-sync-obsidian" ''
    #!/bin/sh
    # Sync Obsidian vault to git (declarative backup)
    VAULT_DIR="${vaultDir}"
    cd "$VAULT_DIR" || exit 1
    git add .
    git commit -m "$(date '+%Y-%m-%d %H:%M:%S')" || exit 0
  '';
  
  # HackMD sync script (uses JARVIS MCP)
  hackmdSync = pkgs.writeScriptBin "hackmd-sync-vault" ''
    #!/bin/sh
    # Sync vault notes to HackMD via JARVIS CLI
    VAULT_DIR="${vaultDir}"
    for note in "$VAULT_DIR"/*.md; do
      if [ -f "$note" ]; then
        title=$(basename "$note" .md)
        echo "Syncing: $title"
        ~/projects/nixos-ai/scripts/jarvis-cli.sh hackmd-sync "$note" "$title" 2>/dev/null || true
      fi
    done
  '';
in {
  home.packages = [gitSyncObsidian hackmdSync];
  
  # Declarative Obsidian vault configuration
  home.file."${vaultDir}/.obsidian/app.json" = {
    text = builtins.toJSON {
      defaultViewMode = "preview";
      showLineNumber = true;
      strictLineBreaks = false;
      readableLineLength = true;
    };
  };
  
  home.file."${vaultDir}/.obsidian/community-plugins.json" = {
    text = builtins.toJSON ["hackmd-sync"];
  };
  
  home.file."${vaultDir}/.obsidian/hackmd-sync.json" = {
    text = builtins.toJSON {
      apiToken = "";  # Set via environment or manually
      syncOnSave = true;
      syncInterval = 300;
    };
  };

  systemd.user.services.git-sync-obsidian = {
    Unit = {
      Description = "Sync Obsidian Vault with Git";
      Wants = "git-sync-obsidian.timer";
    };
    Service = {
      ExecStart = "${gitSyncObsidian}/bin/git-sync-obsidian";
      Type = "simple";
    };
  };

  systemd.user.timers.git-sync-obsidian = {
    Unit.Description = "Run Git Sync for Obsidian Vault";
    Timer.OnCalendar = "*:0/15";
    Install.WantedBy = ["timers.target"];
  };

  # ═══ HackMD Sync Plugin ═══
  # Plugin installed declaratively via community-plugins.json
  # Configure API token via:
  #   Settings → HackMD Sync → API Token
  # Or set HMD_API_ACCESS_TOKEN environment variable
  #
  # The JARVIS MCP server also syncs docs to HackMD automatically.
  # This creates a triangle: Obsidian ↔ HackMD ↔ JARVIS
}
