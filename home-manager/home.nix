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

  # ══════════════════════════════════════════════════════════════
  # AIDER — Qwen3.6-35B-A3B via llama.cpp local
  # Uso: basta rodar `aider` (tudo nas configs abaixo)
  # Benchmark: 32 t/s decode, 367 t/s prefill, 4179 MiB VRAM
  # ══════════════════════════════════════════════════════════════

  # 1. Configuração principal — flags que o aider lê do conf
  home.file.".aider.conf.yml".text = ''
    # Conexão com nosso llama.cpp local
    openai-api-base: "http://localhost:8080/v1"
    openai-api-key: "sk-dummy"
    model: "openai/qwen3-35b-a3b"

    # Edição: diff (SEARCH/REPLACE) — mais eficiente que whole
    edit-format: diff

    # Autonomia: executa sem pedir confirmação
    yes-always: true
    auto-commits: true
    dirty-commits: true

    # Performance: sem stream (resposta completa), sem cache de prompts
    no-stream: true
    no-cache-prompts: true

    # Limpar output: sem warnings nem validação de settings
    no-show-model-warnings: true
    no-check-model-accepts-settings: true

    # Repo map: 512 tokens (suficiente, economiza 1.7k tokens por request)
    map-tokens: 512
    map-refresh: auto
  '';

  # 2. Metadata — limites de contexto e custos
  home.file.".aider.model.metadata.json".text = ''
    {
      "openai/qwen3-35b-a3b": {
        "max_input_tokens": 131072,
        "max_output_tokens": 4096,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openai",
        "mode": "chat"
      }
    }
  '';

  # 3. Settings do modelo — comportamento, thinking, system prompt
  home.file.".aider.model.settings.yml".text = ''
    - name: openai/qwen3-35b-a3b
      # Edição: diff com SEARCH/REPLACE blocks
      edit_format: diff

      # Repo map: aider mapeia o projeto para navegar arquivos
      use_repo_map: true

      # Lazy: false = aplica edits imediatamente (não espera confirmação)
      lazy: false

      # Reminder: sys = lembretes no system prompt (mais estável)
      reminder: sys

      # Examples: no system prompt (economiza tokens)
      examples_as_sys_msg: true

      # Thinking: mostra reasoning separadamente do output
      reasoning_tag: think

      # System prompt: instrução de autonomia
      system_prompt_prefix: >-
        You are an autonomous coding agent. You execute all actions yourself.
        NEVER ask the user to run commands or edit files manually.
        Read files, generate SEARCH/REPLACE blocks, suggest shell commands.
        Be concise. No unnecessary explanations.

      # Parâmetros do modelo
      extra_params:
        max_tokens: 4096
        temperature: 0.1
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
