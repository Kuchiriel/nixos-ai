{pkgs, lib, ...}: let
  wine10 = pkgs.wineWow64Packages.stable;

  mt5 = pkgs.writeShellApplication {
    name = "mt5";
    runtimeInputs = [wine10];
    text = ''
      # mt5 — abre o terminal MT5 no prefix dedicado (~/.mt5)
      # uso: mt5 [argumentos do terminal64.exe]
      export WINEARCH=win64
      export WINEPREFIX="''${MT5_PREFIX:-$HOME/.mt5}"
      TERM64="''${MT5_TERM64:-$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe}"
      if [ ! -f "$TERM64" ]; then
        echo "mt5: terminal64.exe nao encontrado em $WINEPREFIX" >&2
        echo "     rode: mt5-setup /caminho/para/mt5setup.exe" >&2
        exit 1
      fi
      exec wine "$TERM64" "$@"
    '';
  };

  mt5-setup = pkgs.writeShellApplication {
    name = "mt5-setup";
    runtimeInputs = [wine10];
    text = ''
      # mt5-setup — instala o MT5 no prefix dedicado
      # uso: mt5-setup <caminho do mt5setup.exe> [--auto]
      #   --auto = instalacao silenciosa (sem wizard)
      # Aceite os prompts de Mono/Gecko do wine (necessarios p/ o MT5).
      if [ $# -lt 1 ]; then echo "uso: mt5-setup <mt5setup.exe> [--auto]" >&2; exit 1; fi
      export WINEARCH=win64
      export WINEPREFIX="''${MT5_PREFIX:-$HOME/.mt5}"
      mkdir -p "$WINEPREFIX"
      SETUP="$1"
      AUTO=""
      if [ "$2" = "--auto" ] || [ "$1" = "--auto" ]; then AUTO="/auto"; fi
      wine "$SETUP" $AUTO
    '';
  };

  mt5-backtest = pkgs.writeShellApplication {
    name = "mt5-backtest";
    runtimeInputs = [wine10];
    text = ''
      # mt5-backtest — roda o Strategy Tester headless via /config (arquivo .ini)
      # uso: mt5-backtest <tester.ini>
      # o ini segue o formato [Tester] do MT5: Expert, Symbol, Period, FromDate,
      # ToDate, Deposit, Model, OptimizationMode, Report, ShutdownTerminal...
      # ref: metatrader5.com help /tester_ini + stackoverflow 73766843
      INI="''${1:-}"
      [ -n "$INI" ] || { echo "uso: mt5-backtest <tester.ini>"; exit 1; }
      export WINEARCH=win64
      export WINEPREFIX="''${MT5_PREFIX:-$HOME/.mt5}"
      TERM64="''${MT5_TERM64:-$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe}"
      [ -f "$TERM64" ] || { echo "mt5: terminal64.exe nao encontrado"; exit 1; }
      WIN_INI=$(winepath -w "$INI")
      exec wine "$TERM64" "/portable" "/config:$WIN_INI"
    '';
  };

  mt5-desktop-pkg = pkgs.runCommandLocal "mt5-desktop-files" {
    buildInputs = [ ];
  } ''
    mkdir -p $out/share/applications
    cat > $out/share/applications/mt5.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=MetaTrader 5
Comment=MetaTrader 5 Trading Platform (via Wine)
Exec=mt5 %F
Icon=wine
Terminal=false
Type=Application
Categories=Office;Finance;
EOF
  '';
in {
  environment.systemPackages = with pkgs; [
    pciutils
    clinfo
    nvtopPackages.nvidia # Monitoramento em tempo real da RTX 4050 e Intel UHD
    uwsm
    git
    curl
    jq
    htop
    unar # Descompactar .rar/.rar5 (livre; unrar original precisaria allowUnfree)
    wineWow64Packages.stable
    winetricks
    mt5
    mt5-setup
    mt5-backtest
    mt5-desktop-pkg
  ];

  # Regras de udev para otimizar o scheduler de I/O nos NVMes de alta performance
  services.udev.extraRules = ''
    ACTION=="add|change", KERNEL=="sd[a-z]|mmcblk[0-9]*|nvme[0-9]*", ATTR{queue/scheduler}="kyber"
  '';
}
