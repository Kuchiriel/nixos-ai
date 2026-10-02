{ config, lib, pkgs, ... }:
{
  # opencode-serve — servidor headless do opencode para o CELULAR (2026-10-02,
  # pedido do dono).
  #
  # POR QUE EXISTE: o dono trabalhava via TTY (ssh + `opencode`), onde cada
  # invocação é um processo dono da sessão — impossível ver/steerar de outro
  # lugar. Com UM servidor, vários clientes entram na MESMA sessão:
  #   - TUI:  opencode attach http://127.0.0.1:4599
  #   - Web:  http://100.121.100.103:4599 no celular (mesmo tailnet)
  #   - CLI:  opencode run / export
  # É isso que torna o celular um cliente de verdade em vez de uma sessão
  # paralela brigando pelo mesmo arquivo.
  #
  # SEGURANÇA (não negociável):
  #   - A senha vive em ~/.config/opencode/server.env (chmod 600, fora do git).
  #     Sem ela o servidor sobe "unsecured" e entrega as chaves de API da
  #     máquina a qualquer um que alcance a porta.
  #   - Escuta SÓ no IP do Tailscale, e a porta 4599 está liberada apenas em
  #     `interfaces.tailscale0` (hosts/nitro-v15/configuration.nix) — nunca na
  #     LAN. O tailnet já autentica por dispositivo.
  systemd.user.services.opencode-serve = {
    Unit = {
      Description = "opencode serve — acesso do celular via Tailscale";
      After = ["network-online.target"];
      Wants = ["network-online.target"];
    };
    Service = {
      Type = "simple";
      # SEM `export` no arquivo: o systemd EnvironmentFile recusa a linha e
      # loga o valor em texto claro no journal ("Ignoring invalid environment
      # assignment") — aí o servidor sobe UNSECURED e a senha fica no log.
      # Formato obrigatório: KEY=valor (gerado pela activation abaixo).
      EnvironmentFile = "${config.home.homeDirectory}/.config/opencode/server.env";
      # As sessões do opencode são escopadas por diretório. Com o serviço em
      # $HOME o servidor via só 1 sessão; em ~/projects ele vê as 90 — e é
      # nesta que a sessão do TUI mora, que é a que o celular vai Assumeir.
      WorkingDirectory = "${config.home.homeDirectory}/projects";
      # `kilo` é o nome do pacote opencode no overlay do flake (flake.nix:~108):
      # vem de nixpkgs-unstable, porque o opencode-nix do dan-online parou em
      # 2026-05. `pkgs.opencode` aqui devolveria a versão velha/inexistente.
      ExecStart = "${pkgs.kilo}/bin/opencode serve --hostname 100.121.100.103 --port 4599";
      Restart = "always";
      RestartSec = 3;
      # sem isto o opencode segura um terminal e o journal enche de lixo
      StandardOutput = "journal";
      StandardError = "journal";
    };
    Install.WantedBy = ["default.target"];
  };

  # O env da senha é gerado fora do git; cria se faltar para o serviço subir.
  # Rotaciona se o arquivo já tiver o prefixo `export` (que o systemd ignora e
  # loga em claro) — foi assim que a senha acabou no journal em 02/10/2026.
  home.activation."opencode-server-env" = lib.mkIf true ''
    envFile="$HOME/.config/opencode/server.env"
    if [ ! -f "$envFile" ] || grep -q '^export ' "$envFile"; then
      mkdir -p "$(dirname "$envFile")"
      umask 077
      pw="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
      printf 'OPENCODE_SERVER_PASSWORD=%s\n' "$pw" > "$envFile"
      chmod 600 "$envFile"
    fi
  '';
}