# ═══ Nightwatch Timer — overnight autonomous execution ═══
#
# Runs jarvis nightwatch every day at 03:00.
# Independent of session — systemd handles scheduling.
#
# Usage:
#   sudo systemctl start nightwatch    # run now
#   sudo systemctl status nightwatch   # check status
#   sudo journalctl -u nightwatch -f   # follow logs
#   sudo systemctl start jarvis.target # start all jarvis services
#   sudo systemctl stop jarvis.target  # stop all jarvis services

{ config, lib, pkgs, ... }:

let
  jarvisPackage = pkgs.jarvis;
  # Hardcoded: nightwatch timer is specific to the nixos-ai project.
  # Other projects should use their own timer or the jarvis CLI.
  projectRoot = "/home/nixos/projects/nixos-ai";

  # (30/09) O validador do nightwatch EXECUTA os testes do projeto que ele
  # patcheou — logo precisa de um python COM pytest. Medido no unit real:
  #   - /run/current-system/sw/bin/python3 NÃO EXISTE (o PATH do unit não tem
  #     python3; o processo roda com o python do próprio closure);
  #   - o site-packages do jarvis tem só `jarvis` e `nightwatch`.
  # Resultado: `import pytest` falhava → "No module named pytest" contava
  # como FALHA DA TASK, e a convergência media 0/23 — não era o modelo.
  #
  # Tentativas REJEITADAS por medição (não repetir):
  #   a) achar um python com pytest no PATH → não existe nenhum no serviço;
  #   b) `nix develop --command python -m pytest` por validação → no unit
  #      quebra (ProtectSystem=strict não deixa o nix escrever cache,
  #      MemoryMax=2G estoura no nix-eval) e o serviço saía com código 0 no
  #      meio da task (Result=success, ExecMainStatus=0, journal vazio);
  #   c) makeSearchPathOutput sobre propagatedBuildInputs → o atributo Nix
  #      não bate com o nix-support real; pytest não entrava no path.
  #
  # A via canônica: python3.withPackages monta um ambiente com pytest de
  # verdade. O Nix ESCOLHE o interpretador e o passa em JARVIS_TEST_PYTHON;
  # o Python apenas obedece e se certifica (`import pytest`) antes de usar.
  testPythonEnv = pkgs.python3.withPackages (ps: [
    ps.pytest
    ps.pytest-timeout
    ps.hypothesis
  ]);
in {
  systemd.services.nightwatch = {
    description = "JARVIS nightwatch — autonomous overnight maintenance";
    # 30/09: llama-cpp-ik (MoE :8084) como dependência systemd. O harness
    # tentava subir o MoE via `sudo systemctl start` num subprocess — o
    # sudo do PATH do serviço (/run/current-system/sw/bin) é o binário do
    # store SEM setuid, morria com "deve ter bit setuid", e o nightwatch
    # dormia 30min achando que o MoE subia. Declarar Wants+After deixa o
    # systemd subir o MoE como dependência real (robust, sem sudo), e o
    # harness só espera o :8084 ficar healthy. ensure_strong_llm() ainda
    # funciona como fallback (inicia o MoE sob demanda).
    after = [ "llama-cpp-server.service" "jarvis.target" "llama-cpp-ik.service" ];
    wants = [ "llama-cpp-server.service" "llama-cpp-ik.service" ];
    partOf = [ "jarvis.target" ];
    # 30/09: o restore pós-run (parar o MoE que o nightwatch subiu + voltar
    # o router) NÃO pode ser `sudo systemctl` — o unit tem
    # NoNewPrivileges + RestrictSUIDSGID, então o kernel bloqueia setuid e o
    # sudo morre com rc=1 ("sinalizador sem novos privilégios"). Em vez de
    # foughtar o sandbox, o systemd cuida: Wants= sobe o MoE junto, e
    # ExecStopPost abaixo devolve a máquina (para o MoE, restaura o router)
    # com os próprios privilégios do systemd (sem sudo, sem escalada).
    # SEM wantedBy: o timer é o único gatilho. Com wantedBy o service subia a
    # cada `nixos-rebuild switch` (restart do jarvis.target) e queimava a GPU
    # em horário de uso — forense 2026-09-07.

    serviceConfig = {
      Type = "oneshot";
      Environment = [
        "PYTHONPATH=${jarvisPackage}/lib/python3.13/site-packages"
        # O interpretador COM pytest, escolhido pelo Nix (ver testPythonEnv).
        # O validador lê isto e se certifica (`import pytest`) antes de usar.
        "JARVIS_TEST_PYTHON=${testPythonEnv}/bin/python3"
        "JARVIS_PROJECT_ROOT=${projectRoot}"
        # 30/09: /run/wrappers/bin PRIMEIRO — é onde vive o sudo setuid
        # (o de sw/bin é symlink pro store, sem setuid, morre no serviço).
        "PATH=${testPythonEnv}/bin:/run/wrappers/bin:/run/current-system/sw/bin:${pkgs.git}/bin:${pkgs.coreutils}/bin:${pkgs.gnugrep}/bin:${pkgs.findutils}/bin:${pkgs.gnused}/bin"
      ];
      # (30/09) --tasks 4, DE VOLTA ao normal. O experimento --tasks 1 (para
      # isolar drift de branch) provou que drift NÃO era a causa: a causa era
      # o validador sem pytest (ver _python_with_pytest). E --tasks 1 é
      # FRÁGIL: uma task lixo na fila (encontrada: id='stuck', desc='test',
      # target vazio) come o ciclo inteiro e o run fecha 0/0 sem trabalhar.
      # 4 tasks dão 4 chances por ciclo e cabem no teto de 1h.
      ExecStart = "${jarvisPackage}/bin/jarvis nightwatch --tasks 4 --report-telegram --projects nixos-ai";
      # ^ escopo explícito: auto-discover varria TUDO (incl. repos de
      # produção como guia-renamer-pro). Timer só toca nixos-ai.
      WorkingDirectory = projectRoot;
      User = "nixos";

      # Capture all output to journal for audit trail
      StandardOutput = "journal";
      StandardError = "journal";

      # Safety: do NOT restart on failure (prevents crash loops)
      Restart = "no";

      # 30/09: devolve a máquina depois do run, com os privilégios do
      # systemd (o harness não tem — NoNewPrivileges bloqueia sudo).
      # - stop MoE: ele só subiu por causa do Wants= deste unit.
      # - start router: devolve o bonsai pro dono (usa REPL de manhã).
      ExecStopPost = "+/bin/sh -c '/run/current-system/sw/bin/systemctl stop llama-cpp-ik.service || true; /run/current-system/sw/bin/systemctl start llama-cpp-server.service || true'";
      # ^ prefixo '+': roda o ExecStopPost com privilégio de root (senão
      # herda User=nixos e o 'systemctl stop' dá Access denied). O
      # ExecStart principal continua User=nixos, sem escalated.

      # ── Sandboxing ──
      ProtectSystem = "strict";       # /usr e /boot read-only
      PrivateTmp = true;                # /tmp privado
      NoNewPrivileges = true;           # Sem escalada de privilégio
      RestrictSUIDSGID = true;          # Sem arquivos SUID/SGID
      # ── Resource limits ──
      MemoryMax = "2G";                 # Max 2GB RAM (nightwatch needs more)
      TasksMax = 128;                   # Max 128 tasks
      TimeoutStartSec = "3600";         # 1 hour max runtime
    };
  };

  systemd.timers.nightwatch = {
    description = "Run JARVIS nightwatch daily at 03:00";
    # DESABILITADO 2026-09-16 (dono): briga por GPU com audiobook; nunca
    # entregou nada útil. Arquivo preservado p/ reavaliação futura.
    wantedBy = lib.mkForce [];

    timerConfig = {
      OnCalendar = "*-*-* 03:00:00";
      # SEM Persistent: cada reload do systemd (rebuild) disparava o elapse
      # "perdido" imediatamente e queimava a GPU em horário de uso — 2026-09-07.
      RandomizedDelaySec = 1200;
      AccuracySec = 300;
    };
  };
}
