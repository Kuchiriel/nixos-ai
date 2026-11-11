{ config, lib, pkgs, ... }:
# Incremental indexing of opencode sessions into Qdrant `sessions`.
#
# WHY: keeps `jarvis_rehydrate`, `jarvis_session_resume`, and
# `jarvis_rag_search(collection="sessions")` current so agents can recover
# previous session state without re-deriving context.
#
# Source of truth: ~/.local/share/opencode/opencode.db (read-only).
# Output: Qdrant collection `sessions` (structured summaries, no raw transcript).
# State: ~/.local/state/jarvis/sessions-index-state.json (idempotent/incremental).
{
  systemd.user.services.jarvis-sessions-index = {
    Unit = {
      Description = "JARVIS — incremental index of opencode sessions into RAG (sessions collection)";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };
    Service = {
      Type = "oneshot";
      WorkingDirectory = "/home/nixos/projects/nixos-ai";
      # Use the same JARVIS runtime env as MCP/CLI (avoids diverging Python deps).
      ExecStart = "/run/current-system/sw/bin/bash -c 'source /home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-env.sh && exec \"$JARVIS_PY\" /home/nixos/projects/nixos-ai/scripts/index_opencode_sessions.py --incremental'";
      Nice = 10;
      IOSchedulingClass = "idle";
      TimeoutStartSec = 600;
    };
  };

  systemd.user.timers.jarvis-sessions-index = {
    Unit = {
      Description = "Periodically index new/updated opencode sessions for session recovery";
    };
    Timer = {
      OnBootSec = "10min";
      OnUnitActiveSec = "30min";
      Persistent = true;
      RandomizedDelaySec = 120;
    };
    Install = {
      WantedBy = [ "timers.target" ];
    };
  };
}
