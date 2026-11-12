# sandbox-verificacao — nightly self-verification of the canary sandbox
#
# (12/11) PROPRIEDADE: este check vive no repo canary-official, nao no
# nixos-ai. Ele foi escrito aqui (12/10) e por isso aparecia como unit
# failed do nixos-ai quando o jogo estava parado — o dono apontou a
# mistura de escopos ("meu projeto de jogo nao tem a ver com o nixos-ai").
#
# O que muda: o COMANDO continua instalado (`sandbox-verifica`, util para
# rodar a mao), mas o TIMER noturno e o SERVICE ficam DESLIGADOS por
# padrao. Quem quiser o agendamento liga a opcao no home.nix:
#   services.jarvis.sandboxVerificacao.enable = true;
# A casa definitiva do agendamento e o repo canary-official (harness de la).
{ config, lib, pkgs, ... }:
let
  cfg = config.services.jarvis.sandboxVerificacao;
  home = config.home.homeDirectory;

  # writeShellScriptBin, NÃO inline bash -c (lição do xref: systemd choca
  # em quoting aninhado — medido).
  sandbox-verifica = pkgs.writeShellScriptBin "sandbox-verifica" ''
    set -u
    FALHAS=""
    REPO="${cfg.repoPath}"

    # 1. suíte Lua (524 checks) — RESUMO é a linha do veredito (grep,
    #    não tail: o output tem linhas depois do resumo)
    SUITE=$(cd "$REPO" && \
      ${pkgs.lua}/bin/lua data-sandbox/tests/run_tests.lua 2>&1 \
      | grep "RESUMO" | tail -1)
    echo "[sandbox-verifica] $SUITE"
    case "$SUITE" in
      *"0 FALHA"*) : ;;           # sucesso: "N OK, 0 FALHA"
      *) FALHAS="suite: $SUITE" ;;
    esac

    # 2. mundo: validador OTBM — VÁLIDO está no MEIO do output (grep)
    OTBM=$(cd "$REPO/dataset/maps/src" && \
      ${pkgs.python3}/bin/python3 validar_otbm.py \
        "$REPO/data-sandbox/world/canary.otbm" 2>&1 \
      | grep -c "VALIDO" || true)
    echo "[sandbox-verifica] otbm VALIDO x$OTBM (sem acento: output real)"
    if [ "$OTBM" -lt 1 ]; then
      FALHAS="$FALHAS otbm: sem VALIDO no output"
    fi

    # 3. server de pé? (o container é o jogador real)
    # (08/11) Marcador de pausa INTENCIONAL: o dono marca o sandbox como
    # pausado com o arquivo `canary-official/.sandbox-paused` — o check do
    # server é pulado com log explícito (não é regressão). A suíte e o
    # validador OTBM continuam valendo. Sem o marcador: comportamento igual
    # ao anterior (otbr-server-1 DOWN = falha + ntfy).
    if [ -f "$REPO/.sandbox-paused" ]; then
      echo "[sandbox-verifica] sandbox PAUSADO (marker .sandbox-paused) — pulando check do otbr-server-1"
    else
      DOCKER_PS=$(${pkgs.docker}/bin/docker ps --format '{{.Names}}' 2>&1 || true)
      echo "[sandbox-verifica] containers: $(echo "$DOCKER_PS" | tr '\n' ' ')"
      if ! echo "$DOCKER_PS" | grep -q '^otbr-server-1$'; then
        FALHAS="$FALHAS server: otbr-server-1 DOWN (docker ps: $DOCKER_PS)"
      fi
    fi

    if [ -n "$FALHAS" ]; then
      ${home}/projects/team/tg.sh post \
        "[sandbox] regressão noturna: $FALHAS" || true
      exit 1
    fi
    echo "[sandbox-verifica] TUDO VERDE"
  '';
in
{
  options.services.jarvis.sandboxVerificacao = {
    enable = lib.mkEnableOption
      "verificação noturna do sandbox canary (dono do agendamento: repo canary-official)";
    repoPath = lib.mkOption {
      type = lib.types.str;
      default = "${home}/projects/canary-official";
      description = "Raiz do repo canary-official verificado pelo comando sandbox-verifica.";
    };
  };

  config = lib.mkMerge [
    # Comando sempre disponível (rodar a mao continua valendo).
    { home.packages = [ sandbox-verifica ]; }

    (lib.mkIf cfg.enable {
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
    })
  ];
}
