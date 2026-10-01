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
        "JARVIS_PROJECT_ROOT=${projectRoot}"
        # 30/09: /run/wrappers/bin PRIMEIRO — é onde vive o sudo setuid
        # (o de sw/bin é symlink pro store, sem setuid, morre no serviço).
        "PATH=/run/wrappers/bin:/run/current-system/sw/bin:${pkgs.git}/bin:${pkgs.coreutils}/bin:${pkgs.gnugrep}/bin:${pkgs.findutils}/bin:${pkgs.gnused}/bin"
      ];
      ExecStart = "${jarvisPackage}/bin/jarvis nightwatch --tasks 1 --report-telegram --projects nixos-ai";
      # (30/09, EXPERIMENTO) --tasks 1 (era 4): isola DRIFT de branch. Com
      # 4 tasks numa branch, a 2ª vê o arquivo já modificado pela 1ª, e o
      # old_text do modelo pode não casar com o arquivo ATUAL. Com 1 task
      # por run, cada tentativa é um arquivo limpo — se ainda assim não
      # converge, a hipótese de drift cai e o gap é a VALIDAÇÃO ser mais
      # ampla que o bug.
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
