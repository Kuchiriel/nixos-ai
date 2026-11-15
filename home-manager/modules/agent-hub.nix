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
    # (14/11) force: os units existiam como arquivos manuais; sem force o HM
    # aborta a ativacao ("would be clobbered").
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
      # (15/11) BIND=:: de proposito: o TOKEN continua obrigatorio nas rotas
      # sensiveis (transcript/wake) — o padrao do script e loopback, mas o
      # dono precisa abrir o hub do celular (IPv6 da tailnet). Sem token
      # no servidor, as rotas sensiveis recusam (fail-closed).
      Environment = "PORT=8091";
      Environment = "BIND=::";
    };
    Install = {
      WantedBy = [ "default.target" ];
    };
  };

  # O HM aborta a ativacao ("would be clobbered") quando o unit ja existe como
  # arquivo solto em ~/.config/systemd/user (install manual de 14/11). Padrao
  # DA CASA (bench-nightly): um activation move os arquivos antigos para o
  # estado (NAO apaga — fica como evidencia) e o HM cria o symlink.
  home.activation."a-migrate-legacy-agent-hub-units" = lib.mkIf true
    (lib.hm.dag.entryBefore [ "checkFilesChanged" ] ''
      legacy_dir="$HOME/.local/state/jarvis/legacy-agent-hub-units-2026-11-14"
      mkdir -p "$legacy_dir"
      for f in agent-hub.service tailnet-v4-8090.service; do
        p="$HOME/.config/systemd/user/$f"
        if [ -e "$p" ] && [ ! -L "$p" ]; then
          mv "$p" "$legacy_dir/$f"
        fi
        w="$HOME/.config/systemd/user/default.target.wants/$f"
        if [ -e "$w" ] && [ ! -L "$w" ]; then
          mkdir -p "$legacy_dir/default.target.wants"
          mv "$w" "$legacy_dir/default.target.wants/$f"
        fi
      done
    '');

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
