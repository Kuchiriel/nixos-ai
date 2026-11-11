{ config, lib, pkgs, ... }:
# Incremental indexing + consolidation of opencode sessions for recovery memory.
#
# WHY: keeps `jarvis_rehydrate`, `jarvis_session_resume`, and
# `jarvis_rag_search(collection="sessions")` current, and distills session
# summaries into durable episodic memories (`memories`) for recall/rehydrate.
#
# Source of truth: ~/.local/share/opencode/opencode.db (read-only).
# Output: Qdrant `sessions` summaries + consolidated `memories` facts (no raw transcript).
# State: ~/.local/state/jarvis/sessions-index-state.json and
#        ~/.local/state/jarvis/sessions-consolidation-state.json (idempotent).
{
  systemd.user.services.jarvis-sessions-index = {
    Unit = {
      Description = "JARVIS — incremental index+consolidation of opencode sessions (RAG sessions + memories)";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };
    Service = {
      Type = "oneshot";
      WorkingDirectory = "/home/nixos/projects/nixos-ai";
      # Use the same JARVIS runtime env as MCP/CLI (avoids diverging Python deps).
      # 1) refresh session summaries in Qdrant `sessions`  2) consolidate to durable `memories` facts.
      ExecStart = "/run/current-system/sw/bin/bash -c 'source /home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-env.sh && \"$JARVIS_PY\" /home/nixos/projects/nixos-ai/scripts/index_opencode_sessions.py --incremental && \"$JARVIS_PY\" /home/nixos/projects/nixos-ai/scripts/consolidate_sessions_memory.py --incremental'";
      Nice = 10;
      IOSchedulingClass = "idle";
      TimeoutStartSec = 900;
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
