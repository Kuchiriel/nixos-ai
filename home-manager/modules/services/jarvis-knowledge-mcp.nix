{
  config,
  lib,
  pkgs,
  ...
}: {
  # (07/11/2026) O JARVIS em MCP HTTP (streamable-http) na tailnet — RAG,
  # memória, lições e vault para agentes de OUTRA máquina.
  #
  # POR QUE (dono): "combinar expor tools jarvis para uso dele como rag,
  # memory e tudo que for util que temos". O MCP do JARVIS é stdio ⇒ só
  # alcança quem está na mesma máquina. As lanes do Windows, do Termux e do
  # celular estão em outras máquinas ⇒ precisam do endpoint HTTP.
  #
  # O padrão é o coord-mcp (mesmo repo, mesma técnica): FastMCP
  # streamable-http, bind no IP do TAILNET (nunca 0.0.0.0), proteção pela ACL
  # do Tailscale (o FastMCP remove o header Authorization antes das tools ⇒
  # senha por header não trava de verdade — medido em 05/11).
  options.services.jarvis.knowledgeMcp = {
    enable = lib.mkEnableOption "MCP de conhecimento do JARVIS em HTTP (RAG/memória/lições/vault, tailnet)";
    host = lib.mkOption {
      type = lib.types.str;
      default = "100.121.100.103";
      description = "IP do tailnet onde o MCP escuta (NÃO use 0.0.0.0).";
    };
    hostV6 = lib.mkOption {
      type = lib.types.str;
      default = "fd7a:115c:a1e0::7f01:64bd";
      description = "Endereco IPv6 do tailnet onde o MCP tambem escuta (15/11: do celular so o IPv6 responde).";
    };
    port = lib.mkOption {
      type = lib.types.port;
      default = 8766;
      description = "Porta do MCP (endpoint /mcp).";
    };
  };

  config = lib.mkIf config.services.jarvis.knowledgeMcp.enable {
    # (15/11, crouton-alpha) Segunda instancia no IPv6 do tailnet: do
    # celular so o IPv6 responde (a rota IPv4 celular->PC esta morta), e
    # sem isso o MCP de conhecimento (RAG/memoria/licoes) ficava
    # inacessivel do bolso. Bind no endereco do TAILNET (nao 0.0.0.0).
    systemd.user.services.jarvis-knowledge-mcp-v6 = {
      Unit = {
        Description = "JARVIS — MCP de conhecimento em HTTP (tailnet IPv6)";
        After = [ "network-online.target" ];
        Wants = [ "network-online.target" ];
      };
      Install.WantedBy = [ "default.target" ];
      Service = {
        Type = "simple";
        ExecStart = lib.concatStringsSep " " [
          "/home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-http-launcher.sh"
          "--host"
          config.services.jarvis.knowledgeMcp.hostV6
          "--port"
          (toString config.services.jarvis.knowledgeMcp.port)
        ];
        Restart = "always";
        RestartSec = "5s";
        StandardOutput = "journal";
        StandardError = "journal";
      };
    };

    systemd.user.services.jarvis-knowledge-mcp = {
      Unit = {
        Description = "JARVIS — MCP de conhecimento em HTTP (RAG/memória/lições/vault, tailnet)";
        After = [ "network-online.target" ];
        Wants = [ "network-online.target" ];
      };
      Install.WantedBy = [ "default.target" ];
      Service = {
        Type = "simple";
        ExecStart = lib.concatStringsSep " " [
          "/home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-http-launcher.sh"
          "--host"
          config.services.jarvis.knowledgeMcp.host
          "--port"
          (toString config.services.jarvis.knowledgeMcp.port)
        ];
        Restart = "always";
        RestartSec = "5s";
        StandardOutput = "journal";
        StandardError = "journal";
      };
    };
  };
}
