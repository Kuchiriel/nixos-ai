{
  config,
  lib,
  pkgs,
  ...
}:
# Scripts de manutenção empacotados DECLARATIVAMENTE (writeShellApplication).
#
# Por que: depender de scripts soltos na raiz do repo (./rebuild.sh,
# ./clean.sh, ./fix-qdrant.sh) funciona no lab, mas no host ideal eles são
# binários do store Nix — versionados, com PATH controlado, sem depender do
# diretório de trabalho. Serviços (doctor/heal) chamam o caminho do store.
#
# O rebuild.sh roda contra o repo local do usuário (~/nixos-config-reborn):
# o script referencia o flake, não o copia (o repo é o estado declarativo).
let
  rebuildSh = pkgs.writeShellApplication {
    name = "jarvis-rebuild";
    runtimeInputs = [pkgs.git pkgs.nh];
    text = ''
      set -e
      FLAKE_DIR="''${JARVIS_FLAKE_DIR:-$HOME/nixos-config-reborn}"
      TARGET_HOST="''${JARVIS_TARGET_HOST:-nixos-lab}"

      # nh 4.4.2+: usa NH_FLAKE; o FLAKE antigo dispara warning
      export NH_FLAKE="$FLAKE_DIR"
      unset FLAKE

      echo "[1/4] Reiniciando nix-daemon..."
      sudo systemctl restart nix-daemon

      echo "[2/4] Indexando alterações no Git para o Nix Flakes..."
      cd "$FLAKE_DIR"
      git add -A
      if git diff --cached --quiet; then
        echo "      (nenhuma alteração pendente)"
      else
        N_FILES=$(git diff --cached --name-only | wc -l)
        git commit -m "chore: update $N_FILES file(s)"
      fi
      cd - > /dev/null

      echo "[3/4] Executando Rebuild..."
      nh os switch "$FLAKE_DIR" -H "$TARGET_HOST" \
        -- --option binary-caches-parallel-connections 4 --option http-connections 5 \
        | grep -E "error:|at .*\.nix" || true

      echo "[4/4] Sistema atualizado!"
    '';
  };

  cleanSh = pkgs.writeShellApplication {
    name = "jarvis-clean";
    runtimeInputs = [pkgs.nix];
    text = ''
      GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
      echo -e "''${BLUE}=== FAXINA COMPLETA NO NIXOS ===''${NC}"

      echo -e "\n''${YELLOW}[1/5] Home Manager: expirando gerações...''${NC}"
      if command -v home-manager > /dev/null; then
        home-manager expire-generations "-0 days"
        home-manager remove-generations old
      fi

      echo -e "\n''${YELLOW}[2/5] Perfis do usuário + GC (7d)...''${NC}"
      nix-env --delete-generations old
      nix-collect-garbage --delete-older-than 7d

      echo -e "\n''${YELLOW}[3/5] Gerações do sistema + histórico de boot...''${NC}"
      sudo nix-env --profile /nix/var/nix/profiles/system --delete-generations old
      sudo nix-profile wipe-history --profile /nix/var/nix/profiles/system 2>/dev/null || true

      echo -e "\n''${YELLOW}[4/5] Garbage collector profundo...''${NC}"
      sudo nix-collect-garbage -d

      echo -e "\n''${YELLOW}[5/5] Otimização do store (hardlinks)...''${NC}"
      sudo nix-store --optimise

      echo -e "\n''${GREEN}=== FAXINA CONCLUÍDA ===''${NC}"
      df -h /nix
    '';
  };

  fixQdrantSh = pkgs.writeShellApplication {
    name = "jarvis-fix-qdrant";
    text = ''
      # Qdrant pós-upgrade: storage da base antiga é incompatível → descarta o
      # estado de runtime recriável e reinicia. (Ver README.)
      if [ ! -d /var/lib/qdrant/storage ]; then
        echo "storage do qdrant não encontrado — nada a fazer."
        exit 0
      fi
      sudo systemctl stop qdrant
      sudo rm -rf /var/lib/qdrant/storage
      sudo systemctl start qdrant
      echo "qdrant reiniciado com storage recriado."
    '';
  };
in {
  # Ativa com: programs.jarvis-scripts.enable = true
  options.programs.jarvis-scripts = {
    enable = lib.mkEnableOption "scripts de manutenção JARVIS (rebuild/clean/fix-qdrant) no store";
  };

  config = lib.mkIf config.programs.jarvis-scripts.enable {
    environment.systemPackages = [rebuildSh cleanSh fixQdrantSh];
    # Comandos `rebuild`, `clean`, `fix-qdrant` disponíveis no PATH (binários
    # do store, não scripts soltos). O doctor/heal referenciam esses binários.
  };
}
