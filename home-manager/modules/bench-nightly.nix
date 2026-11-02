{ config, lib, pkgs, ... }:
# bench-nightly — os 2 jobs noturnos do JARVIS, DECLARATIVOS (02/11).
#
# Antes: arquivos soltos em ~/.config/systemd/user/ (fora do Nix) — o
# rebuild não os tocava e nada no repo os descrevia (entropia). Agora são
# gerados pelo home-manager: o agendamento vive junto do resto.
#
# bench-qwen (04:00): mede o DEFAULT (4B-MTP+LoRA, :8092). O script nunca
# mais para o default — para o router :8080 (medida limpa) e o religa.
# swap-probe (05:00): virou probe do DEFAULT (o hot-swap que ele media não
# existe mais na topologia nova) com fail-safe: se o default não
# responde, reinicia o service em vez de deixar a máquina sem LLM.
#
# Os scripts usam `sudo -n systemctl` (stop/start do router) — o usuário
# tem NOPASSWD pra systemctl; o timer roda como user service.
{
  systemd.user.services = {
    bench-qwen = {
      Unit = {
        Description = "Bench noturno do default (4B-MTP+LoRA, :8092)";
      };
      Service = {
        Type = "oneshot";
        WorkingDirectory = "/home/nixos/projects";
        ExecStart = "/home/nixos/projects/nixos-ai/benchmarks/model-tiers/night-qwen.sh";
        Nice = 10;
      };
    };
    swap-probe = {
      Unit = {
        Description = "Probe do default (05:00) — reinicia o service se o default não responder";
      };
      Service = {
        Type = "oneshot";
        WorkingDirectory = "/home/nixos/projects";
        ExecStart = "/home/nixos/projects/nixos-ai/benchmarks/model-tiers/swap-probe.sh";
        Nice = 10;
      };
    };
  };

  systemd.user.timers = {
    bench-qwen = {
      Unit = {
        Description = "Bench noturno do default (04:00, com religamento verificado)";
      };
      Timer = {
        OnCalendar = "04:00";
        Persistent = true;
        RandomizedDelaySec = 300;
      };
      Install = {
        WantedBy = [ "timers.target" ];
      };
    };
    swap-probe = {
      Unit = {
        Description = "Probe do default (05:00)";
      };
      Timer = {
        OnCalendar = "05:00";
        Persistent = true;
        RandomizedDelaySec = 300;
      };
      Install = {
        WantedBy = [ "timers.target" ];
      };
    };
  };
}
