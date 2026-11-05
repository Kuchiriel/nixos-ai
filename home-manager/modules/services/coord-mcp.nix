{
  config,
  lib,
  pkgs,
  ...
}: {
  # (05/11) MCP de coordenação entre IAs por HTTP (streamable-http).
  #
  # POR QUE: o canal de bot-a-bot tem duas metades —
  #   1) o BUS global (coord-json no issue do GitHub): auditável, funciona
  #      entre maquinas sem rede direta;
  #   2) o CANAL DIRETO (este servidor): as ferramentas de roster/msg do
  #      outro host, sem depender de issue nem de CLI.
  # O transporte direto é HTTP porque a outra ponta é um opencode em outra
  # maquina (Windows), e o opencode só fala MCP remoto por URL.
  #
  # O host default é o IP do TAILNET desta maquina — NÃO 0.0.0.0: escutar
  # em 0.0.0.0 também expõe na LAN; a proteção é o Tailscale (o firewall
  # do tailscale só deixa o tailnet chegar).
  #
  # A unidade depende do `coord_http.py` (branch infra/coord-mcp, PR #2) e
  # do `fastmcp`, que existe no PERFIL do JARVIS (medido: 3.2.3) — o
  # launcher resolve o PYTHONPATH em runtime, sem adicionar dependência
  # ao package.nix.
  options.services.jarvis.coordMcp = {
    enable = lib.mkEnableOption "MCP de coordenação entre IAs (HTTP na tailnet)";
    host = lib.mkOption {
      type = lib.types.str;
      default = "100.121.100.103";
      description = "IP do tailnet onde o MCP escuta (NÃO use 0.0.0.0).";
    };
    port = lib.mkOption {
      type = lib.types.port;
      default = 8765;
      description = "Porta do MCP (endpoint /mcp).";
    };
    agent = lib.mkOption {
      type = lib.types.str;
      default = "jarvis@nitro-v15";
      description = "Identidade do agente dono deste servidor (COORD_AGENT).";
    };
  };

  config = lib.mkIf config.services.jarvis.coordMcp.enable {
    systemd.user.services.coord-mcp = {
      description = "JARVIS — MCP de coordenação entre IAs (streamable-http, tailnet)";
      # (05/11) after/wants no home-manager são ATTRSET
      # ({ "unidade" = true; }) — lista e string as duas quebram o build
      # ("not of type attribute set of ...").
      after = { "network-online.target" = true; };
      wants = { "network-online.target" = true; };
      wantedBy = [ "default.target" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = lib.concatStringsSep " " [
          "/home/nixos/projects/nixos-ai/modules/ai/jarvis/coord-mcp-launcher.sh"
          "--host"
          config.services.jarvis.coordMcp.host
          "--port"
          (toString config.services.jarvis.coordMcp.port)
        ];
        # (05/11) A identidade do agente que chama o MCP vem do env: sem
        # isso o coord_whoami cai no default e mostra o cartão de outro.
        Environment = {
          COORD_AGENT = config.services.jarvis.coordMcp.agent;
        };
        Restart = "always";
        RestartSec = "5s";
        # O MCP não escreve no stdout (é protocolo) → log no journal.
        StandardOutput = "journal";
        StandardError = "journal";
      };
    };
  };
}
