# Audiobook Reader — wofi menu, waybar status, keybindings.
# Declarative: all scripts created via home.file, no manual setup needed.
{
  pkgs,
  lib,
  ...
}: let
  # ── Wofi menu script ──────────────────────────────────────────────────────
  audiobookMenu = pkgs.writeShellScriptBin "jarvis-audiobook-menu" ''
    # Audiobook Reader — wofi menu
    # Requires: jarvis python package, wofi, mpv

    choice=$(echo -e "📚 Scan livros\\n📖 Listar livros\\n▶️  Tocar livro\\n⏸  Pausar\\n▶️  Continuar\\n⏹  Parar\\n📊 Status" | \
      wofi --dmenu --prompt "Audiobook:" --width 400 --height 350)

    case "$choice" in
      *"Scan"*)
        jarvis audiobook scan 2>&1 | wofi --dmenu --prompt "Resultado:" --width 600 || true
        ;;
      *"Listar"*)
        jarvis audiobook list 2>&1 | wofi --dmenu --prompt "Livros:" --width 600 || true
        ;;
      *"Tocar"*)
        # Get book list for selection
        books=$(jarvis audiobook list 2>/dev/null | grep -oP '^\d+\.\s+\K.*' || true)
        if [ -z "$books" ]; then
          notify-send "📚 Audiobook" "Nenhum livro encontrado. Execute Scan primeiro."
          exit 0
        fi
        book=$(echo "$books" | wofi --dmenu --prompt "Livro:" --width 600 --height 400)
        if [ -n "$book" ]; then
          notify-send "▶️ Audiobook" "Reproduzindo: $book"
          jarvis audiobook play "$book" 2>&1 | head -5 &
        fi
        ;;
      *"Pausar"*)
        jarvis audiobook pause 2>/dev/null
        notify-send "⏸ Audiobook" "Pausado"
        ;;
      *"Continuar"*)
        jarvis audiobook resume 2>/dev/null
        notify-send "▶️ Audiobook" "Continuando..."
        ;;
      *"Parar"*)
        jarvis audiobook stop 2>/dev/null
        notify-send "⏹ Audiobook" "Reprodução parada"
        ;;
      *"Status"*)
        jarvis audiobook status 2>&1 | wofi --dmenu --prompt "Status:" --width 500 || true
        ;;
    esac
  '';

  # ── Waybar status script ──────────────────────────────────────────────────
  audiobookWaybar = pkgs.writeShellScriptBin "jarvis-audiobook-waybar" ''
    # Output JSON for waybar custom module
    status=$(jarvis audiobook status 2>/dev/null)
    if echo "$status" | grep -q "Tocando\|playing"; then
      book=$(echo "$status" | grep -oP 'Livro: \K.*' | head -1)
      chunk=$(echo "$status" | grep -oP 'Chunk: \K\d+' | head -1)
      total=$(echo "$status" | grep -oP '/ \K\d+' | head -1)
      printf '{"text":"󰏤","tooltip":"▶ %s — chunk %s/%s","class":"audiobook-playing"}' "$book" "$chunk" "$total"
    elif echo "$status" | grep -q "Pausado\|paused"; then
      book=$(echo "$status" | grep -oP 'Livro: \K.*' | head -1)
      printf '{"text":"󰏤","tooltip":"⏸ %s — pausado","class":"audiobook-paused"}' "$book"
    else
      printf '{"text":"","tooltip":"Audiobook: idle","class":"audiobook-idle"}'
    fi
  '';

  # ── Quick TTS test script ──────────────────────────────────────────────────
  ttsTest = pkgs.writeShellScriptBin "jarvis-tts-test" ''
    # Quick TTS test — generates and plays a sample
    echo "Testando TTS..."
    wav=$(jarvis speak "Olá! Eu sou a Dora, sua assistente de áudio." 2>/dev/null | tail -1)
    if [ -n "$wav" ] && [ -f "$wav" ]; then
      mpv --no-video --really-quiet "$wav"
      echo "TTS OK: $wav"
    else
      echo "TTS falhou"
    fi
  '';
in {
  # ── Packages ────────────────────────────────────────────────────────────────
  home.packages = with pkgs; [
    audiobookMenu
    audiobookWaybar
    ttsTest
    mpv # Audio player for TTS and audiobook playback
  ];

  # ── Wofi config for audiobook ───────────────────────────────────────────────
  home.file.".config/wofi/style.css".text = lib.mkAfter ''
    /* Audiobook menu styling */
    window {
      background-color: rgba(15, 15, 25, 0.95);
      border: 1px solid #00ffff;
      border-radius: 8px;
    }
  '';

  # ── Hyprland keybindings ────────────────────────────────────────────────────
  wayland.windowManager.hyprland.settings = {
    bind = [
      # SUPER+O = Audiobook menu (O for "out loud")
      "$mainMod, O, exec, ${audiobookMenu}/bin/jarvis-audiobook-menu"
      # SUPER+SHIFT+O = Quick TTS test
      "$mainMod SHIFT, O, exec, ${ttsTest}/bin/jarvis-tts-test"
    ];
  };

  # ── Waybar custom module (appended to existing config) ──────────────────────
  # NOTE: This is merged into the existing waybar config via mkMerge in waybar.nix
  # The actual module definition is added there.
}
