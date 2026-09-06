{
  homeStateVersion,
  user,
  pkgs,
  inputs,
  ...
}: {
  imports = [
    ./modules
    ./home-packages.nix
    ./modules/rclone-sync.nix
    ./modules/ai
    ./modules/services/jarvis-wakeword.nix
    # coding: coding agents (Pi, OpenCode)
    # ./modules/coding/pi.nix
    # ./modules/coding/shared/default.nix
    # VS Code + Roo Code (100% declarativo)
    ./modules/vscode-roo.nix
  ];

  stylix.targets.hyprland.enable = false;

  # ⚠️ SEGREDOS: NUNCA coloque API keys aqui (vazam para o repo/git history).
  # O padrão do projeto é /etc/litellm.env (chmod 600, criado manualmente no
  # host, fora do git) — o serviço services.litellm lê de lá. Para o aider
  # enxergar a chave na sessão interativa:
  #    sudo cp /etc/litellm.env ~/.config/litellm.env && chmod 600 ~/.config/litellm.env
  #    echo '[ -f ~/.config/litellm.env ] && set -a && . ~/.config/litellm.env && set +a' >> ~/.bashrc

  # ── stt-ptt: Push-to-Talk STT com Whisper ──────────────────
  # stt-ptt.enable = true;
  # stt-ptt.model = "ggml-large-v3-turbo";
  # stt-ptt.language = "pt";

  # ── coding: coding agents (Pi, OpenCode) ──────────────────
  # Pi agent desabilitado — renderForPi precisa de agente "primary" no repo AGENTS
  # Para reativar, adicione um agente com mode="primary" no repo AGENTS

  # coding.agents.pi.enable = false;

  home.sessionVariables = {
    _JAVA_AWT_WM_NONREPARENTING = "1";
    AWT_TOOLKIT = "MToolkit";
    JAVA_TOOL_OPTIONS = "-Dsun.java2d.uiScale=1";
    # Oculta o aviso de falta de botocore/aws do LiteLLM no Aider
    LITELLM_LOG = "ERROR";
  };

  # Importa as variáveis de ambiente com segurança ao abrir o terminal
  programs.bash.initExtra = ''
    if [ -f ~/.config/ai-agents/keys-wrapper.sh ]; then
      set -a
      source ~/.config/ai-agents/keys-wrapper.sh
      set +a
    fi
  '';

  # ZSH — emacs keybindings (Ctrl+A/E/Ctrl+K, etc)
  programs.zsh = {
    enable = true;
    initContent = ''
      # Emacs mode: Ctrl+A = início da linha, Ctrl+E = fim
      bindkey -e
      # Ctrl+R = busca reversa no histórico
      bindkey '^R' history-incremental-search-backward
      # Ctrl+W = deletar palavra
      bindkey '^W' backward-kill-word
      # Ctrl+U = deletar até início da linha
      bindkey '^U' backward-kill-line
    '';
  };

  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };

  # Garante que as ferramentas universais de AST/tags estejam disponíveis no PATH do usuário para o Aider
  home.packages = with pkgs; [
    universal-ctags
  ];

  # ══════════════════════════════════════════════════════════════
  # JARVIS STT — Download declarativo do modelo faster-whisper-tiny.en
  # ══════════════════════════════════════════════════════════════
  home.file.".local/share/jarvis/voice/models--Systran--faster-whisper-tiny.en/snapshots/main/model.bin".source = pkgs.fetchurl {
    url = "https://huggingface.co";
    # ATUALIZADO: Substituído pelo hash correto apontado pelo log do Nix
    hash = "sha256-RNPNvS2++DhYGMDtE5nans36CII9kdDo/acqVxwx2Qs=";
  };

  # ══════════════════════════════════════════════════════════════
  # JARVIS — API Keys abstraction (keys-wrapper.sh + keys.env)
  # ══════════════════════════════════════════════════════════════
  home.file.".config/ai-agents/keys.env".source = builtins.toFile "jarvis-keys.env" ''
    source /etc/litellm.env 2>/dev/null || true
  '';

  home.file.".config/ai-agents/keys-wrapper.sh".source = builtins.toFile "jarvis-keys-wrapper.sh" ''
    #!/usr/bin/env bash
    # Abstração de chaves para IA agents.
    # Source este script em vez de keys.env diretamente para ter nomes normalizados.
    # Resolve: TOGETHER_API_KEY vs TOGETHERAI_API_KEY, HF_TOKEN vs HUGGINGFACE_API_KEY, etc.

    set -a
    source "/home/$USER/.config/ai-agents/keys.env" 2>/dev/null || source "/etc/litellm.env" 2>/dev/null || true
    set +a

    if [ -z "$TOGETHER_API_KEY" ] && [ -n "$TOGETHERAI_API_KEY" ]; then
        export TOGETHER_API_KEY="$TOGETHERAI_API_KEY"
    fi
    if [ -z "$HF_TOKEN" ] && [ -n "$HUGGINGFACE_API_KEY" ]; then
        export HF_TOKEN="$HUGGINGFACE_API_KEY"
    fi
    if [ -z "$HUGGINGFACE_API_KEY" ] && [ -n "$HF_TOKEN" ]; then
        export HUGGINGFACE_API_KEY="$HF_TOKEN"
    fi
    if [ -z "$GEMINI_API_KEY" ] && [ -n "$GOOGLE_API_KEY" ]; then
        export GEMINI_API_KEY="$GOOGLE_API_KEY"
    fi
  '';
  home.file.".config/ai-agents/keys-wrapper.sh".executable = true;

  # ── VS Code + Roo Code — configurado via módulo vscode-roo.nix ──
  # (extensões, userSettings, MCP, custom modes são declarativos)
  vscode-roo = {
    enable = true;
  };

  # Aliases rápidos para as ferramentas de IA em nuvem
  home.shellAliases = {
    kilo = "opencode";
    agy  = "antigravity-ide";
  };

  # ══════════════════════════════════════════════════════════════
  # CONFIGURAÇÃO DECLARATIVA DOS AGENTES CLOUD (KILO & ANTIGRAVITY)
  # ══════════════════════════════════════════════════════════════

  # 1. Configuração do Antigravity IDE (Settings do Usuário via XDG)
  xdg.configFile."antigravity-ide/User/settings.json".text = builtins.toJSON {
    "antigravity.agent.customInstructions" = ''
      Você opera dentro de um monorepo localizado em /home/nixos/projects. Antes de sugerir alterações, contextualize-se obrigatoriamente lendo as diretrizes centrais nos arquivos:
      - /home/nixos/projects/AGENTS.md
      - /home/nixos/projects/BUFFY.md
      - /home/nixos/projects/nixos-ai/AGENTS.md
      - /home/nixos/projects/nixos-ai/BUFFY.md

      Nossa documentação utiliza Obsidian Wikilinks no padrão [[Nome da Nota]]. Sempre que encontrar essa sintaxe, resolva o link buscando o arquivo .md correspondente dentro do Vault em /home/nixos/vaults/projects/ para se situar perfeitamente.
    '';
    "gemini.systemPrompt" = "Veja as diretrizes em antigravity.agent.customInstructions.";
    "telemetry.telemetryLevel" = "off";
  };

 # ══════════════════════════════════════════════════════════════
  # CONFIGURAÇÃO DECLARATIVA DO OPENCODE (MÓDULO ANTIGO E ESTÁVEL)
  # ══════════════════════════════════════════════════════════════
  programs.opencode = {
    enable = true;
    package = inputs.opencode-flake.packages.${pkgs.system}.default;

    settings = {
      # Provedor local (Bonsai 8B ternário via llama.cpp PrismML, porta 8080)
      provider = {
        local = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "http://127.0.0.1:8080/v1";
          };
          models = {
            "qwen3-35b-a3b" = {
              name = "Qwen3 35B Local";
            };
            "bonsai-8b" = {
              name = "Bonsai 8B Local (ternary)";
            };
          };
        };
        
        # ADICIONADO: Provedor oficial da Google para rodar na nuvem estável
        google = {
          npm = "@ai-sdk/google";
          models = {
            "gemini-2.5-flash" = {
              name = "Gemini 2.5 Flash Cloud";
            };
          };
        };
        
        # ADICIONADO: OpenRouter (cascade/fallback free tier)
        openrouter = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://openrouter.ai/api/v1";
            headers = {
              "Authorization" = "Bearer \${OPENROUTER_API_KEY}";
              "HTTP-Referer" = "http://localhost:5173";
              "X-Title" = "Jarvis WebUI";
            };
          };
          models = {
            "free" = {
              name = "OpenRouter Free Cascade";
            };
            "qwen/qwen3-coder:free" = {
              name = "Qwen Coder Free";
            };
          };
        };
        
        # ADICIONADO: Groq (fast LLM cloud)
        groq = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api.groq.com/openai/v1";
            headers = {
              "Authorization" = "Bearer \${GROQ_API_KEY}";
            };
          };
          models = {
            "llama-3.3-70b-versatile" = {
              name = "Groq Llama 3.3 70B";
            };
          };
        };
        
        # ADICIONADO: Cerebras (fast inference)
        cerebras = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api.cerebras.ai/v1";
            headers = {
              "Authorization" = "Bearer \${CEREBRAS_API_KEY}";
            };
          };
          models = {
            "llama3.1-70b" = {
              name = "Cerebras Llama 3.1 70B";
            };
          };
        };
      };
      
      # Define o modelo padrão para cascade/fallback
      model = "openrouter/free";

      # MCP Jarvis: RAG, memória, vault, files, shell, nix — via stdio.
      # Handshake validado (tools/list retorna 20 tools). Env inline no
      # bash -c porque o campo environment nem sempre é repassado.
      mcp = {
        jarvis = {
          type = "local";
          command = [ "bash" "-c" "cd /home/nixos/projects/nixos-ai && PYTHONPATH=modules/ai/jarvis/src JARVIS_PROJECT_ROOT=/home/nixos/projects/nixos-ai exec /etc/profiles/per-user/nixos/bin/python3 -m jarvis.mcp_server" ];
          cwd = "/home/nixos/projects/nixos-ai";
          enabled = true;
          timeout = 30000;
        };
      };
    };
  };

  # ══════════════════════════════════════════════════════════════
  # AIDER — Qwen3.6-35B-A3B via llama.cpp local
  # Uso: basta rodar `aider` (tudo nas configs abaixo)
  # Benchmark: 32 t/s decode, 367 t/s prefill, 4179 MiB VRAM
  # ══════════════════════════════════════════════════════════════

  # 1. Configuração principal do Aider
  home.file.".aider.conf.yml".text = ''
    openai-api-base: "http://localhost:8080/v1"
    openai-api-key: "sk-dummy"
    model: "openai/qwen3-35b-a3b"

    architect: true

    edit-format: diff
    yes-always: true
    auto-commits: true
    dirty-commits: true

    subtree-only: true
    auto-test: false
    suggest-shell-commands: false
    aiderignore: ".aiderignore"

    no-stream: false
    no-cache-prompts: true
    no-show-model-warnings: true
    no-check-model-accepts-settings: true

    # Mantém o mapa do repositório em 512 tokens para prefill ultrarrápido
    map-tokens: 8192
    map-refresh: auto
  '';

  home.file.".aiderignore".text = ''
    # Segredos, Chaves e Envs
    *.env
    *.pem
    *.key
    *.token
    /etc/litellm.env
    /etc/jarvis-telegram.env

    # Modelos de IA, Pesos e Assets Pesados
    *.gguf
    *.bin
    *.pt
    *.safetensors
    *.onnx
    /modules/ai/models/

    # Bancos de Dados, Vetores e Caches de Áudio do Jarvis
    /qdrant_data/
    *.sqlite
    *.db
    *.wav
    *.mp3
    *.flac
    *.pcm

    # Caches, Venvs, Nix Stores e Artefatos de Build
    .direnv/
    .venv/
    venv/
    __pycache__/
    *.pyc
    .pytest_cache/
    .hypothesis/
    .mypy_cache/
    .ruff_cache/
    result
    result-*

    # Logs, Trava de Sistema e Configs Específicas
    logs/
    *.log
    hosts/nitro-v15/hardware-configuration.nix
    .aider*
    *.zip
    *.tar.gz

    # Documentação Extensa / Markdown Secundários (Economiza Tokens de Contexto)
    #docs/
    #*.md
  '';

  # 2. Metadata — Limite ampliado para 8192 output tokens
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

  home.file.".aider.model.settings.yml".text = ''
    - name: openai/qwen3-35b-a3b
      edit_format: diff
      use_repo_map: true
      lazy: false
      reminder: sys
      examples_as_sys_msg: true
      reasoning_tag: null

      system_prompt_prefix: |
        You are an elite senior systems engineering AI partner.
        Rules of Engagement:
        1. Act with absolute epistemic rigor. Never assume, guess, or invent file contents, logs, or states. If context is missing, state it explicitly.
        2. Provide exact, minimal SEARCH/REPLACE blocks for code modifications. Do not break existing logic.
        3. Keep explanations strictly technical and concise. Eliminate fluff, pleasantries, or meta-commentary. Focus purely on code execution and architecture.
      extra_params:
        max_tokens: 8192
        temperature: 0.0
  '';

  services.jarvis-wakeword = {
    enable = true;
    ackLang = "pt"; # Jarvis fala PT-BR (sistema em en_US, usuário em PT-BR)
    # Device: physical mic (rnnoise_source has no audio routing on this hardware)
    device = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source";
    # Calibração validada do legado:
    # 0.20 = sensível o suficiente para voz normal
    threshold = 0.20;
    # RMS gate: ignora score alto se RMS < 500 (evita falsos positivos)
    rmsGate = 500;
    # Pipeline de voz: STT (faster-whisper) → LLM (llama.cpp) → TTS (Kokoro)
    # O wakeword grava WAV e passa como argumento para 'jarvis voice'
    brainCommand = ["jarvis" "voice"];
  };

  # ══════════════════════════════════════════════════════════════
  home = {
    username = user;
    homeDirectory = "/home/${user}";
    stateVersion = homeStateVersion;
  };
}
