{pkgs, ...}: let
  booksDir = "$HOME/Downloads/books";

  # JARVIS — prompt rápido
  jarvisAsk = pkgs.writeScriptBin "jarvis-ask-prompt" ''
    #!/bin/sh
    PROMPT=$(wofi --dmenu --prompt "JARVIS:" --width 800 2>/dev/null || rofi -dmenu -p "JARVIS:" -theme jarvis-cyan 2>/dev/null)
    [ -z "$PROMPT" ] && exit 0
    foot --app-id floating_shell -e bash -lc "jarvis ask \"$PROMPT\""
  '';

  # NixOS-AI Launcher — GUI para todas as features
  launcherScript = pkgs.writeScriptBin "nixos-ai-launcher" ''
    #!/bin/sh
    exec ${../../../modules/ai/jarvis/src/jarvis/cli/launcher.sh} "$@"
  '';

  booksScript = pkgs.writeScriptBin "open_books" ''
    #!/bin/sh

    BOOKS_DIR="${booksDir}"

    BOOK=$(find "$BOOKS_DIR" -type f \( -iname "*.pdf" -o -iname "*.epub" -o -iname "*.djvu" \) | wofi --dmenu --prompt "Select a book" --width 1200 --height 400)

    if [ -n "$BOOK" ]; then
        zathura "$BOOK" &
    else
        echo "No book selected."
    fi
  '';
in {
  home.packages = with pkgs; [
    booksScript
    jarvisAsk
    launcherScript
    grim
    slurp
    wl-clipboard
    libnotify # Necessário para o grimblast enviar notificações do sistema
    grimblast # Garante que a ferramenta de screenshot está nos pacotes do user
  ];

  wayland.windowManager.hyprland.settings = {
    bind = [
      # Corrigido: vírgula adicionada entre $mainMod e Return
      "$mainMod,       Return, exec, $terminal"
      "$mainMod,       Q, killactive"
      "$mainMod SHIFT, Q, exit,"
      "$mainMod,       R, exec, $fileManager"
      "$mainMod,       F, fullscreen, 0"
      "$mainMod,       T, togglefloating,"
      "$mainMod,       D, exec, $menu --show drun"
      "$mainMod,       J, layoutmsg, togglesplit"
      "$mainMod,       E, exec, bemoji -cn"
      "$mainMod,       V, exec, cliphist list | $menu --dmenu | cliphist decode | wl-copy"
      "$mainMod,       B, exec, pkill -SIGUSR2 waybar"
      "$mainMod SHIFT, B, exec, pkill -SIGUSR1 waybar"
      "$mainMod,       L, exec, loginctl lock-session"
      "$mainMod,       P, exec, hyprpicker -an"
      "$mainMod,       N, exec, swaync-client -t"
      "$mainMod,       W, exec, ${booksScript}/bin/open_books"
      "$mainMod,       A, exec, ${launcherScript}/bin/nixos-ai-launcher"

      # Screenshots resilientes (copia direto para o wl-copy)
      ", Print, exec, grim - | wl-copy"
      "$mainMod, Print, exec, grim -g \"$(slurp)\" - | wl-copy"

      # Moving focus
      "$mainMod, left, movefocus, l"
      "$mainMod, right, movefocus, r"
      "$mainMod, up, movefocus, u"
      "$mainMod, down, movefocus, d"

      # Moving windows
      "$mainMod SHIFT, left,  swapwindow, l"
      "$mainMod SHIFT, right, swapwindow, r"
      "$mainMod SHIFT, up,    swapwindow, u"
      "$mainMod SHIFT, down,  swapwindow, d"

      # Resizing windows
      "$mainMod CTRL, left,  resizeactive, -60 0"
      "$mainMod CTRL, right, resizeactive,  60 0"
      "$mainMod CTRL, up,    resizeactive,  0 -60"
      "$mainMod CTRL, down,  resizeactive,  0  60"

      # Switching workspaces
      "$mainMod, 1, workspace, 1"
      "$mainMod, 2, workspace, 2"
      "$mainMod, 3, workspace, 3"
      "$mainMod, 4, workspace, 4"
      "$mainMod, 5, workspace, 5"
      "$mainMod, 6, workspace, 6"
      "$mainMod, 7, workspace, 7"
      "$mainMod, 8, workspace, 8"
      "$mainMod, 9, workspace, 9"
      "$mainMod, 0, workspace, 10"

      # Moving windows to workspaces
      "$mainMod SHIFT, 1, movetoworkspacesilent, 1"
      "$mainMod SHIFT, 2, movetoworkspacesilent, 2"
      "$mainMod SHIFT, 3, movetoworkspacesilent, 3"
      "$mainMod SHIFT, 4, movetoworkspacesilent, 4"
      "$mainMod SHIFT, 5, movetoworkspacesilent, 5"
      "$mainMod SHIFT, 6, movetoworkspacesilent, 6"
      "$mainMod SHIFT, 7, movetoworkspacesilent, 7"
      "$mainMod SHIFT, 8, movetoworkspacesilent, 8"
      "$mainMod SHIFT, 9, movetoworkspacesilent, 9"
      "$mainMod SHIFT, 0, movetoworkspacesilent, 10"

      # Scratchpad
      "$mainMod,       S, togglespecialworkspace,  magic"
      "$mainMod SHIFT, S, movetoworkspace, special:magic"

      # JARVIS — ferramentas de IA (SUPER+A → launcher, ver acima)
      "$mainMod SHIFT, A, exec, $terminal -e jarvis agent --help"
      "$mainMod,       I, exec, $terminal -e jarvis doctor"
    ];

    bindm = [
      "$mainMod, mouse:272, movewindow"
      "$mainMod, mouse:273, resizewindow"
    ];

    bindel = [
      ",XF86AudioRaiseVolume,  exec, wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"
      ",XF86AudioLowerVolume,  exec, wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"
      ",XF86AudioMute,         exec, wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"
      ",XF86AudioMicMute,      exec, wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"
      "$mainMod, bracketright, exec, brightnessctl s 10%+"
      "$mainMod, bracketleft,  exec, brightnessctl s 10%-"
    ];

    bindl = [
      ", XF86AudioNext,  exec, playerctl next"
      ", XF86AudioPause, exec, playerctl play-pause"
      ", XF86AudioPlay,  exec, playerctl play-pause"
      ", XF86AudioPrev,  exec, playerctl previous"
    ];
  };
}
