# ydotoold para o jarvis/nixos-ai (2026-10-02).
#
# POR QUE ESTE SERVIÇO EXISTE (bug real, medido hoje):
#   `ydotool` procurava o socket em `/run/user/1000/.ydotool_socket` e o
#   `ydotoold` (iniciado via sudo, sem XDG_RUNTIME_DIR) criava em
#   `/tmp/.ydotool_socket`. Resultado: TODO comando ydotool falhava em
#   silêncio — `ydotool click` devolvia rc=0 e não clicava, `mousemove` não
#   movia. Por isso o clique no jogo "ia pro botao mas nao clicava" e o
#   teclado sintético não funcionava. Com o socket no lugar certo, os dois
#   passaram a funcionar na hora (click no botao do chat = CHAT ON).
#
# Roda como serviço do USUÁRIO (sem sudo): o grupo `uinput` já dá acesso a
# /dev/uinput, e o XDG_RUNTIME_DIR do systemd --user é o /run/user/1000, que é
# exatamente onde o `ydotool` procura.
{ config, lib, pkgs, ... }:
{
  systemd.user.services.ydotoold = {
    Unit = {
      Description = "ydotoold — mouse/teclado virtual (uinput) para o JARVIS";
      After = ["graphical-session.target"];
    };
    Service = {
      Type = "simple";
      ExecStart = "${pkgs.ydotool}/bin/ydotoold";
      Restart = "always";
      RestartSec = 2;
    };
    Install.WantedBy = ["default.target"];
  };
}