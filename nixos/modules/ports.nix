# Módulo NixOS para gerenciamento centralizado de portas
#
# Este módulo fornece gerenciamento de portas centralizado para todos os
# hosts do nixos-ai. Define portas padrão para serviços de IA (qdrant,
# llama-cpp, mcp) com suporte a overrides por host.
#
# Usage em configuration.nix:
#   imports = [ ./modules/ports.nix ];
#
#   ports = {
#     enable = true;
#     definitions = {
#       qdrant = 6333;
#       llama-cpp = 8080;
#       mcp = 3000;
#     };
#     hostOverrides = {
#       nitro-v15 = { qdrant = 6334; };
#     };
#   };
#
#   # Usar portas em serviços:
#   services.qdrant.settings.config.apiKey = "...";
#   services.qdrant.settings.config.listener = {
#     type = "http";
#     address = "0.0.0.0";
#     port = config.ports.get "qdrant";
#   };
{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.ports;

  portsLib = import "${./../../lib/ports.nix}" {inherit lib;};

  portHelpers =
    if cfg.enable
    then
      portsLib.mkPortHelpers {
        ports = cfg.definitions;
        hostPorts = cfg.hostOverrides;
      }
    else null;
in {
  options.ports = {
    enable = lib.mkEnableOption "gerenciamento centralizado de portas";

    definitions = lib.mkOption {
      type = lib.types.attrsOf lib.types.port;
      default = {
        qdrant = 6333;
        llama-cpp = 8080;
        mcp = 3000;
      };
      description = "Definições padrão de portas para serviços.";
    };

    hostOverrides = lib.mkOption {
      type = lib.types.attrsOf (lib.types.attrsOf lib.types.port);
      default = {};
      description = "Overrides de portas por host.";
    };

    currentHost = lib.mkOption {
      type = lib.types.str;
      default = config.networking.hostName;
      description = "Hostname usado para resolução de portas.";
    };

    # Função para obter porta de um serviço
    get = lib.mkOption {
      type = lib.types.functionTo lib.types.nullOr lib.types.port;
      readOnly = true;
      description = "Função para obter porta de um serviço com override por host.";
    };

    # Todas as portas para o host atual
    all = lib.mkOption {
      type = lib.types.attrsOf lib.types.port;
      readOnly = true;
      description = "Todas as portas para o host atual (defaults + overrides).";
    };
  };

  config = lib.mkIf cfg.enable {
    ports = {
      get = service: portHelpers.getPort service cfg.currentHost;
      all = portHelpers.getHostPorts cfg.currentHost;
    };

    # Exporta portas como JSON para scripts
    environment.etc = let
      portsJson = pkgs.writeText "ports.json" (builtins.toJSON cfg.all);
    in {
      "ports.json".source = portsJson;
    };
  };
}
