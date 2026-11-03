# ═══ Service Modules ═══
# Importação explícita — substitui readDir dinâmico.
# Adicione novos serviços aqui ao invés de depender de discovery.

{...}: {
  imports = [
    ./chromium-cdp.nix
    ./charger-watch.nix
    ./jarvis-focus.nix
    ./jarvis-gaming.nix
    ./jarvis-heal.nix
    ./jarvis-keys-env.nix
    ./jarvis-idle.nix
    ./jarvis-notify.nix
    ./jarvis-watchdog.nix
    ./jarvis-telegram.nix
    ./jarvis-vault.nix
    ./jarvis-webui.nix
    ./jarvis-webui-frontend.nix
    ./litellm-cascade.nix
    ./llama-cpp.nix
    ./llama-fan-control.nix
    ./llama-uncensored.nix
    ./nightwatch-timer.nix
    ./audiobook-audit-timer.nix
    ./jarvis-consolidate-timer.nix
    ./qdrant.nix
    ./vision-moondream.nix
  ];
}
