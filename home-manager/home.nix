{ homeStateVersion, user, pkgs, ... }: {
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
  #    sudo cp /etc/litellm.env ~/.config/litellm.env && chmod 600 ~/.config/litellm.env
  #    echo '[ -f ~/.config/litellm.env ] && set -a && . ~/.config/litellm.env && set +a' >> ~/.bashrc

  home.sessionVariables = {
    _JAVA_AWT_WM_NONREPARENTING = "1";
    AWT_TOOLKIT = "MToolkit";
    JAVA_TOOL_OPTIONS = "-Dsun.java2d.uiScale=1";
    # Oculta o aviso de falta de botocore/aws do LiteLLM no Aider
    LITELLM_LOG = "ERROR";
  };

  # Importa as variáveis de ambiente com segurança ao abrir o terminal
  programs.bash.initExtra = ''
    if [ -f /etc/litellm.env ]; then
      set -a
      source /etc/litellm.env
      set +a
    fi
  '';

  # Garante que as ferramentas universais de AST/tags estejam disponíveis no PATH do usuário para o Aider
  home.packages = with pkgs; [
    universal-ctags
  ];

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
  # JARVIS STT — Download declarativo do modelo faster-whisper-tiny.en
  # ══════════════════════════════════════════════════════════════
  home.file.".local/share/jarvis/voice/models--Systran--faster-whisper-tiny.en/snapshots/main/model.bin".source = pkgs.fetchurl {
    url = "https://huggingface.co/Systran/faster-whisper-tiny.en/resolve/main/model.bin";
    hash = "sha256-Glr64GpNuRyXXJqdeL5cwRDuTqAirVfVVJLkVQ6Tayo=";
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

    # Repo map: mantido enxuto em 512 tokens para acelerar o prefill no llama.cpp
    map-tokens: 512
    map-refresh: auto
  '';

  # 2. Metadata — limites de contexto e custos (com margem para raciocínio)
  home.file.".aider.model.metadata.json".text = ''
    {
      "openai/qwen3-35b-a3b": {
        "max_input_tokens": 131072,
        "max_output_tokens": 8192,
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

      # Repo map: aider mapeia o projeto para navegar arquivos autonomamente
      use_repo_map: true

      # Lazy: false = aplica edits imediatamente (não espera confirmação)
      lazy: false

      # Reminder: sys = lembretes no system prompt (mais estável)
      reminder: sys

      # Examples: no system prompt (economiza tokens)
      examples_as_sys_msg: true

      # Thinking: captura e exibe a tag de raciocínio do modelo
      reasoning_tag: think

      # System prompt: força concisão no raciocínio e execução obrigatória do código
      system_prompt_prefix: >-
        You are an autonomous execution coding agent.
        You have direct access to the repo map. NEVER ask the user to manually attach, paste, or inspect files.
        Keep your reasoning inside <think> extremely brief and concise (max 3-4 sentences).
        You MUST focus your token budget on outputting the SEARCH/REPLACE diff blocks and terminal commands.
        NEVER exhaust your turn in thinking without writing the actual code edits.

      # Parâmetros do modelo
      extra_params:
        max_tokens: 8192
        temperature: 0.2
  '';

  services.jarvis-wakeword = {
    enable = true;
    # Calibração validada do legado (docs/architecture/legacy-audio-calibration.md):
    # 0.85 = menos false positives com ventoinha/sons de casa
    threshold = 0.15;  # Voz ~0.33, ruído ~0.002. 0.15 = seguro
    # RMS gate: ignora score alto se RMS < 500 (evita falsos positivos)
    rmsGate = 500;
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
