{ homeStateVersion, user, ... }: {
  imports = [
    ./modules
    ./home-packages.nix
    ./modules/rclone-sync.nix
    ./modules/ai
    ./modules/services/jarvis-wakeword.nix
  ];

  # ⚠️ SEGREDOS: NUNCA coloque API keys aqui (vazam para o repo/git history).
  # O padrão do projeto é /etc/litellm.env (chmod 600, criado manualmente no
  # host, fora do git) — o serviço services.litellm lê de lá. Para o aider
  # enxergar a chave na sessão interativa:
  #   sudo cp /etc/litellm.env ~/.config/litellm.env && chmod 600 ~/.config/litellm.env
  #   echo '[ -f ~/.config/litellm.env ] && set -a && . ~/.config/litellm.env && set +a' >> ~/.bashrc
  home.sessionVariables = { };

  # Importa as variáveis de ambiente com segurança ao abrir o terminal

  programs.bash.initExtra = ''
    if [ -f /etc/litellm.env ]; then
      set -a
      source /etc/litellm.env
      set +a
    fi
  '';

  home.file.".aider.conf.yml".text = ''
    openai-api-base: http://localhost:8080/v1
    model: openai//nix/store/dw121d64zaschr6nw19lwvhl3mmnzh0a-Qwen3-4B-Q4_K_M.gguf
    auto-commits: true
    dirty-commits: true
    # A chave GROQ_API_KEY vem do ambiente (ver comentário acima)
  '';

  services.jarvis-wakeword = {
    enable = true;
    # Calibração validada do legado (docs/architecture/legacy-audio-calibration.md):
    # 0.85 = menos false positives com ventoinha/sons de casa
    threshold = 0.85;
    # Pipeline de voz: STT (faster-whisper) → LLM (llama.cpp) → TTS (Kokoro)
    # O wakeword grava WAV e passa como argumento para 'jarvis voice'
    brainCommand = [ "jarvis" "voice" ];
  };


  home = {
    username = user;
    homeDirectory = "/home/${user}";
    stateVersion = homeStateVersion;
  };
}
