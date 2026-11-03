# ═══════════════════════════════════════════════════════════════════════
# JARVIS-KEYS-ENV — espelho do /etc/litellm.env em formato systemd
# ═══════════════════════════════════════════════════════════════════════
#
# PROBLEMA (03/11): o systemd EnvironmentFile NÃO aceita `export KEY=...`.
# A linha é recusada e o systemd LOGA A LINHA INTEIRA no journal:
#
#   jarvis-telegram.service: Ignoring invalid environment assignment
#   'export NVIDIA_API_KEY=nvapi-...': /etc/litellm.env
#
# Duas consequências: (1) a variável NÃO entra no ambiente do serviço (o bot
# sobe sem chave cloud) e (2) o SEGREDO vai parar no journal, legível por
# qualquer usuário no grupo systemd-journal. Medido: 206 linhas hoje, com
# valores de sk-or-v1-*, sk-* e nvapi-*.
#
# FIX: /etc/litellm.env continua como está (o shell precisa de `export` — os
# scripts fazem `set -a; . file`), e um unit oneshot gera o espelho em
# /run/jarvis/litellm.env no formato KEY=valor (systemd-compatible), 0600
# root:root. Os units que precisam das chaves passam a ler o espelho.
#
# O systemd lê o EnvironmentFile como root antes de largar privilégio → o
# 0600 root não impede o serviço (roda como user) de receber as variáveis.
# ═══════════════════════════════════════════════════════════════════════
{ config, lib, pkgs, ... }:
let
  cfg = config.services.jarvis-keys-env;
  mirrorScript = pkgs.writeShellScript "jarvis-keys-env" ''
    set -euo pipefail
    src="${cfg.source}"
    dst="${cfg.target}"
    if [ ! -r "$src" ]; then
      echo "jarvis-keys-env: AVISO: $src ilegível — units sem chaves cloud" >&2
      exit 0
    fi
    install -d -m 0700 -o root -g root "$(dirname "$dst")"
    umask 077
    grep -E '^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=' "$src" \
      | sed -e 's/^[[:space:]]*export[[:space:]]\+//' -e '/^[[:space:]]*#/d' \
      > "$dst"
    chmod 0600 "$dst"
    # NÃO logar o conteúdo: só o número de chaves.
    echo "jarvis-keys-env: $dst escrito ($(grep -c '=' "$dst") chaves)"
  '';
in
{
  options.services.jarvis-keys-env = {
    enable = lib.mkEnableOption "espelho systemd do /etc/litellm.env (sem `export`)";
    source = lib.mkOption {
      type = lib.types.str;
      default = "/etc/litellm.env";
      description = "Arquivo-fonte com as chaves (formato shell, aceita `export`).";
    };
    target = lib.mkOption {
      type = lib.types.str;
      default = "/run/jarvis/litellm.env";
      description = "Espelho em formato systemd (KEY=valor).";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.tmpfiles.rules = [
      "d /run/jarvis 0700 root root -"
    ];

    systemd.services."jarvis-keys-env" = {
      description = "Espelha /etc/litellm.env em formato systemd (KEY=valor, sem `export`)";
      wantedBy = [ "multi-user.target" ];
      before = [ "jarvis-telegram.service" "jarvis-vault.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = mirrorScript;
      };
    };

    # Re-gera o espelho se a fonte mudar (rotação de chave sem reboot).
    systemd.paths."jarvis-keys-env-path" = {
      description = "Re-gera /run/jarvis/litellm.env quando /etc/litellm.env muda";
      wantedBy = [ "multi-user.target" ];
      pathConfig = {
        PathChanged = cfg.source;
        Unit = "jarvis-keys-env.service";
      };
    };
  };
}
