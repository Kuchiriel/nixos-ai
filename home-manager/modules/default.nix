{
  imports = [
    ./agents-md.nix
    ./jarvismodes.nix
    # Modelos de voz (kokoro/whisper/openwakeword) — links em ~/.local/share.
    # Antes só o wakeword (desabilitado) os referenciava -> GC levou os
    # store paths e o TTS Kokoro morreu (fallback espeak = voz horrível).
    ./jarvis-models.nix
    ./alacritty.nix
    ./bat.nix
    ./chromium.nix
    ./eza.nix
    ./foot.nix
    ./git.nix
    ./hyprland
    ./lazygit.nix
    ./mpvpaper.nix
    ./neovim.nix
    ./obsidian.nix
    ./ranger.nix
    ./rofi.nix
    ./audiobook.nix
    ./starship.nix
    ./stylix.nix
    # (07/11) Madrugada da comunicacao entre os agentes (slot 03:30, antes
    # era o team-suite rodando o JOGO DE TESTE — arquivo solto, fora do Nix).
    ./night-comms.nix
    ./services/jarvis-sessions-index.nix
    ./swaync
    ./tmux.nix
    ./waybar.nix
    # Default source do pipewire = mic DIGITAL (o Stereo está morto e o
    # AEC3 captura do default ⇒ duplex surdo). Ver o módulo p/ o porque.
    ./services/wireplumber-default-source.nix
    # (05/11) MCP de coordenação entre IAs por HTTP na tailnet.
    ./services/coord-mcp.nix
    ./services/jarvis-knowledge-mcp.nix
    # (19/11, auditoria-runtime) O cliente de voz duplex era uma unit SOLTA
    # em ~/.config/systemd/user (fora do Nix): nenhum rebuild a recriava e
    # nenhuma maquina montada do zero teria voz. Ver o modulo.
    ./services/duplex-voice.nix
    ./wofi
    ./zathura.nix
    ./zsh.nix
  ];
}
