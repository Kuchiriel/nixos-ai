{ homeStateVersion, user, ... }: {
  imports = [
    ./modules
    ./home-packages.nix
    ./modules/rclone-sync.nix
    ./modules/ai
    ./modules/services/jarvis-wakeword.nix
  ];

stylix.targets.hyprland.enable = false;

  # ⚠️ SEGREDOS: NUNCA coloque API keys aqui (vazam para o repo/git history).
  # O padrão do projeto é /etc/litellm.env (chmod 600, criado manualmente no
  # host, fora do git) — o serviço services.litellm lê de lá. Para o aider
  # enxergar a chave na sessão interativa:
  #   sudo cp /etc/litellm.env ~/.config/litellm.env && chmod 600 ~/.config/litellm.env
  #   echo '[ -f ~/.config/litellm.env ] && set -a && . ~/.config/litellm.env && set +a' >> ~/.bashrc

  home.sessionVariables = {
    _JAVA_AWT_WM_NONREPARENTING = "1";
    AWT_TOOLKIT = "MToolkit";
    JAVA_TOOL_OPTIONS = "-Dsun.java2d.uiScale=1";
  };

  # Importa as variáveis de ambiente com segurança ao abrir o terminal

  programs.bash.initExtra = ''
    if [ -f /etc/litellm.env ]; then
      set -a
      source /etc/litellm.env
      set +a
    fi
  '';
   
  programs.foot = {
    enable = true;
    settings = {
      main = {
        font = {
          _type = "override";
          priority = 50; # Define a força da substituição como mkForce
          content = "JetBrainsMono Nerd Font:size=12";
        };
      };
    };
  };

  # 1. Configuração do Aider — Qwen3.6-35B-A3B via llama.cpp local
  home.file.".aider.conf.yml".text = ''
    openai-api-base: "http://localhost:8080/v1"
    openai-api-key: "sk-dummy"
    model: "openai/custom-model"
    edit-format: diff
    auto-commits: true
    dirty-commits: true
    yes-always: true
    no-show-model-warnings: true
    no-check-model-accepts-settings: true
    no-cache-prompts: true
    no-stream: true
    map-tokens: 2048
    map-refresh: auto
  '';

  # 2. Metadata do modelo (limites de contexto)
  home.file.".aider.model.metadata.json".text = ''
    {
      "openai/custom-model": {
        "max_input_tokens": 131072,
        "max_output_tokens": 4096,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openai",
        "mode": "chat"
      }
    }
  '';

  # 3. Settings do modelo customizado (edit_format, system_prompt, thinking off)
  home.file.".aider.model.settings.yml".text = ''
    - name: openai/custom-model
      edit_format: diff
      use_repo_map: true
      lazy: false
      reminder: sys
      examples_as_sys_msg: true
      reasoning_tag: think
      system_prompt_prefix: >-
        You are an autonomous coding agent. You MUST execute all actions yourself.
        NEVER ask the user to run commands, edit files, or do anything manually.
        When you need to read a file, read it. When you need to edit, generate SEARCH/REPLACE blocks.
        When you need to run a shell command, suggest it in a ```bash block.
        Be concise and direct. Do not output thinking or reasoning text.
      extra_params:
        max_tokens: 4096
        temperature: 0.0
        extra_body:
          chat_template_kwargs:
            enable_thinking: false
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
