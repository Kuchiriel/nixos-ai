# ═══ Service Modules ═══
# Importação explícita — substitui readDir dinâmico.
# Adicione novos serviços aqui ao invés de depender de discovery.

{...}: {
  imports = [
    ./jarvis-gaming.nix
    ./jarvis-heal.nix
    ./jarvis-idle.nix
    ./jarvis-watchdog.nix
    ./jarvis-telegram.nix
    ./jarvis-vault.nix
    ./jarvis-webui.nix
    ./litellm-cascade.nix
    ./llama-cpp.nix
    ./llama-fan-control.nix
    ./nightwatch-timer.nix
    ./qdrant.nix
  ];
}
