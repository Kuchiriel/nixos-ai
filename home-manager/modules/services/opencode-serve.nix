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
      After = ["network-online.target" "nv-gate.service"];
      # (03/11) nv-gate é o proxy de taxa do free tier NVIDIA: sem ele o
      # serve sobe e cada rajada de agentes toma 429 (40 RPM por chave).
      # Wants = falha do gate NÃO derruba o serve (o provider fica direto).
      Wants = [ "network-online.target" "nv-gate.service" ];
      # (11/10) StartLimitIntervalSec=0 = retry PARA SEMPRE. O default
      # (5 restarts/10s) matou o serviço parado às 19:09 (bind no IP do
      # tailscale durante restart do tailscaled pelo switch) e ele só
      # voltou com restart manual. Crash-loop aqui = tailscale ainda
      # subindo; desistir nunca é a resposta certa.
      StartLimitIntervalSec = 0;
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
      # (03/11) Segura o start ATÉ o IP do tailnet existir. Sem isso o bind
      # em 100.121.100.103 falhava no boot com EADDRNOTAVAIL (o tailscaled
      # ainda não tinha subido) e deixava um ciclo de erro no journal a cada
      # boot. TimeoutStartSec=0 = espera sem limite (sem erro, sem desistir);
      # o Restart=always continua como rede de segurança.
      TimeoutStartSec = 0;
      ExecStartPre = "${pkgs.bash}/bin/bash -c 'until ${pkgs.iproute2}/bin/ip -4 addr show dev tailscale0 2>/dev/null | ${pkgs.gnugrep}/bin/grep -q \"inet 100.121.100.103\"; do sleep 2; done'";
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

  # RELOAD NO SWITCH (29/10 — incidente real): o serve carrega a config do
  # opencode UMA vez no boot. Ficou rodando desde 15/10 com a config daquela
  # época (só `freellmapi`, provider morto) e a TUI/celular passaram a ver
  # "modelos sumiram" (nvidia A55B, nomes/contexto ausentes) mesmo com a
  # config atual correta no disco — o restart manual resolvia. Aqui o serviço
  # é reiniciado a cada activation (config é regerada antes do writeBoundary),
  # então rebuild/switch nunca mais deixa o serve com config velha.
  # `|| true`: activation pode rodar sem DBUS em contexto de boot.
  home.activation."opencode-serve-reload" = lib.hm.dag.entryAfter ["writeBoundary"] ''
    if ${pkgs.systemd}/bin/systemctl --user is-active --quiet opencode-serve.service 2>/dev/null; then
      ${pkgs.systemd}/bin/systemctl --user restart opencode-serve.service 2>/dev/null || true
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