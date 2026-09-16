# ═══ Audiobook Audit Timer — forensic audio auditor, todo dia 03:30 ═══
#
# Roda attrib-llm.py (persona forensic_audio_auditor) nos caps com UNKNOWNs
# + verify-v2 report. Não renderiza, não treina: só auditoria e tabelas.
# Relatórios em /tmp/audiobook-audit/ + caps/capNN-llm.json.
{ config, lib, pkgs, ... }:

{
  systemd.services.audiobook-audit = {
    description = "LOTM audiobook — forensic speaker attribution (nightly)";
    after = [ "llama-cpp-server.service" ];
    wants = [ "llama-cpp-server.service" ];
    serviceConfig = {
      Type = "oneshot";
      User = "nixos";
      Environment = [
        "LD_LIBRARY_PATH=/nix/store/3lpf2hl979sfmyb9f573xq1bz3xkds0v-cuda-merged-12.9/lib:/run/opengl-driver/lib:/nix/store/7vafhlh0lmcvi75jfyy09qwr4m3x1ks3-gcc-15.2.0-lib/lib:/nix/store/483x61iy35irm4wr2b7dwzihljhp6da2-zlib-1.3.2/lib"
        "PATH=/run/current-system/sw/bin:${pkgs.coreutils}/bin:${pkgs.gnugrep}/bin:${pkgs.findutils}/bin"
      ];
      ExecStart = "${pkgs.bash}/bin/bash /home/nixos/projects/applio-lab/scripts/nightly-audit.sh";
      WorkingDirectory = "/home/nixos/projects/applio-lab";
    };
  };
  systemd.timers.audiobook-audit = {
    description = "LOTM audiobook audit diário 01:00";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "01:00";
      Persistent = true;
    };
  };
}
