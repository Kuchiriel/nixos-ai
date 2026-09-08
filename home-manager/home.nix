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
    # Reconcilia auth.json do opencode com o env (fonte da verdade).
    # Mata a classe "colei a chave e continua dando token error": chave
    # apodrecida no state é sobrescrita pela chave boa do /etc/litellm.env.
    if [ -x ~/.config/ai-agents/opencode-auth-sync.sh ]; then
      ~/.config/ai-agents/opencode-auth-sync.sh >/dev/null 2>&1 || true
    fi
    # RVC voice-clone (timbre Jarvis): env canônico em scripts/rvc-env.sh
    # (só exporta se o spike existir; pós-reboot: ./scripts/rvc-spike-bootstrap.sh).
    # O python do venv usa o loader nix-ld → sem LD_LIBRARY_PATH manual.
    source ${../scripts/rvc-env.sh}
  '';

  # Sync declarativo opencode auth.json <- env (nunca commita segredos:
  # o script lê do env em runtime; aqui vai só o código do sync).
  home.file.".config/ai-agents/opencode-auth-sync.sh".source = builtins.toFile "opencode-auth-sync.sh" ''
    #!/usr/bin/env bash
    # Reconcilia ~/.local/share/opencode/auth.json com as chaves do env.
    # Env é a fonte da verdade (/etc/litellm.env via keys-wrapper.sh).
    # Só toca providers com chave válida no env; nunca exibe valores.
    set -u
    AUTH="$HOME/.local/share/opencode/auth.json"
    [ -f "$AUTH" ] || exit 0
    [ -n "$OPENROUTER_API_KEY" ] || [ -n "$GROQ_API_KEY" ] || [ -n "$CEREBRAS_API_KEY" ] || [ -n "$NVIDIA_API_KEY" ] || [ -n "$GEMINI_API_KEY" ] || [ -n "$TOGETHER_API_KEY" ] || [ -n "$HF_TOKEN" ] || exit 0
    python3 - "$AUTH" <<'PYEOF'
    import json, os, sys
    path = sys.argv[1]
    mapping = {
        "openrouter": os.environ.get("OPENROUTER_API_KEY", ""),
        "groq": os.environ.get("GROQ_API_KEY", ""),
        "cerebras": os.environ.get("CEREBRAS_API_KEY", ""),
        "nvidia": os.environ.get("NVIDIA_API_KEY", ""),
        "google": os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", ""),
        "together": os.environ.get("TOGETHER_API_KEY", "") or os.environ.get("TOGETHERAI_API_KEY", ""),
        "huggingface": os.environ.get("HF_TOKEN", "") or os.environ.get("HUGGINGFACE_API_KEY", ""),
    }
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        sys.exit(0)
    changed = []
    for provider, key in mapping.items():
        if not key or len(key) < 8:
            continue
        entry = data.get(provider)
        if not isinstance(entry, dict):
            entry = {"type": "api"}
            data[provider] = entry
        if entry.get("key") != key:
            entry["key"] = key
            entry["type"] = "api"
            changed.append(provider)
    if changed:
        # backup do original antes de sobrescrever
        try:
            import shutil
            shutil.copy2(path, path + ".prev")
        except OSError:
            pass
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print("opencode auth sync: " + ", ".join(changed))
    PYEOF
  '';
  home.file.".config/ai-agents/opencode-auth-sync.sh".executable = true;

  # ZSH — emacs keybindings (Ctrl+A/E/Ctrl+K, etc)
  programs.zsh = {
    enable = true;
    # ZSH é o shell padrão do usuário (nixos): aqui também precisa das
    # chaves + sync do opencode (bash.initExtra não roda em zsh).
    initContent = ''
      # Emacs mode: Ctrl+A = início da linha, Ctrl+E = fim
      bindkey -e
      # Ctrl+R = busca reversa no histórico
      bindkey '^R' history-incremental-search-backward
      # Ctrl+W = deletar palavra
      bindkey '^W' backward-kill-word
      # Ctrl+U = deletar até início da linha
      bindkey '^U' backward-kill-line
      # Chaves das APIs (fonte da verdade: /etc/litellm.env)
      if [ -f "$HOME/.config/ai-agents/keys-wrapper.sh" ]; then
        set -a
        source "$HOME/.config/ai-agents/keys-wrapper.sh"
        set +a
      fi
      # Reconcilia auth.json do opencode com o env
      if [ -x "$HOME/.config/ai-agents/opencode-auth-sync.sh" ]; then
        "$HOME/.config/ai-agents/opencode-auth-sync.sh" >/dev/null 2>&1 || true
      fi
      # RVC voice-clone (timbre Jarvis): mesma fonte canônica do bash.
      # Sem isso, `jarvis speak --clone` no zsh falha com JARVIS_RVC_PYTHON ausente.
      source ${../scripts/rvc-env.sh}
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

  # (STT small vive em modules/ai/models.nix → linkado pelo wakeword nix;
  # tiny.en foi removido: nada o referencia e é English-only.)

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
    # Secrets avulsos (best-effort: arquivos root-only são ignorados no shell,
    # mas lidos pelos services via EnvironmentFile; o env prevalece sempre).
    if [ -z "$TAVILY_API_KEY" ]; then
        TAVILY_API_KEY=$(cut -d= -f2 /etc/jarvis-secrets/tavily.env 2>/dev/null)
        [ -n "$TAVILY_API_KEY" ] && export TAVILY_API_KEY
    fi
    if [ -z "$HMD_API_ACCESS_TOKEN" ]; then
        HMD_API_ACCESS_TOKEN=$(cut -d= -f2 /etc/jarvis-secrets/hackmd.env 2>/dev/null)
        [ -n "$HMD_API_ACCESS_TOKEN" ] && export HMD_API_ACCESS_TOKEN
    fi
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
    # Fonte única: overlay `kilo` (nixpkgs-unstable; dan-online parou em 05/2026).
    package = pkgs.kilo;

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
            # {env:VAR} é a sintaxe que o opencode expande (NÃO ${VAR}).
            apiKey = "{env:OPENROUTER_API_KEY}";
            headers = {
              "HTTP-Referer" = "http://localhost:5173";
              "X-Title" = "Jarvis WebUI";
            };
          };
          models = {
            "free" = {
              name = "OpenRouter Free Cascade";
            };
            "qwen/qwen3-coder" = {
              name = "Qwen Coder";
            };
            "qwen/qwen3-coder:free" = {
              name = "Qwen Coder Free (as vezes sem endpoint)";
            };
          };
        };
        
        # ADICIONADO: Groq (fast LLM cloud)
        groq = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api.groq.com/openai/v1";
            apiKey = "{env:GROQ_API_KEY}";
          };
          models = {
            "qwen/qwen3.6-27b" = {
              name = "Groq Qwen3.6 27B";
              # Tier grátis: OTPM 1000 → limita saída p/ caber (ITPM 7000 ainda
              # é apertado p/ o system prompt do opencode; requer tier pago p/ uso real).
              limit = {
                context = 131072;
                output = 800;
              };
            };
            "qwen/qwen3.8-27b" = {
              name = "Groq Qwen3.8 27B";
              limit = {
                context = 131072;
                output = 800;
              };
            };
          };
        };
        
        # ADICIONADO: Cerebras (fast inference)
        cerebras = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api.cerebras.ai/v1";
            apiKey = "{env:CEREBRAS_API_KEY}";
          };
          models = {
            "qwen-3.8-27b" = {
              name = "Cerebras Qwen3.8 27B";
            };
          };
        };

        # ADICIONADO: Together AI (open-source models)
        together = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api.together.xyz/v1";
            apiKey = "{env:TOGETHER_API_KEY}";
          };
          models = {
            "meta-llama/Llama-3.3-70B-Instruct-Turbo" = {
              name = "Llama 3.3 70B Turbo";
            };
            "Qwen/Qwen3-Coder-480B-A35B-Instruct" = {
              name = "Qwen3 Coder 480B";
            };
          };
        };

        # ADICIONADO: HuggingFace Inference API
        huggingface = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api-inference.huggingface.co/v1";
            apiKey = "{env:HF_TOKEN}";
          };
          models = {
            "Qwen/Qwen3-235B-A22B-Instruct-2507" = {
              name = "Qwen3 235B HF";
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
    # Verificação wakeword OFFLINE (ww_scorer.py): 0.4 (0.5 rejeitava wake
    # real a 0.49 no ruído; ruído ambiente fica <0.15 — forense 2026-09).
    wakeThreshold = 0.4;
    # Pipeline de voz: STT (faster-whisper) → LLM (llama.cpp) → TTS (Kokoro+RVC)
    # --clone: timbre Jarvis coerente com ack/persona (~+20s/turno; com fallback
    # p/ TTS puro se o spike /tmp sumir). O wakeword grava WAV e passa como arg.
    brainCommand = ["jarvis" "voice" "--clone"];
  };

  # ══════════════════════════════════════════════════════════════
  home = {
    username = user;
    homeDirectory = "/home/${user}";
    stateVersion = homeStateVersion;
  };
}
