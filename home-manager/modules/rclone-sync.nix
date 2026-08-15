{ pkgs, config, ... }:

let
  filterFile = pkgs.writeText "rclone-filters.txt" ''
    - **/.local/**
    - **/.npm/**
    - **/.npm-global/**
    - **/.pub-cache/**
    - **/.rustup/**
    - **/bin/**
    - **/venv/**
    - **/.venv/**
    - **/env/**
    - **/.cache/**
    - **/.local/**
    - **/.git/**
    - **/node_modules/**
    - **/__pycache__/**
    - **/target/**
    - **/run/**
    - .cargo/**
    - **/*.rclonelink
    - **/*.sock
    - **/*.log
    - **/*.wav
    - **/*.raw
    - **/*.mp3
    - **/*.prof
    - **/archive/**
    - **/archives/**
    - **/datasets/**
    - **/vcpkg/**
    - **/OTServer_UPGRADE/**
    + **
  '';

  qdrant-snapshot = pkgs.writeShellScriptBin "qdrant-snapshot" ''
    ${pkgs.curl}/bin/curl -s http://localhost:6333/collections | ${pkgs.jq}/bin/jq -r '.result.collections[].name' | while read col; do
      ${pkgs.curl}/bin/curl -X POST http://localhost:6333/collections/$col/snapshots
    done
  '';
in
{
  home.packages = [ pkgs.rclone qdrant-snapshot ];

  xdg.configFile."rclone/filters.txt".source = filterFile;

  systemd.user.services.rclone-sync = {
    Unit = {
      Description = "Sync Inteligente Rclone para Google Drive (Projects & Qdrant)";
      After = [ "network-online.target" ];
    };
    Service = {
      Type = "oneshot";
      ExecStartPre = "-${qdrant-snapshot}/bin/qdrant-snapshot";
      ExecStart = ''
        ${pkgs.rclone}/bin/rclone copy /home/nixos/projects gdrive:NixOS-Sync/03-projects \
          --filter-from ${config.xdg.configFile."rclone/filters.txt".target} \
          --update \
          --fast-list \
          --links \
          --tpslimit 10 \
          --transfers 4 \
          --checkers 8 \
          --retries 3 \
          --timeout 1h \
          --log-level INFO
      '';
    };
  };

  systemd.user.timers.rclone-sync = {
    Unit.Description = "Timer do Sync Inteligente de Projects";
    Timer = {
      OnCalendar = "*-*-* 00/4:00:00";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
