# Serviços dos modelos uncensored diretos (:8084 MoE 35B, :8092 4B).
# Motivo (03/10): 5 OOM-kills em processos manuais (nohup, sem cgroup) +
# 3 load-fails (VRAM curta, mlock RLIMIT). Service = MemoryMax (OOM só
# dentro da cgroup, sem freeze global) + Restart (auto-revive) +
# LimitMEMLOCK (mlock sem prlimit manual). Partida no boot (wantedBy).
{ config, pkgs, lib, ... }:
with lib;
{
  systemd.services = {
    llama-uncensored-35b = {
      description = "Qwen3.6-35B MoE Uncensored (ik_llama.cpp, :8084)";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      partOf = [ "jarvis.target" ];
      wantedBy = [ "jarvis.target" "multi-user.target" ];
      # Binário fora do store: libs via Environment (precedente llama-cpp.nix).
      environment.LD_LIBRARY_PATH = "/home/nixos/projects/ik_llama.cpp/build/bin:${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.openssl.out}/lib:${pkgs.cudaPackages.cuda_cudart}/lib:${pkgs.cudaPackages.libcublas.lib}/lib:/run/opengl-driver/lib";
      script = ''
        exec /home/nixos/projects/ik_llama.cpp/build/bin/llama-server \
          -m /home/nixos/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf \
          --host 127.0.0.1 --port 8084 \
          -ngl 45 --n-cpu-moe 35 -t 6 -c 8192 -fa on -ctk q4_0 -ctv q4_0 \
          -b 512 -ub 512 --parallel 1 --jinja --mlock --reasoning off
      '';
      serviceConfig = {
        User = "nixos";
        Restart = "on-failure";
        RestartSec = "30";
        StartLimitIntervalSec = 600;
        StartLimitBurst = 3;
        LimitMEMLOCK = "infinity";
        # Pico medido ~21-22GB RSS: 23G mata spike fugitivo, não o load.
        MemoryHigh = "21G";
        MemoryMax = "23G";
        OOMScoreAdjust = 1000;
        TasksMax = 64;
      };
    };

    llama-uncensored-4b = {
      description = "Qwen3.5-4B Uncensored (upstream stock CPU, :8092)";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      partOf = [ "jarvis.target" ];
      wantedBy = [ "jarvis.target" "multi-user.target" ];
      script = ''
        exec ${pkgs.llama-cpp}/bin/llama-server \
          -m /home/nixos/models/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf \
          --host 127.0.0.1 --port 8092 \
          -ngl 0 -t 6 -c 32768 -fa on -ctk q4_0 -ctv q4_0 \
          -b 512 -ub 512 --parallel 1 --jinja --reasoning off
      '';
      serviceConfig = {
        User = "nixos";
        Restart = "on-failure";
        RestartSec = "10";
        StartLimitIntervalSec = 600;
        StartLimitBurst = 5;
        MemoryHigh = "3G";
        MemoryMax = "4G";
        OOMScoreAdjust = 1000;
        TasksMax = 64;
      };
    };
  };
}
