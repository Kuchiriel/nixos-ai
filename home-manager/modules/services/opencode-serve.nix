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
      EnvironmentFile = "${config.home.homeDirectory}/.config/opencode/server.env";
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
  home.activation."opencode-server-env" = lib.mkIf true ''
    envFile="$HOME/.config/opencode/server.env"
    if [ ! -f "$envFile" ]; then
      mkdir -p "$(dirname "$envFile")"
      umask 077
      pw="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
      printf 'export OPENCODE_SERVER_PASSWORD=%s\n' "$pw" > "$envFile"
      chmod 600 "$envFile"
    fi
  '';
}