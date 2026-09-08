{
  config,
  pkgs,
  lib,
  ...
}:
with lib; let
  routing = pkgs.aiModels.routing;
  envName = config.services.jarvis.environment; # "host" | "vm"

  # Presets habilitados neste ambiente — ÚNICA FONTE: models.nix `routing`.
  enabledPresets = filterAttrs (id: m: m.serve.${envName} or false) routing.models;

  # Router roda UM binário: se qualquer preset exige o fork Prism
  # (bonsai Q2_0 g64), o router inteiro usa o wrapper Prism.
  needsPrism = any (m: m.needsWrapper != null) (attrValues enabledPresets);
  routerBin =
    if needsPrism
    then "${../ai}/llama-prism-wrapper.sh"
    else "${pkgs.llama-cpp.override {cudaSupport = true;}}/bin/llama-server";

  # Perfil de execução do preset (variante VM quando declarada).
  presetProfile = m:
    pkgs.aiModels.profiles.${if envName == "vm" && m ? profileVm then m.profileVm else m.profile};

  # kvCache ("-fa on -ctk q4_0 -ctv q4_0") → chaves INI/CLI. Falha no eval
  # (não em runtime) se aparecer um formato novo — honestidade > adivinhação.
  parseKv = kv: let
    mm = builtins.match "-fa ([a-z]+) -ctk ([a-z0-9_]+) -ctv ([a-z0-9_]+)" kv;
  in
    if mm == null
    then throw "llama-cpp router: kvCache com formato inesperado: ${kv}"
    else {
      flash-attn = builtins.elemAt mm 0;
      cache-type-k = builtins.elemAt mm 1;
      cache-type-v = builtins.elemAt mm 2;
    };

  # moeFlags só nas formas "" ou "--n-cpu-moe N" nos presets roteados
  # (bonsai/qwen-fast/chat/vm). Flag exótica (split-mode/poll/EHS) exige
  # estender o parser — throw explícito em vez de dropar silencioso.
  parseMoe = flags:
    if flags == ""
    then null
    else let mm = builtins.match "--n-cpu-moe ([0-9]+)" flags; in
      if mm == null
      then throw "llama-cpp router: moeFlags não-portável p/ preset INI: ${flags}"
      else builtins.elemAt mm 0;

  # Uma seção [id] do preset INI (formato: README tools/server, "Model presets").
  mkPresetSection = id: m: let
    p = presetProfile m;
    kv = parseKv p.kvCache;
    moe = parseMoe p.moeFlags;
  in ''
    [${id}]
    model = ${pkgs.aiModels.${p.model}}
    ${optionalString (p ? mmproj && p.mmproj != null) "mmproj = ${pkgs.aiModels.${p.mmproj}}"}
    c = ${toString p.ctxSize}
    n-gpu-layers = ${toString p.gpuLayers}
    jinja = true
    ${optionalString (moe != null) "n-cpu-moe = ${moe}"}
    ${concatStringsSep "\n" (m.iniExtra or [])}
  '';

  presetIni = pkgs.writeText "jarvis-router-models.ini" ''
    version = 1

    [*]
    # Defaults globais (instâncias herdam CLI do router + isto; preset sobrescreve).
    jinja = true

    ${concatStringsSep "\n" (mapAttrsToList mkPresetSection enabledPresets)}
  '';

  # Valores comuns da linha do router: do modelo default (warmup + herança).
  defaultId = config.services.llama-cpp-server.defaultModel;
  defaultProf = presetProfile routing.models.${defaultId};
  defaultKv = parseKv defaultProf.kvCache;

  # Compila o llama-cpp com suporte a CUDA forçado.
  # Usa o `pkgs` já recebido pelo módulo (herda allowUnfree + overlay
  # definidos centralmente no flake.nix) — NÃO reimportar pkgs.path aqui.
  llamaCppPkg = pkgs.llama-cpp.override {cudaSupport = true;};
in {
  options.services = {
    llama-cpp-server = {
      enable = mkEnableOption "Llama.cpp Main Server";
      port = mkOption {
        type = types.port;
        default = 8080;
      };
      # Router nativo (llama-server --models-preset): default EFETIVO
      # preservado por ambiente — host servia bonsai, lab servia vm/Qwen.
      # Trocar o default (ex.: p/ jarvis-fast) é decisão de produto (§21).
      defaultModel = mkOption {
        type = types.enum (attrNames routing.models);
        default =
          if envName == "host"
          then routing.default
          else "jarvis-fast";
        description = ''
          Modelo carregado no boot (warmup) e usado quando o request não
          especifica `model`. IDs e capabilities em modules/ai/models.nix
          (routing). O router atende qualquer preset via campo `model` do
          request, com load/unload sob demanda (max 1 residente — VRAM 6GB).
        '';
      };
      extraFlags = mkOption {
        type = types.listOf types.str;
        default = ["--jinja"];
      };
      bindAddress = mkOption {
        type = types.str;
        default = "127.0.0.1";
        description = ''
          Address to bind the llama-server HTTP endpoint.
          Default: 127.0.0.1 (loopback only — local inference, not exposed).
          Set to "0.0.0.0" only when remote access is explicitly needed.
        '';
      };
    };
    llama-cpp-embeddings = {
      enable = mkEnableOption "Llama.cpp Embeddings Server";
      port = mkOption {
        type = types.port;
        default = 8081;
      };
    };
    llama-cpp-rerank = {
      enable = mkEnableOption "Llama.cpp Rerank Server";
      port = mkOption {
        type = types.port;
        default = 8082;
      };
    };
  };

  config = mkIf (
    config.services.jarvis.enable
    && (config.services.llama-cpp-server.enable || config.services.llama-cpp-embeddings.enable || config.services.llama-cpp-rerank.enable)
  ) {
    # Registry derivado de models.nix (routing): Python lê via
    # /etc/jarvis/model-registry.json (override: JARVIS_MODEL_REGISTRY).
    # Mesma fonte que gera o preset INI acima — sem dict duplicado.
    environment.etc."jarvis/model-registry.json".text = pkgs.aiModels.registryJson;
    systemd.services = {
      llama-cpp-server = mkIf config.services.llama-cpp-server.enable {
        description = "Llama.cpp Router (presets: ${concatStringsSep ", " (attrNames enabledPresets)}; default: ${defaultId})";
        after = ["network-online.target" "qdrant.service"];
        wants = ["network-online.target"];
        # PartOf jarvis.target: para junto com o ecossistema
        partOf = ["jarvis.target"];
        wantedBy = ["jarvis.target" "multi-user.target"];
        # Router Prism (binário fora do store) precisa das libs de runtime
        # via Environment — precedente: llama-wackmall-wrapper.sh.
        environment = optionalAttrs needsPrism {
          LD_LIBRARY_PATH = "/home/nixos/projects/prism-bin/llama-prism-b10660-e311ed3:${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.openssl.out}/lib:${pkgs.cudaPackages.cuda_cudart}/lib:${pkgs.cudaPackages.libcublas.lib}/lib:/run/opengl-driver/lib";
        };

        script = ''
          exec ${routerBin} \
            --host ${config.services.llama-cpp-server.bindAddress} --port ${toString config.services.llama-cpp-server.port} \
            --models-preset ${presetIni} \
            --models-max ${toString routing.maxResident} \
            -t ${toString defaultProf.threads} -b ${toString defaultProf.batchSize} -ub ${toString defaultProf.ubatch} \
            -fa ${defaultKv.flash-attn} -ctk ${defaultKv.cache-type-k} -ctv ${defaultKv.cache-type-v} \
            --parallel 1 \
            ${escapeShellArgs config.services.llama-cpp-server.extraFlags}
        '';

        # Warmup best-effort do default: preserva o comportamento boot-ready
        # do servidor single-model (sem isso, o 1º chat após reboot pagaria
        # o cold start). Falha aqui NÃO derruba o serviço (on-demand cobre).
        postStart = ''
          ${pkgs.python3}/bin/python3 - "${toString config.services.llama-cpp-server.port}" "${defaultId}" <<'EOF' || echo "router warmup: modelo sob demanda (cold start no 1o request)" >&2
          import json, sys, time, urllib.request
          port, model = sys.argv[1], sys.argv[2]
          base = f"http://127.0.0.1:{port}"
          def call(path, payload=None):
              req = urllib.request.Request(base + path,
                  data=json.dumps(payload).encode() if payload else None,
                  headers={"Content-Type": "application/json"})
              with urllib.request.urlopen(req, timeout=30) as r:
                  return json.load(r)
          try:
              call("/models/load", {"model": model})
          except Exception as e:
              print(f"router warmup: load falhou ({e})", file=sys.stderr)
              sys.exit(0)
          for _ in range(150):  # até 5min (MoE 20GB)
              try:
                  data = call("/v1/models")
                  for m in data.get("data", []):
                      if m.get("id") == model and (m.get("status") or {}).get("value") == "loaded":
                          print(f"router warmup: {model} loaded")
                          sys.exit(0)
              except Exception:
                  pass
              time.sleep(2)
          print(f"router warmup: timeout aguardando {model} (on-demand cobre)", file=sys.stderr)
          EOF
        '';

        serviceConfig =
          {
            User = "nixos";
            Restart = "on-failure";
          };
      };

      llama-cpp-embeddings = mkIf config.services.llama-cpp-embeddings.enable {
        description = "Llama.cpp Embeddings Server";
        after = ["network-online.target" "qdrant.service"];
        wants = ["network-online.target"];
        partOf = ["jarvis.target"];
        wantedBy = ["jarvis.target"];
        script = ''
          exec ${pkgs.llama-cpp}/bin/llama-server \
            -m "${pkgs.aiModels.embed}" \
            --host 127.0.0.1 --port ${toString config.services.llama-cpp-embeddings.port} \
            --embeddings --pooling mean -c 4096 -t 2 -b 2048 -ub 1024
        '';
        serviceConfig = {
          User = "nixos";
          Restart = "on-failure";
          # ── Sandboxing ──
          ProtectSystem = "strict";       # /usr e /boot read-only
          PrivateTmp = true;                # /tmp privado
          NoNewPrivileges = true;           # Sem escalada de privilégio
          RestrictSUIDSGID = true;          # Sem arquivos SUID/SGID
          # ── Resource limits ──
          # Embeddings OOM-killed 2x em 2026-09-05 com 512M (mmap 42G
          # virtual no compute buffer). 2G comporta modelo + buffers.
          MemoryMax = "2G";               # Max 2GB RAM (model 512MB + buffers)
          TasksMax = 32;                  # Max 32 tasks
        };
      };

      llama-cpp-rerank = mkIf config.services.llama-cpp-rerank.enable {
        description = "Llama.cpp Rerank Server";
        after = ["network-online.target"];
        wants = ["network-online.target"];
        partOf = ["jarvis.target"];
        wantedBy = ["jarvis.target"];
        environment.CUDA_VISIBLE_DEVICES = "";
        script = ''
          exec ${pkgs.llama-cpp}/bin/llama-server \
            -m "${pkgs.aiModels.reranker}" \
            --host 127.0.0.1 --port ${toString config.services.llama-cpp-rerank.port} \
            --rerank -t 2 -c 8192 -b 512 -ub 512
        '';
        serviceConfig = {
          User = "nixos";
          # ── Sandboxing ──
          ProtectSystem = "strict";       # /usr e /boot read-only
          PrivateTmp = true;                # /tmp privado
          NoNewPrivileges = true;           # Sem escalada de privilégio
          RestrictSUIDSGID = true;          # Sem arquivos SUID/SGID
          # ── Resource limits ──
          MemoryMax = "1G";                 # Max 1GB RAM (model is 438MB)
          TasksMax = 64;                    # Max 64 tasks (threads)
        };
      };
    };
  };
}
