{
  config,
  lib,
  pkgs,
  ...
}:
# ═══════════════════════════════════════════════════════════════════════
# JARVIS-ENV — Master orchestrator do ecossistema Jarvis.
#
# Dois switches centrais:
#   1. services.jarvis.enable  — liga/desliga TODO o ecossistema
#   2. services.jarvis.environment — "vm" ou "host" (profile de execução)
#
# Hierarquia systemd:
#   jarvis.target (multi-user.target)
#       ├── qdrant.service (infraestrutura base)
#       ├── llama-cpp-server.service (inferência)
#       ├── jarvis-heal.service (auto-reparo)
#       ├── jarvis-idle-worker.timer (manutenção)
#       ├── jarvis-telegram.service (notificações)
#       ├── jarvis-vault-summarize.timer (memória)
#       └── jarvis-gaming-watcher.service (resource profiles)
#
# Quando services.jarvis.enable = false:
#   - NENHUM serviço Jarvis inicia no boot
#   - NENHUMA configuração de runtime é ativada
#   - Modelos NÃO são baixados (fetchurl é lazy — se ninguém referencia, não baixa)
#
# IMPORTANTE: mkIf NÃO impede avaliação de toda expressão no módulo.
# O Nix ainda avalia a estrutura. O objetivo é evitar materialização/ativação.
# ═══════════════════════════════════════════════════════════════════════
with lib; {
  options.services.jarvis = {
    enable = mkEnableOption "Jarvis Ecosystem (master toggle for all Jarvis services)";

    environment = mkOption {
      type = types.enum ["vm" "host"];
      default = "vm";
      description = ''
        Recipiente do sistema: "vm" = Lab (CPU, sem GPU, modo leve) e
        "host" = bare metal (RTX 4050 6GB + iGPU, MoE com expert offload).
        Todos os módulos (llama-cpp, waybar, mpvpaper, hyprland) consomem
        este único switch — troque aqui, o corpo inteiro reage no rebuild.
      '';
    };
  };

  config = mkIf config.services.jarvis.enable {
    # ═══════════════════════════════════════════════════════════════════
    # JARVIS TARGET — target mestre do ecossistema
    # ═══════════════════════════════════════════════════════════════════
    systemd.targets.jarvis = {
      description = "Jarvis AI Ecosystem";
      wants = [
        "qdrant.service"
        "llama-cpp-server.service"
        "jarvis-gaming-watcher.service"
      ];
      after = [
        "qdrant.service"
        "llama-cpp-server.service"
      ];
    };

    # ═══════════════════════════════════════════════════════════════════
    # TMPFILES — diretórios base do ecossistema
    # ═══════════════════════════════════════════════════════════════════
    systemd.tmpfiles.rules = [
      "d /var/lib/jarvis 0755 root root -"
      "d /var/lib/jarvis/models 0755 root root -"
      "h /var/lib/jarvis/models - - - - +C"
    ];
  };
}
