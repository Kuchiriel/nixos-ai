{
  pkgs,
  ...
}: {
  fonts.fontconfig.enable = true;
  home.packages = with pkgs; [
    # (21/10) PYTHON3 EXPLÍCITO: o venv karaok (duplex-voice, asrd,
    # whisper, TTS) symlinka pro python3 do profile — era dependência
    # TRANSITIVA (foi embora com o antigravity no GC de 12:00 e a
    # interface de voz MORREU). Explícito = nunca mais GC'd.
    python3

    # AI CLIs
    kilo

    # Desktop essential apps
    foot
    yazi
    imv
    mpv
    vlc # player p/ revisar áudio/vídeo (LOTM)
    audacity # editor de áudio leve (datasets voz)
    mousepad # notepad gráfico simples (legendas/checks)
    pavucontrol

    # TUI tools (porta do legado Manjaro — abre via on-click no Waybar)
    bluetui # Bluetooth TUI (on-click no módulo bluetooth; melhor que bluetuith)
    hyprsunset # modo noturno quente/frio (toggle no módulo brilho)
    ncpamixer # Audio mixer TUI (on-click no módulo pulseaudio)
    networkmanagerapplet # nmtui-connect (on-click no módulo network)
    calcurse # Calendar TUI (on-click no clock)
    htop # Process viewer alternativo ao btm
    intel-gpu-tools

    # Fonts / Icons (Adaptado para compatibilidade estável do Nixpkgs 26.05)
    font-awesome
    nerd-fonts.jetbrains-mono
    nerd-fonts.symbols-only

    # Core CLI utils
    nodejs # npx para MCP servers (Roo Dev, etc.)
    gitleaks # secret scanning git (IMP-001; docs/audits/SECURITY.md)
    bc
    bottom
    brightnessctl
    cliphist
    ffmpeg
    fzf
    grimblast
    hyprpicker
    xxd # hex dump (análise de formatos binários de clients de jogo)
    # Input sintetico (uinput) para o agente operar o desktop sem mouse fisico:
    # ydotool faz TECLADO e MOUSE (clique com botao, mover cursor). O Hyprland
    # so tem `dispatch movecursor` e nao tem dispatch de clique, entao sem o
    # ydotool nao da para clicar no chat do jogo — que e como a automacao de
    # UI do sandbox (canary-official/data-sandbox/tools/loop.sh) fala com o
    # client. wtype faz so teclado e ja era usado.
    ydotool
    xdotool # alternativa X11 (XWayland) ao ydotool — ydotoold (daemon/uinput)
            # estava dando problema; xdotool nao precisa de daemon nem uinput
    wtype
    ntfs3g
    playerctl
    ripgrep
    unzip
    wget
    wl-clipboard
    yt-dlp
    zip

    # WM Utilities
    libnotify
    # (03/11) xdg-desktop-portal-gtk/hyprland NÃO entram aqui: o sistema já
    # os instala via xdg.portal.extraPortals (programs.hyprland). Duas cópias
    # do mesmo .service faziam o dbus-broker logar "Ignoring duplicate name
    # 'org.freedesktop.impl.portal...'" em todo boot.
    yad # GUI dialogs para NixOS-AI Launcher

    # ── packages ──────────────────────────────────────
    # sidecar: terminal multiplexer/UX para CLI agents
    # sidecar
    # stt-ptt: Push-to-Talk Speech-to-Text com Whisper
    # stt-ptt
    # talk: Text-to-Speech com ElevenLabs para notificações
    # talk  # REMOVIDO: redundante com Kokoro TTS do jarvis voice
  ];
}

