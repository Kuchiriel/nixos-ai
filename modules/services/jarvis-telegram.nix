{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.jarvis-telegram;
in {
  options.services.jarvis-telegram = {
    enable = lib.mkEnableOption "Telegram control plane (remote interface for JARVIS missions)";

    environmentFile = lib.mkOption {
      type = lib.types.path;
      default = "/etc/jarvis-telegram.env";
      description = ''
        File holding the credentials (mode 600, outside the repo/store):
          JARVIS_TELEGRAM_TOKEN=<token from BotFather>
          JARVIS_TELEGRAM_CHAT_ID=<your chat_id, or a comma-separated list>
          JARVIS_TELEGRAM_USER_ID=<your user_id — REQUIRED when the bot is in a group>

        To find your chat_id: send a message to the bot and call
        https://api.telegram.org/bot<TOKEN>/getUpdates (field chat.id).
        To find your user_id: same call, field from.id.

        SECURITY: set JARVIS_TELEGRAM_USER_ID whenever the bot can be reached
        from a group. With only a chat id, ANY member of that chat is
        authorized to start missions and approve operations.

        The `-` prefix makes systemd IGNORE the file when absent: without a
        token the service stays stopped until you create the bot and fill the
        file, then `sudo systemctl restart jarvis-telegram`.
      '';
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Owner of the JARVIS state (memory/vault/audit/missions).";
    };

    # Mission state lives outside the Nix store so it survives rebuilds.
    stateDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/jarvis/missions";
      defaultText = "/var/lib/jarvis/missions";
      description = ''
        Durable mission store (one JSON per mission, atomic writes).
        Must be writable by `user` and must NOT live in the store: a rebuild
        would otherwise wipe in-flight missions.
      '';
    };

    # Resource ceiling. A mission runs one agent at a time; the pool is
    # bounded in-process (ThreadPoolExecutor max_workers=2 in the channel).
    memoryMax = lib.mkOption {
      type = lib.types.str;
      default = "4G";
      description = ''
        RAM ceiling for the channel. Deliberately larger than the old 256M:
        missions load the model registry and the task queue in-process, and
        256M was low enough to OOM-kill a mission mid-flight.
      '';
    };

    tasksMax = lib.mkOption {
      type = lib.types.int;
      default = 256;
      description = "Thread ceiling (bounded worker pool + polling).";
    };

    extraArgs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Extra arguments appended to `jarvis telegram`.";
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    # Persistent state, created declaratively with the right ownership.
    systemd.tmpfiles.rules = [
      "d ${cfg.stateDir} 0750 ${cfg.user} - -"
    ];

    systemd.services.jarvis-telegram = {
      description = "JARVIS — Telegram control plane (missions, approvals, notifications)";
      after = [ "network-online.target" "jarvis.target" ];
      wants = [ "network-online.target" ];
      partOf = [ "jarvis.target" ];
      wantedBy = [ "jarvis.target" ];
      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        Group = cfg.user;

        # Credentials come from files OUTSIDE the store, never inline.
        # litellm.env is needed for the API cascade (STUCK -> Groq); the bot
        # already runs as the same user, so the file's own permissions are
        # the boundary.
        EnvironmentFile = [
          "-${cfg.environmentFile}"
          "-/etc/litellm.env"
        ];
        Environment = [
          "JARVIS_MISSION_DIR=${cfg.stateDir}"
          "JARVIS_WORKSPACE_ROOT=/home/${cfg.user}/projects"
          "PYTHONUNBUFFERED=1"
        ];

        ExecStart = lib.concatStringsSep " " (
          [ "${pkgs.jarvis}/bin/jarvis" "telegram" ]
          # --poll-timeout keeps the long-poll responsive to systemd stop.
          ++ [ "--poll-timeout" "20" ]
          ++ cfg.extraArgs
        );

        # Reconnection is expected (network flaps, token rotation): restart
        # always, with a short delay so a broken token does not spin hot.
        Restart = "always";
        RestartSec = "10";
        # Enough for a long poll to return and the worker pool to wind down.
        TimeoutStopSec = "30";
        KillSignal = "SIGTERM";

        # ── Sandboxing ──
        # strict: /usr, /boot, /nix read-only. State dirs are explicitly
        # writable below — without those the service cannot persist missions.
        ProtectSystem = "strict";
        ReadWritePaths = [ cfg.stateDir "/home/${cfg.user}/.local/state/jarvis" ];
        PrivateTmp = true;
        NoNewPrivileges = true;
        RestrictSUIDSGID = true;
        RestrictRealtime = true;
        LockPersonality = true;

        # ── Resource limits ──
        MemoryMax = cfg.memoryMax;
        TasksMax = cfg.tasksMax;
      };
    };
  };
}