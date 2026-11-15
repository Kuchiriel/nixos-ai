{ config, lib, pkgs, ... }:
# agent-hub — mission control dos agentes do nitro-v15 (14/11/2026, crouton-alpha).
#
# POR QUE: o dono pediu ver e comandar os agentes de fora (celular), e o
# bus (GitHub issue) nao acorda ninguem — precisa entrar no PROMPT da sessao.
# O hub le o roster local + a API do opencode (loopback) e expoe:
#   GET  /api/agents                 roster + busy + status
#   GET  /api/transcript?session=S   ultimas mensagens da sessao
#   POST /api/wake                   injeta prompt na sessao do peer
#
# NAO é serviço do sistema: é user service, porta 8091, bind '::' (dual-stack:
# LAN + tailnet v4/v6). O script vive no repo (caminho vivo, igual ao
# agents-watcher): editar o script nao pede rebuild, so o restart do unit.
#
# O forward tailnet-v4-8090 existe porque o jarvis-webui (servico NixOS) so
# escuta em 127.0.0.1:8090 por design (nao expor chaves de API na LAN). O
# forward abre 100.121.100.103:8090 (tailnet IPv4) -> 127.0.0.1:8090, e a
# firewall do host (configuration.nix) libera 5173/8090/8091 so no tailscale0
# e na LAN.
{
  systemd.user.services.agent-hub = {
    Unit = {
      Description = "Agent Hub — mission control remoto do opencode no nitro-v15";
      After = [ "network.target" ];
    };
    Service = {
      Type = "simple";
      WorkingDirectory = "/home/nixos/projects/nixos-ai";
      ExecStart = "${pkgs.nodejs}/bin/node /home/nixos/projects/nixos-ai/scripts/agent-hub.mjs";
      Restart = "on-failure";
      RestartSec = "3";
      Environment = "PORT=8091";
    };
    Install = {
      WantedBy = [ "default.target" ];
    };
  };

  systemd.user.services.tailnet-v4-8090 = {
    Unit = {
      Description = "Forward Tailscale IPv4 100.121.100.103:8090 -> 127.0.0.1:8090 (webui backend)";
      After = [ "network.target" ];
    };
    Service = {
      Type = "simple";
      ExecStart = "${pkgs.nodejs}/bin/node /home/nixos/projects/nixos-ai/scripts/tailnet-v4-8090.mjs";
      Restart = "on-failure";
      RestartSec = "3";
    };
    Install = {
      WantedBy = [ "default.target" ];
    };
  };
}
