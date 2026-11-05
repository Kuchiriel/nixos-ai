{pkgs, lib, ...}: let
  vaultDir = "$HOME/vaults/projects";
  
  gitSyncObsidian = pkgs.writeScriptBin "git-sync-obsidian" ''
    #!/bin/sh
    # Sync Obsidian vault to git (declarative backup)
    VAULT_DIR="${vaultDir}"
    cd "$VAULT_DIR" || exit 1
    # (04/11, sweep) O vault NAO era repo proprio: o `git add .` caia no
    # repo de $HOME (que nao tem remote) → commits locais que NAO sao
    # backup + risco de commitar o repo do HOME inteiro. Agora: exige repo
    # proprio e faz PUSH quando existe remote; sem remote, avisa.
    ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
    if [ "$ROOT" != "$VAULT_DIR" ]; then
      echo "git-sync-obsidian: $VAULT_DIR nao e repo proprio (toplevel=$ROOT) — backup do vault DESATIVADO" >&2
      exit 2
    fi
    git add -A . || exit 1
    if git diff --cached --quiet; then
      echo "git-sync-obsidian: nada novo"
      exit 0
    fi
    git commit -m "$(date '+%Y-%m-%d %H:%M:%S')" || exit 1
    if git remote | grep -q .; then
      git push || { echo "git-sync-obsidian: push falhou" >&2; exit 1; }
    else
      echo "git-sync-obsidian: repo sem remote — commit local apenas (a copia fora da maquina e o rclone)" >&2
    fi
  '';
  
  # HackMD sync script (uses JARVIS MCP)
  hackmdSync = pkgs.writeScriptBin "hackmd-sync-vault" ''
    #!/bin/sh
    # Sync vault notes to HackMD via JARVIS CLI
    VAULT_DIR="${vaultDir}"
    # Sync all .md files in vault and subdirectories
    find "$VAULT_DIR" -name '*.md' -type f | while read -r note; do
      title=$(echo "$note" | sed "s|$VAULT_DIR/||" | sed 's|/| - |g' | sed 's|\.md$||')
      echo "Syncing: $title"
      ~/projects/nixos-ai/scripts/jarvis-cli.sh hackmd-sync "$note" "$title" 2>/dev/null || true
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
      # (04/11, sweep) syncOnSave=true + token vazio = falha SILENCIOSA a
      # cada save no vault (o plugin tentava sincronizar e nao tinha
      # credencial). O sync real e feito pelo timer hackmd-sync-vault via
      # MCP (jarvis_vault_sync_hackmd). syncOnSave off = sem ruido.
      syncOnSave = false;
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
      # (04/11) oneshot: o script termina (antes ficava 'inactive dead'
      # como Type=simple, sem estado de sucesso visivel).
      Type = "oneshot";
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
