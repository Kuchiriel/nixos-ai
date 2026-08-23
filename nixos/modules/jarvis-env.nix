{
  lib,
  ...
}:
# ═══════════════════════════════════════════════════════════════════════
# JARVIS-ENV — o "cérebro do ambiente" (metáfora da água).
#
# UM switch central: `services.jarvis.environment` (vm | host). Todos os
# módulos bebem dele em vez de detectar o ambiente cada um do seu jeito:
#
#   - llama-cpp  → profile do models.nix (vm=CPU Qwen3-4B, host=MoE+GPU)
#   - waybar     → módulos por hardware (sem battery/bluetooth na VM)
#   - mpvpaper   → wallpaper animado só no host (iGPU)
#   - hyprland   → animações/efeitos por ambiente
#
# Por quê declarativo e não "auto-detect em build": o NixOS avalia a config
# ANTES do boot — não existe detecção em tempo de build. A água NixOS é:
# cada host declara seu recipiente (1 linha), e o corpo inteiro reage junto.
# A detecção em RUNTIME (systemd-detect-virt/lspci) fica para os serviços
# que precisam decidir ao vivo (hwdetect/hwprofile no Python).
# ═══════════════════════════════════════════════════════════════════════
with lib; {
  options.services.jarvis = {
    enable = mkEnableOption "JARVIS environment switch (vm/host)";

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
}
