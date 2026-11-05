{
  pkgs,
  config,
  ...
}: let
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
    - **/build/**
    - **/CMakeFiles/**
    - **/*.o
    - **/*.a
    - **/*.gguf
    - **/*.safetensors
    - **/*.tar.zst
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
      # (12/10) prune: snapshots acumulavam desde 08-20 (9.9G medidos) —
      # mantém as 2 mais novas por coleção (nomes têm timestamp, sort basta).
      ${pkgs.curl}/bin/curl -s http://localhost:6333/collections/$col/snapshots | ${pkgs.jq}/bin/jq -r '.result[].name' | sort -r | tail -n +3 | while read snap; do
        ${pkgs.curl}/bin/curl -X DELETE http://localhost:6333/collections/$col/snapshots/$snap
      done
    done
  '';
  # (05/11) O corpo da sync como SCRIPT. O systemd NAO roda shell em
  # ExecStart: com o texto multi-linha, os operadores (||, if, fi) viravam
  # ARGUMENTOS do rclone ("Command lsd needs 1 arguments maximum") e a
  # unit morria com status=2/INVALIDARGUMENT. Mesmo padrao das units de voz.
  # (05/11) writeShellScriptBin (e nao writeShellScript): home.packages
  # usa buildEnv, que nao consegue mesclar um ARQUIVO (so diretorios).
  rclone-sync-script = pkgs.writeShellScriptBin "rclone-sync" ''
    set -euo pipefail
'''
      ${pkgs.rclone}/bin/rclone lsd gdrive:NixOS-Sync --max-depth 1 >/dev/null 2>&1 || {
        echo "rclone-sync: credencial do Drive invalida ou sem escopo (403 ACCESS_TOKEN_SCOPE_INSUFFICIENT) — refaca o OAuth com escopo drive.file: rclone config reconnect gdrive" >&2
        exit 1
      }
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
        --max-duration 4h \
        --log-level INFO
      # (04/11, sweep) O snapshot do Qdrant era criado e PRUNADO, mas o
      # rclone so copiava ~/projects → a memoria do JARVIS (memories/
      # code_index/books) ficava SO na maquina. Agora sai tambem.
      if [ -d /var/lib/qdrant/snapshots ]; then
        ${pkgs.rclone}/bin/rclone copy /var/lib/qdrant/snapshots gdrive:NixOS-Sync/04-qdrant-snapshots \
          --update \
          --fast-list \
          --tpslimit 10 \
          --transfers 2 \
          --checkers 4 \
          --retries 3 \
          --timeout 1h \
          --max-duration 90m \
          --exclude "*.lock" \
          --log-level INFO
      fi
      # (04/11, sweep) O vault (memoria de longo prazo do JARVIS) ficava
      # SO na maquina: o rclone so copiava ~/projects e ~/vaults esta fora
      # do escopo. Agora sai tambem — SEM o filtro global (que exclui
      # .git/: no vault o historico git E o backup).
      if [ -d /home/nixos/vaults ]; then
        ${pkgs.rclone}/bin/rclone copy /home/nixos/vaults gdrive:NixOS-Sync/05-vault \
          --update \
          --fast-list \
          --tpslimit 10 \
          --transfers 2 \
          --checkers 4 \
          --retries 3 \
          --timeout 1h \
          --max-duration 45m \
          --exclude "**/.obsidian/workspace*" \
          --exclude "**/.trash/**" \
          --log-level INFO
      fi
  '';
in {
  # (05/11) O script da sync PRECISA estar em home.packages: o ExecStart
  # do unit é um arquivo de TEXTO com um caminho do store dentro — e o
  # GC não enxerga essa referência (o path não vira dependência da
  # closure). Resultado: o script era coletado e a unit morria com
  # 203/EXEC. Em home.packages a closure segura o path ✓ (o mesmo
  # motivo do qdrant-snapshot estar aqui).
  home.packages = [pkgs.rclone qdrant-snapshot rclone-sync-script];

  xdg.configFile."rclone/filters.txt".source = filterFile;


  systemd.user.services.rclone-sync = {
    Unit = {
      Description = "Sync Inteligente Rclone para Google Drive (Projects & Qdrant)";
      After = ["network-online.target"];
    };
    Service = {
      Type = "oneshot";
      # (04/11, sweep) A unit ficava 'activating' por 1d19h e o timer
      # travava em 'running' (nunca re-armava): o rclone tentava arquivo a
      # arquivo (403 sem escopo OAuth) sem limite de tempo. Timeout + teto
      # de duração: o backup falha VISÍVEL em vez de ficar pendurado.
      TimeoutStartSec = "6h";
      ExecStartPre = "-${qdrant-snapshot}/bin/qdrant-snapshot";
      ExecStart = "${rclone-sync-script}/bin/rclone-sync";
    };
  };

  systemd.user.timers.rclone-sync = {
    Unit.Description = "Timer do Sync Inteligente de Projects";
    Timer = {
      OnCalendar = "*-*-* 00/4:00:00";
      Persistent = true;
      # (04/11) re-arma a partir do FIM da execução (a unit podia ficar
      # horas ativa); com OnCalendar+Persistent o proximo disparo e diario.
      OnUnitInactiveSec = "30min";
    };
    Install.WantedBy = ["timers.target"];
  };
}
