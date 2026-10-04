# Serviços LLM diretos GERADOS de models.nix directServers (fonte única!).
# Nada literal aqui além do mapeamento: flags, portas, modelos, memórias
# e wanted vêm de pkgs.aiModels.directServers. Conflicts calculado sobre
# o conjunto = um LLM grande por vez na VRAM 6GB (disciplina do dono).
{ config, pkgs, lib, ... }:
with lib;
let
  servers = pkgs.aiModels.directServers;
  names = attrNames servers;
  binFor = b:
    if b == "ik" then
      "/home/nixos/projects/ik_llama.cpp/build/bin/llama-server"
    else
      "${pkgs.llama-cpp}/bin/llama-server";
  ldFor = b:
    optionalAttrs (b == "ik") {
      LD_LIBRARY_PATH = "/home/nixos/projects/ik_llama.cpp/build/bin:${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.openssl.out}/lib:${pkgs.cudaPackages.cuda_cudart}/lib:${pkgs.cudaPackages.libcublas.lib}/lib:/run/opengl-driver/lib";
    };
  mkDirect = name: s: {
    description = "LLM direct ${name} (:${toString s.port}) — gerado de models.nix";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    partOf = [ "jarvis.target" ];
    wantedBy = optionals s.wanted [ "jarvis.target" "multi-user.target" ];
    conflicts =
      map (n: "llama-${n}.service") (filter (n: n != name) names);
    environment = ldFor s.binary;
    script = ''
      exec ${binFor s.binary} \
        -m ${s.modelFile} \
        --host 127.0.0.1 --port ${toString s.port} \
        -ngl ${toString s.gpuLayers} -t ${toString s.threads} \
        -c ${toString s.ctxSize} -b ${toString s.batchSize} \
        -ub ${toString s.ubatch} \
        ${optionalString (s.moeFlags != "") s.moeFlags} \
        -fa ${if s.fa then "on" else "off"} -ctk ${s.ctk} -ctv ${s.ctv} \
        ${escapeShellArgs s.extraArgs}
    '';
    serviceConfig = {
      User = "nixos";
      Restart = "on-failure";
      RestartSec = "20";
      StartLimitIntervalSec = 600;
      StartLimitBurst = 4;
      MemoryHigh = s.memHigh;
      MemoryMax = s.memMax;
      OOMScoreAdjust = 1000;
      TasksMax = 64;
    } // optionalAttrs s.limitMemlock { LimitMEMLOCK = "infinity"; };
  };
in
{
  systemd.services = mapAttrs' (n: s: nameValuePair "llama-${n}" (mkDirect n s)) servers;
}
