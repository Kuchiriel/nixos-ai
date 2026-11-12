# xref-watch — weekly docs<->code cross-reference regression watch (12/10).
#
# (12/11) PROPRIEDADE: o alvo do check (xref_audit.py do baseline
# docs<->code) vive no repo canary-official, nao no nixos-ai. Mesma
# correção do sandbox-verificacao: o COMANDO fica instalado
# (`xref-check`), mas o timer semanal fica DESLIGADO por padrão. Para
# agendar aqui (temporário) ou no harness do repo dono:
#   services.jarvis.xrefWatch.enable = true;
{ config, lib, pkgs, ... }:
let
  watch = config.services.jarvis.xrefWatch;
  home = config.home.homeDirectory;
  # (12/10) writeShellScriptBin, NOT inline bash -c: systemd chokes on
  # nested quoting ("Unbalanced quoting", unit refused to load — measured).
  xref-check = pkgs.writeShellScriptBin "xref-check" ''
    set -u
    OUT=$(${pkgs.python3}/bin/python3 \
      "${watch.repoPath}/dataset/tools/xref_audit.py" \
      --check 2>&1 | tail -1)
    echo "$OUT"
    case "$OUT" in
      *CHECK\ FAIL*)
        ${home}/projects/team/tg.sh post \
          "[xref] cross-ref regression: $OUT" || true
        ;;
    esac
  '';
in
{
  options.services.jarvis.xrefWatch = {
    enable = lib.mkEnableOption
      "check semanal de cross-references do canary (dono: repo canary-official)";
    repoPath = lib.mkOption {
      type = lib.types.str;
      default = "${home}/projects/canary-official";
      description = "Raiz do repo que contém dataset/tools/xref_audit.py.";
    };
  };

  config = lib.mkMerge [
    { home.packages = [ xref-check ]; }

    (lib.mkIf watch.enable {
      systemd.user.services.xref-watch = {
        Unit = {
          Description = "Weekly xref regression check (docs<->code)";
        };
        Service = {
          Type = "oneshot";
          ExecStart = "${xref-check}/bin/xref-check";
        };
      };

      systemd.user.timers.xref-watch = {
        Unit = {
          Description = "Weekly xref regression check";
        };
        Timer = {
          OnCalendar = "Sun *-*-* 04:00:00";
          Persistent = true;
        };
        Install = {
          WantedBy = [ "timers.target" ];
        };
      };
    })
  ];
}
