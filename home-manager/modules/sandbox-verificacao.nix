{ config, lib, pkgs, ... }:
# sandbox-verificacao — nightly self-verification of the canary sandbox
# (12/10, dono: "depender menos de humano validando"). Mirror do padrão
# xref-watch: roda a SUÍTE (524 checks) + o validador OTBM (reader réplica
# do canary) toda madrugada; telegrama SÓ em regressão (mesmo canal team).
# A prova viva de manhã: journalctl --user -u sandbox-verificacao.
let
  # writeShellScriptBin, NÃO inline bash -c (lição do xref: systemd choca
  # em quoting aninhado — medido).
  sandbox-verifica = pkgs.writeShellScriptBin "sandbox-verifica" ''
    set -u
    FALHAS=""

    # 1. suíte Lua (524 checks — o gate de TODAS as mecânicas sandbox)
    SUITE=$(cd /home/nixos/projects/canary-official && \
      ${pkgs.lua}/bin/lua data-sandbox/tests/run_tests.lua 2>&1 | tail -1)
    echo "[sandbox-verifica] $SUITE"
    case "$SUITE" in
      *FALHA*|*lua:*)
        FALHAS="suite: $SUITE"
        ;;
    esac

    # 2. mundo: validador OTBM (estrutura + filtro-mestre + contagens)
    OTBM=$(cd /home/nixos/projects/canary-official/dataset/maps/src && \
      ${pkgs.python3}/bin/python3 validar_otbm.py \
        /home/nixos/projects/canary-official/data-sandbox/world/canary.otbm 2>&1 | tail -3)
    echo "[sandbox-verifica] $OTBM"
    case "$OTBM" in
      *VÁLIDO*) : ;;
      *)
        FALHAS="$FALHAS otbm: $(echo "$OTBM" | head -1)"
        ;;
    esac

    # 3. server de pé? (o container é o jogador real)
    if ! ${pkgs.docker}/bin/docker ps --format '{{.Names}}' 2>/dev/null | \
        grep -q '^otbr-server-1$'; then
      FALHAS="$FALHAS server: otbr-server-1 DOWN"
    fi

    if [ -n "$FALHAS" ]; then
      /home/nixos/projects/team/tg.sh post \
        "[sandbox] regressão noturna: $FALHAS" || true
      exit 1
    fi
    echo "[sandbox-verifica] TUDO VERDE"
  '';
in {
  home.packages = [ sandbox-verifica ];

  systemd.user.services.sandbox-verificacao = {
    Unit = {
      Description = "Nightly sandbox self-verification (suite + otbm + server)";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${sandbox-verifica}/bin/sandbox-verifica";
    };
  };

  systemd.user.timers.sandbox-verificacao = {
    Unit = {
      Description = "Nightly sandbox self-verification";
    };
    Timer = {
      OnCalendar = "*-*-* 03:17:00";
      Persistent = true;
    };
    Install = {
      WantedBy = [ "timers.target" ];
    };
  };
}
