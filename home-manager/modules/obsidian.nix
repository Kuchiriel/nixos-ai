{pkgs, ...}: let
  gitSyncObsidian = pkgs.writeScriptBin "git-sync-obsidian" ''
    #!/bin/sh

    VAULT_DIR="$HOME/para"
    cd $VAULT_DIR || exit 1
    git add .
    git commit -m "$(date '+%Y-%m-%d %H:%M:%S')" || exit 0
  '';
in {
  home.packages = [gitSyncObsidian];

  systemd.user.services.git-sync-obsidian = {
    Unit = {
      Description = "Sync Obsidian Vault with GitHub";
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
  # Install via Obsidian Community Plugins (BRAT or manual)
  # Plugin: hackmd-sync (bidirectional push/pull)
  # After Obsidian starts, go to:
  #   Settings → Community Plugins → Browse → Search "HackMD Sync" → Install
  # Then configure:
  #   Settings → HackMD Sync → API Token: (same token as JARVIS)
  #
  # Alternative: use hackmd-push for one-way push only
  #
  # The JARVIS MCP server also syncs docs to HackMD automatically.
  # This creates a triangle: Obsidian ↔ HackMD ↔ JARVIS
}
