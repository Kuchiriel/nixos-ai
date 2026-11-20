{ config, lib, pkgs, ... }:
# (20/11) Descoberta dinâmica da frota, sem hardcode de host/agente.
# Usa Tailscale, mDNS, ARP, ICMP, TCP, HTTPS, SNMP e os blocos coord-json do
# bus para descobrir peers e agentes. Estado append-only + A/B por método.
{
  systemd.user.services.fleet-discovery = {
    Unit = {
      Description = "JARVIS — descoberta dinâmica de hosts e agentes da frota";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };
    Service = {
      Type = "oneshot";
      WorkingDirectory = "/home/nixos/projects/nixos-ai";
      ExecStart = "/run/current-system/sw/bin/bash -c 'source /home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-env.sh && \"$JARVIS_PY\" /home/nixos/projects/nixos-ai/scripts/fleet-discover.py --write-state --write-manifests \"$HOME/.local/state/jarvis/fleet-discovery/manifests\" >/dev/null'";
      Nice = 10;
      IOSchedulingClass = "idle";
      TimeoutStartSec = 180;
    };
  };

  systemd.user.timers.fleet-discovery = {
    Unit = {
      Description = "Descoberta periódica da frota (hosts, portas, agentes)";
    };
    Timer = {
      OnBootSec = "2min";
      OnUnitActiveSec = "10min";
      Persistent = true;
      RandomizedDelaySec = 30;
    };
    Install = {
      WantedBy = [ "timers.target" ];
    };
  };
}
