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
      # keys.env (2º item): o systemd user manager nunca lê .zshrc, então o
      # serve nascia sem NENHUMA chave ({env:} vazio → 401 em todo modelo
      # cloud pelo celular; medido 11/10: environ do PID sem API_KEY).
      # Gerado da /etc/litellm.env pela activation abaixo (formato KEY=valor,
      # chmod 600). Prefixo `-`: opcional — se a activation ainda não rodou,
      # o serve sobe (só com local), em vez de falhar o boot.
      EnvironmentFile = [
        "${config.home.homeDirectory}/.config/opencode/server.env"
        "-${config.home.homeDirectory}/.config/opencode/keys.env"
      ];
      # As sessões do opencode são escopadas por diretório. Com o serviço em
      # $HOME o servidor via só 1 sessão; em ~/projects ele vê as 90 — e é
      # nesta que a sessão do TUI mora, que é a que o celular vai Assumeir.
      WorkingDirectory = "${config.home.homeDirectory}/projects";
      # `kilo` é o nome do pacote opencode no overlay do flake (flake.nix:~108):
      # vem de nixpkgs-unstable, porque o opencode-nix do dan-online parou em
      # 2026-05. `pkgs.opencode` aqui devolveria a versão velha/inexistente.
      # Bind NO IP DO TAILNET, não 0.0.0.0 — defesa em profundidade. Testei
      # 0.0.0.0 com o firewall escopado em tailscale0 e o host respondeu no
      # próprio IP da LAN (192.168.15.9) com 200. Só que esse teste não prova
      # exposição: tráfego local-para-local entra por `lo`, e o NixOS aceita
      # `lo` sempre, furando a regra por interface. Bind no IP do tailnet
      # garante o isolamento independente do firewall (que segue como 2ª camada).
      # Consequência: o attach precisa usar o IP do Tailscale, não 127.0.0.1.
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
      # caminho ABSOLUTO: a activation roda com PATH mínimo e `python3` não
      # existe lá (2026-10-02: "line 416: python3: command not found").
      pw="$(${pkgs.python3}/bin/python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
      printf 'OPENCODE_SERVER_PASSWORD=%s\n' "$pw" > "$envFile"
      chmod 600 "$envFile"
    fi
  '';

  # keys.env p/ o serve (11/10): espelha /etc/litellm.env em formato KEY=valor
  # (sem `export` — systemd recusa e loga em claro). Roda TODA activation, então
  # rotação de chave no /etc/litellm.env propaga no próximo switch/login.
  # Se a fonte estiver ilegível (foi assim 11/10: chmod 600 pelo agente do
  # driver → shell sem chave → 401 em tudo), AVISA no stderr mas não quebra a
  # activation; o serve sobe sem chaves cloud (só local) até o próximo switch.
  home.activation."opencode-keys-env" = lib.mkIf true ''
    keysFile="$HOME/.config/opencode/keys.env"
    src="/etc/litellm.env"
    if [ -r "$src" ]; then
      mkdir -p "$(dirname "$keysFile")"
      umask 077
      grep -E '^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=' "$src" \
        | sed -e 's/^[[:space:]]*export[[:space:]]\+//' -e '/^[[:space:]]*#/d' \
        > "$keysFile"
      chmod 600 "$keysFile"
    else
      echo "opencode-keys-env: AVISO: $src ilegível — serve sem chaves cloud" >&2
    fi
  '';
}