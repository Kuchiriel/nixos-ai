{ config, lib, pkgs, ... }:
let
  cfg = config.services.vision-siglip;
in
{
  options.services.vision-siglip = {
    enable = lib.mkEnableOption "SigLIP + MLP local vision model (sprite classification)";

    port = lib.mkOption {
      type = lib.types.int;
      default = 8099;
      description = "TCP port to listen on for vision API requests.";
    };

    modelPath = lib.mkOption {
      type = lib.types.path;
      default = /home/nixos/models/siglip;
      description = "Path to SigLIP model directory.";
    };

    mlpWeightsPath = lib.mkOption {
      type = lib.types.path;
      default = /home/nixos/models/siglip-mlp-alvos;
      description = "Path to fine-tuned MLP weights file.";
    };

    batchSize = lib.mkOption {
      type = lib.types.int;
      default = 4;
      description = "Batch size for inference.";
    };

    # Whether to use GPU if available
    useGPU = lib.mkOption {
      type = lib.types.bool;
      default = lib.mkIf config.boot.kernelModules.nvidia;
      description = "Use GPU for inference if available.";
    };
  };

  config = lib.mkIf cfg.enable {
    # Ensure Python and required packages are available
    environment.systemPackages = with pkgs; [
      python3
      python3Packages.pillow
      python3Packages.torch
      python3Packages.torchvision
      python3Packages.transformers
      python3Packages.numpy
    ];

    # Create service user and group
    users.users.vision-siglip = {
      isSystemAccount = true;
      description = "SigLIP vision service user";
      extraGroups = [ "video" ]; # For GPU access if needed
    };

    # Service configuration
    systemd.services.vision-siglip = {
      description = "SigLIP + MLP Vision Service for Sprite Classification";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        User = "vision-siglip";
        Group = "vision-siglip";
        ExecStart = pkgs.writeShellApplication "vision-siglip-server" ''
          #!${pkgs.runtimeShell}
          export PYTHONPATH="${pkgs.python3}/lib/python3.${pkgs.python3.version}/site-packages"
          
          # Check if GPU should be used
          USE_GPU="${if cfg.useGPU then "true" else "false"}"
          
          # Start the vision server
          exec ${pkgs.python3}/bin/python ${toString cfg.modelPath}/vision_server.py \\
            --model-path ${toString cfg.modelPath} \\
            --mlp-weights ${toString cfg.mlpWeightsPath} \\
            --port ${toString cfg.port} \\
            --batch-size ${toString cfg.batchSize} \\
            ${if cfg.useGPU then "--use-gpu" else ""}
        '';
        Restart = "on-failure";
        RestartSec = 5;
        StartLimitIntervalSec = 60;
        StartLimitBurst = 5;
      };
    };

    # Firewall configuration
    networking.firewall.allowedTCPPorts = [ cfg.port ];
  };
}
