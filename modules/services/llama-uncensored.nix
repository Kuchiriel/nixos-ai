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
    else if b == "stock" then
      # llama.cpp v0.7.0 com CUDA (build local 17/10, sm_89): o único
      # binário comprovado que APLICA o LoRA em qwen35moe (o ik carrega
      # e não aplica — mismatch de nomes; o nixpkgs b9190 tem o arch
      # mas não foi validado p/ o duplex). Precedente: "ik" também é
      # build de repo. LD/rpath já embutidos (testes standalone ok).
      "/home/nixos/projects/llama.cpp/build-stock/bin/llama-server"
    else
      "${pkgs.llama-cpp}/bin/llama-server";
  ldFor = b:
    optionalAttrs (b == "ik" || b == "stock") {
      # (17/10) "stock" também precisa: SEM isto o serviço vê só a CUDA
      # STUB ("driver is a stub library") e roda 100% CPU — 434MB VRAM,
      # ticks de segundos, máquina travando. O driver de verdade vive em
      # /run/opengl-driver/lib (impuro por natureza, nunca no rpath).
      LD_LIBRARY_PATH =
        (if b == "ik"
        then "/home/nixos/projects/ik_llama.cpp/build/bin:"
        else "/home/nixos/projects/llama.cpp/build-stock/bin:")
        + "${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.openssl.out}/lib:${pkgs.cudaPackages.cuda_cudart}/lib:${pkgs.cudaPackages.libcublas.lib}/lib:/run/opengl-driver/lib";
    };
  # (24/10, lição do incidente 04:03) GUARD DE VRAM: restart de serviço
  # GPU pode falhar porque a instância ANTIGA ainda segura a memória
  # quando a nova alocava ("failed to fit params to free device memory,
  # n_gpu_layers already set by user, abort") — e nada reergue o wanted=
  # false. O guard espera a VRAM liberar (≤90s) antes de subir; se não
  # liberar, falha com mensagem LEGÍVEL no journal (não o cryptico do
  # llama-server).
  vramGuard = pkgs.writeShellScript "llama-vram-guard" ''
    NEED="''${1:-3000}"
    SMI=/run/current-system/sw/bin/nvidia-smi
    FREE=0
    for _ in $(seq 1 90); do
      FREE=$("$SMI" --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
      FREE="''${FREE:-0}"
      [ "$FREE" -ge "$NEED" ] && exit 0
      sleep 1
    done
    echo "vram-guard: FREE=''${FREE}MiB < NEED=''${NEED}MiB após 90s — outro processo segura a GPU (router/instância antiga?). Veja nvidia-smi." >&2
    exit 1
  '';

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
      # (24/10) espera VRAM liberar antes de alocar (v. vramGuard)
      ExecStartPre = [ "${vramGuard} ${toString (s.vramMinMiB or 3000)}" ];
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
