# Audiobook Reader — keybindings and packages.
# Scripts (menu + waybar) are defined in waybar.nix to share scope.
# This module adds keybindings and mpv.
{
  pkgs,
  lib,
  ...
}: {
  # ── Packages ────────────────────────────────────────────────────────────────
  home.packages = with pkgs; [
    mpv # Audio player for TTS and audiobook playback
  ];

  # ── Hyprland keybindings ────────────────────────────────────────────────────
  wayland.windowManager.hyprland.settings = {
    bind = [
      # SUPER+O = Audiobook menu (O for "out loud")
      "$mainMod, O, exec, jarvis-audiobook-menu"
      # SUPER+SHIFT+O = Quick TTS test
      "$mainMod SHIFT, O, exec, jarvis speak 'Olá! Teste de TTS.' 2>/dev/null | tail -1 | xargs -I{} mpv --no-video --really-quiet {}"
    ];
  };
}
