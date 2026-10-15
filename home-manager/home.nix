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
    ./modules/xref-watch.nix
    ./modules/sandbox-verificacao.nix
    ./modules/agents-heartbeat-watchdog.nix
    ./modules/ai
    ./modules/services/jarvis-wakeword.nix
    ./modules/services/sunshine.nix
    # opencode serve headless p/ o celular assumir a mesma sessao (tailnet)
    ./modules/services/opencode-serve.nix
    # ydotoald no lugar certo (XDG_RUNTIME_DIR) — sem isso o ydotool falha calado
    ./modules/services/ydotoold.nix
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
    # Computer-use (harness humanizado 24/09): digitação Wayland + OCR.
    # Mouse via python-evdev (uinput, dep do pacote jarvis).
    wtype
    tesseract
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

  # RTK plugin do opencode — declarativo (antes era arquivo solto fora do git).
  # 08/10: opt-out com `norrtk` + passthrough p/ ambientes explícitos
  # (venv/python -m/nix develop) — rewrite indiscriminado confundia modelos
  # fracos (rtk pytest rodava python do PATH sem pytest).
  home.file.".config/opencode/plugins/rtk.ts".source = ./files/opencode/plugins/rtk.ts;

  # Memory + safety plugin — plain .js (node --check validatable, 10/10
  # regex tests). Compaction hook injects the recall/remember protocol;
  # tool.execute.before denies unanchored root deletes via args rewrite.
  home.file.".config/opencode/plugins/memory.js".source = ./files/opencode/plugins/memory.js;

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
      # Direct LLMs GERADOS de models.nix directServers (14/10:
      # fim do hardcoded!). Services com `opencode = {key,name,context,
      # output}` viram providers (id+port da service = fonte única).
      # Router (:8080), local-fast (alias) e local_small_model manuais.
      provider = ({
        # FreeLLMAPI (:3001, 15/10 E2E) — o ROUTER de 34 free-providers
        # (212 models, failover por rate-limit, quota tracking). Key via
        # {env:FREELLMAPI_API_KEY} (/etc/litellm.env → keys-wrapper).
        # FIX 15/10: este bloco estava IRMÃO de `provider` no settings —
        # o gerador o emitia no top-level do opencode.json (junto de
        # `model`, `small_model`...), onde o CLI NUNCA lê: só
        # `provider.<id>` vira provider selecionável. Por isso "to sem
        # modelo". Move pra DENTRO do provider attrset.
        # Modelos: 'auto' = o router decide; catalog tem ids turvos
        # (anotações em .config/freellmapi/E2E-ANOTACOES.md) — começar
        # SÓ com auto e ir liberando ids conforme provados.
        # Probe AO VIVO 15/10 (HTTP :3001 + E2E via `opencode run` — o CLI
        # usa o system prompt do agente (~19k tok), que é o teste real):
        #   ✅ RESPONDEM: auto, gemini-3.5/2.5/3.1-flash-lite, qwen3.8-27b,
        #      gpt-oss-120b/20b, nemotron-3-super-120b, llama-4-scout,
        #      qwen2.5-coder-32b, qwq-32b, llama-3.1-8b,
        #      mistral-small-3.1-24b, llama-3.3-70b-fp8-fast,
        #      command-a, command-r7b, fusion
        #   🟡 RATE-LIMIT (manter — cooldown de free tier, volta sozinho):
        #      nemotron-3.5-lightning (quota diária OpenRouter :free)
        #   ❌ REMOVIDOS (motivo definitivo, não é rate-limit):
        #      claude-opus/sonnet/haiku-4-5 → 404 "not in catalog" (UNAVAILABLE)
        #      gemini-3.8/3.6/3.5-flash + gemini-2.5-flash → 502 upstream
        #        empty_completion (google key podre no router)
        #      nemotron-3-ultra-550b, deepseek-r1-distill, moondream → 502
        #      gemini-3.7-flash → timeout upstream
        #   Notas de uso (limitações reais dos FREE tiers, não defeito):
        #      qwen3.8-27b/lhama-3.3 ITPM 7-8k < system prompt do opencode —
        #        respondem por HTTP curto, nunca pelo agente CLI;
        #      aya-expanse-32b: sem tool-calling (responde texto, não agente).
        freellmapi = {
          npm = "@ai-sdk/openai-compatible";
          name = "FreeLLMAPI";
          options = {
            baseURL = "http://127.0.0.1:3001/v1";
            apiKey = "{env:FREELLMAPI_API_KEY}";
          };
          models = {
            auto = {
              name = "FreeLLMAPI Auto (router 34 providers)";
              limit = { context = 128000; output = 8192; };
            };
            fusion = {
              name = "FreeLLMAPI Fusion (multi-model judge)";
              limit = { context = 128000; output = 8192; };
            };
            "gemini-3.5-flash-lite" = {
              name = "Gemini 3.5 Flash Lite";
              limit = { context = 128000; output = 8192; };
            };
            "gemini-2.5-flash-lite" = {
              name = "Gemini 2.5 Flash Lite";
              limit = { context = 32768; output = 8192; };
            };
            "gemini-3.1-flash-lite" = {
              name = "Gemini 3.1 Flash Lite";
              limit = { context = 128000; output = 8192; };
            };
            "qwen3.8-27b" = {
              name = "Qwen3.8 27B (groq; ITPM free 7k < prompt agente)";
              limit = { context = 131072; output = 4096; };
            };
            "gpt-oss-120b" = {
              name = "GPT-OSS 120B (groq)";
              limit = { context = 131072; output = 8192; };
            };
            "gpt-oss-20b" = {
              name = "GPT-OSS 20B (nvidia)";
              limit = { context = 32768; output = 8192; };
            };
            "nemotron-3-super-120b" = {
              name = "Nemotron 3 Super 120B (nvidia)";
              limit = { context = 131072; output = 8192; };
            };
            "nemotron-3.5-lightning" = {
              name = "Nemotron 3.5 Lightning (openrouter :free)";
              limit = { context = 128000; output = 8192; };
            };
            "llama-4-scout" = {
              name = "Llama 4 Scout (cloudflare)";
              limit = { context = 131072; output = 8192; };
            };
            "qwen2.5-coder-32b" = {
              name = "Qwen2.5 Coder 32B (cloudflare)";
              limit = { context = 32768; output = 8192; };
            };
            "qwq-32b" = {
              name = "QwQ 32B (cloudflare)";
              limit = { context = 32768; output = 8192; };
            };
            "llama-3.1-8b" = {
              name = "Llama 3.1 8B (cloudflare; tool-call via texto)";
              limit = { context = 32768; output = 4096; };
            };
            "mistral-small-3.1-24b" = {
              name = "Mistral Small 3.1 24B (cloudflare)";
              limit = { context = 32768; output = 8192; };
            };
            "llama-3.3-70b-fp8-fast" = {
              name = "Llama 3.3 70B FP8 (cloudflare ctx 24k)";
              limit = { context = 24000; output = 4096; };
            };
            "command-a" = {
              name = "Command A (cohere)";
              limit = { context = 131072; output = 8192; };
            };
            "command-r7b" = {
              name = "Command R7B (cohere)";
              limit = { context = 128000; output = 8192; };
            };
          };
        };
        # (14/10, dono: small_model NUNCA `local` — pc fraco puxaria modelo
        # inútil. Nome dedicado pro tier leve, endpoint do bonsai.)
        local_small_model = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "http://127.0.0.1:8080/v1";
          };
          models = {
            bonsai = {
              name = "Bonsai 8B Ternário (leve)";
              limit = { context = 8192; output = 2048; };
            };
          };
        };
        local = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "http://127.0.0.1:8080/v1";
          };
          models = {
            # Ids = EXATAMENTE os do server /v1/models (bonsai,
            # jarvis-fast, jarvis-strong) — opencode valida contra o
            # server; nome divergente → "model not found" (bug 16/09).
            # NOTA 03/10: jarvis-fast/strong REMOVIDOS daqui — o router 8080
            # só serve 'bonsai' (/v1/models). fast mora no upstream 8083
            # (provider local-fast); strong não tem preset em lugar nenhum —
            # a classe 35B é o local-uncensored (:8084).
            "bonsai" = {
              name = "Bonsai 8B Local (ternary)";
              # c=49152 do preset prism (jarvis-models-prism.ini).
              limit = {
                context = 49152;
                output = 8192;
              };
            };
          };
        };

        # jarvis-fast DE VERDADE: upstream stock na 8083 (preset c=16384,
        # id verificado via /v1/models). Estava no provider `local` (:8080)
        # onde o router não o serve.
        local-fast = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "http://127.0.0.1:8083/v1";
          };
          models = {
            "jarvis-fast" = {
              name = "Qwen3-4B Local (fast)";
              limit = {
                context = 16384;
                output = 4096;
              };
            };
          };
        };

        
        # ADICIONADO: Provedor oficial da Google para rodar na nuvem estável
        # Auditoria 08/10: catálogo real via API (45 modelos); free tier
        # confirma flash/flash-lite/gemma. GEMINI_API_KEY do env estava podre
        # (API_KEY_INVALID) — corrigida c/ a chave válida do auth.json.
        google = {
          npm = "@ai-sdk/google";
          models = {
            "gemini-2.5-flash" = {
              name = "Gemini 2.5 Flash Cloud";
            };
            "gemini-2.5-flash-lite" = {
              name = "Gemini 2.5 Flash Lite Cloud";
            };
            "gemini-3.5-flash" = {
              name = "Gemini 3.5 Flash Cloud";
            };
            "gemma-4-31b-it" = {
              name = "Gemma 4 31B IT (free)";
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
            # Slugs :free VERIFICADOS no catálogo real 08/10 (GET /api/v1/models,
            # 16 :free vivos). glm-5.2:free MORREU (fora do catálogo) — removido.
            # Free tier = rate limit diário por conta.
            "nvidia/nemotron-3-ultra-550b-a55b:free" = {
              name = "Nemotron 3 Ultra 550B Free";
            };
            "nvidia/nemotron-3-super-120b-a12b:free" = {
              name = "Nemotron 3 Super 120B Free";
            };
            "nvidia/nemotron-3.5-lightning:free" = {
              name = "Nemotron 3.5 Lightning Free";
            };
            "google/gemma-4-31b-it:free" = {
              name = "Gemma 4 31B Free";
            };
            "thinkingmachines/inkling:free" = {
              name = "Inkling Free (novidade 10/26)";
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
            # Auditoria 08/10 (GET /models real): qwen3.6-27b MORREU (removido);
            # catálogo free atual = qwen3.8-27b + gpt-oss-120b/20b + allam-2-7b.
            "qwen/qwen3.8-27b" = {
              name = "Groq Qwen3.8 27B";
              # Tier grátis: OTPM 1000 → limita saída p/ caber (ITPM 7000 ainda
              # é apertado p/ o system prompt do opencode; requer tier pago p/ uso real).
              limit = {
                context = 131072;
                output = 800;
              };
            };
            "openai/gpt-oss-120b" = {
              name = "Groq GPT-OSS 120B";
              limit = {
                context = 131072;
                output = 800;
              };
            };
            "openai/gpt-oss-20b" = {
              name = "Groq GPT-OSS 20B";
              limit = {
                context = 131072;
                output = 800;
              };
            };
          };
        };
        
        # NVIDIA NIM (chave NVIDIA_API_KEY validada 16/09: HTTP 200, 82
        # modelos — provider free vivo que estava fora do config)
        nvidia = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://integrate.api.nvidia.com/v1";
            apiKey = "{env:NVIDIA_API_KEY}";
          };
          models = {
            # Auditoria 08/10 (GET /models real, 80 modelos): v4-flash-0731
            # saiu do catálogo → v4.1-flash. gemma-4-31b-it adicionado.
            "deepseek-ai/deepseek-v4.1-flash" = {
              name = "DeepSeek V4.1 Flash (NIM free)";
            };
            "z-ai/glm-5.3-flash" = {
              name = "GLM 5.3 Flash (NIM free)";
            };
            "nvidia/nemotron-3-super-120b-a12b" = {
              name = "Nemotron 3 Super 120B (NIM free)";
            };
            "google/gemma-4-31b-it" = {
              name = "Gemma 4 31B IT (NIM free)";
            };
          };
        };

        # ADICIONADO: Cerebras (fast inference)
        # 16/09: chave válida mas conta sem crédito → "Payment Required".
        cerebras = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api.cerebras.ai/v1";
            apiKey = "{env:CEREBRAS_API_KEY}";
          };
          models = {
            # Auditoria 08/10 (GET /models real): catálogo = gpt-oss-120b +
            # qwen-3.8-27b. "Payment Required" de 16/09 a retestar.
            "qwen-3.8-27b" = {
              name = "Cerebras Qwen3.8 27B";
            };
            "gpt-oss-120b" = {
              name = "Cerebras GPT-OSS 120B";
            };
          };
        };

        # Together REMOVIDO 16/09: conta exige US$5 de crédito (dono
        # recusou) e a chave retorna 401. Re-add só se billing resolver.

        # Cloudflare Workers AI (free tier: 10k neurons/dia, sem cartão).
        # Chave + account id no env (08/10). Endpoint OpenAI-compat
        # /ai/v1/chat/completions validado 08/10 (HTTP 200, "OK.").
        cloudflare = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api.cloudflare.com/client/v4/accounts/{env:CLOUDFLARE_ACCOUNT_ID}/ai/v1";
            apiKey = "{env:CLOUDFLARE_API_TOKEN}";
          };
          models = {
            # IDs verificados no /models/search 08/10 (322 modelos;
            # abaixo os de geração de texto mais úteis).
            # Testes 08/10: gpt-oss-120b OK; llama-3.3-70b precisa de limit
            # (24000 max total); kimi-k2.7-code EXIGE plano pago Workers
            # (Forbidden no free) → mantido p/ referência, removido do filtro.
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast" = {
              name = "Llama 3.3 70B (Workers AI free)";
              limit = {
                context = 24000;
                output = 8000;
              };
            };
            "@cf/openai/gpt-oss-120b" = {
              name = "GPT-OSS 120B (Workers AI free)";
            };
            "@cf/google/gemma-4-26b-a4b-it" = {
              name = "Gemma 4 26B A4B (Workers AI free)";
            };
            "@cf/qwen/qwen3.8-27b" = {
              name = "Qwen3.8 27B (Workers AI free)";
            };
            "@cf/deepseek-ai/deepseek-v4-flash-0731" = {
              name = "DeepSeek V4 Flash (Workers AI free)";
            };
            "@cf/mistralai/mistral-small-3.1-24b-instruct" = {
              name = "Mistral Small 3.1 24B (Workers AI free)";
            };
          };
        };

        # SambaNova Cloud — chave válida (catálogo 6 modelos 08/10), MAS
        # inferência retorna HTTP 402 PAYMENT_METHOD_REQUIRED: o free tier
        # pós-2026 exige cartão no dashboard. AGUARDANDO_ACAO_USUARIO.
        sambanova = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api.sambanova.ai/v1";
            apiKey = "{env:SAMBANOVA_API_KEY}";
          };
          models = {
            "Meta-Llama-3.3-70B-Instruct" = {
              name = "Llama 3.3 70B (SambaNova)";
            };
            "gpt-oss-120b" = {
              name = "GPT-OSS 120B (SambaNova)";
            };
            "gemma-4-31B-it" = {
              name = "Gemma 4 31B (SambaNova)";
            };
            "DeepSeek-V3.2" = {
              name = "DeepSeek V3.2 (SambaNova)";
            };
          };
        };

        # Cohere — trial key gratuita (rate-limited, sem cartão).
        # Endpoint OpenAI-compat /compatibility/v1 validado 08/10 (HTTP 200).
        cohere = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "https://api.cohere.ai/compatibility/v1";
            apiKey = "{env:COHERE_API_KEY}";
          };
          models = {
            "command-r7b-12-2024" = {
              name = "Command R7B (Cohere trial)";
            };
            "command-r-plus-08-2024" = {
              name = "Command R+ (Cohere trial)";
            };
            "command-a-03-2025" = {
              name = "Command A (Cohere trial)";
            };
            "command-a-reasoning-08-2025" = {
              name = "Command A Reasoning (Cohere trial)";
            };
            "north-mini-code-1-0" = {
              name = "North Mini Code (Cohere trial)";
            };
          };
        };

        # ADICIONADO: HuggingFace Inference API
        huggingface = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            # api-inference = endpoint legado; o vivo é o router (chat
            # completions validado 16/09: HTTP 200 com resposta real)
            baseURL = "https://router.huggingface.co/v1";
            apiKey = "{env:HF_TOKEN}";
          };
          models = {
            "Qwen/Qwen3-235B-A22B-Instruct-2507" = {
              name = "Qwen3 235B HF";
            };
          };
        };
      } // pkgs.lib.mapAttrs'
        (name: svc: pkgs.lib.nameValuePair svc.opencode.key {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "http://127.0.0.1:${toString svc.port}/v1";
          };
          models = {
            "${svc.modelFile}" = {
              name = svc.opencode.name;
              limit = {
                context = svc.opencode.context;
                output = svc.opencode.output;
              };
            };
          };
        })
        (pkgs.lib.filterAttrs (n: s: s ? opencode) pkgs.aiModels.directServers));

      # ════════════════════════════════════════════════════════════
      # FILTRO DO CATÁLOGO (auditoria 08/10 — whitelist = só o que
      # passou no teste real "Responda somente OK" via opencode run).
      # Inventário completo continua em `provider.*.models` acima; o
      # whitelist POR PROVIDER controla o que aparece no seletor.
      # Reteste: editar a lista + ./rebuild-host.sh --quick + ativação.
      # ════════════════════════════════════════════════════════════
      # NOTA 08/10 PÓS-TESTE: `whitelist` por provider não é aplicado pelo
      # seletor da CLI 1.18.29 (modelos continuam listados). O filtro
      # real da CLI é `enabled_providers`. Como vários providers têm ALGUNS
      # modelos aprovados e outros não (ex.: Cloudflare free vs paid-only),
      # manter TODOS habilitados + documentar o estado por modelo aqui é
      # a política que preserva inventário sem esconder aprovados.
      # Estado por modelo (matriz completa em docs/improvements/):
      #   APROVADO: google/gemini-2.5-flash, google/gemini-2.5-flash-lite,
      #     google/gemini-3.5-flash, google/gemma-4-31b-it,
      #     cloudflare/@cf/openai/gpt-oss-120b, cloudflare/@cf/google/gemma-4-26b-a4b-it,
      #     cloudflare/@cf/qwen/qwen3.8-27b, cloudflare/@cf/mistralai/mistral-small-3.1-24b-instruct,
      #     cohere/command-r7b-12-2024, cohere/command-a-03-2025,
      #     cohere/command-a-reasoning-08-2025, cohere/north-mini-code-1-0,
      #     nvidia/nvidia/nemotron-3-super-120b-a12b, nvidia/google/gemma-4-31b-it,
      #     openrouter/thinkingmachines/inkling:free,
      #     local/bonsai (+ locais: consulta direta, fora do escopo cloud)
      #   RATE_LIMIT_TEMPORARIO (exceção Zen — NÃO marcar como defeituoso):
      #     opencode/* (account-wide, confirmado 08/10 via log "Rate limit
      #     exceeded" em mimo-v2.6-flash-free e big-pickle; retestar depois)
      #   AGUARDANDO_ACAO_USUARIO: sambanova/* (HTTP 402 PAYMENT_METHOD_REQUIRED:
      #     free tier pós-2026 exige cartão no dashboard cloud.sambanova.ai)
      #   MODELO_PAGO/SEM_ACESSO free: cloudflare/@cf/moonshotai/kimi-k2.7-code
      #     e @cf/deepseek-ai/deepseek-v4-flash-0731 (Forbidden: exige Workers
      #     Paid), huggingface/* (créditos esgotados), cerebras/* (Payment
      #     Required), groq/qwen3.8-27b + gpt-oss-120b via opencode (ITPM/TPM
      #     7000/8000 < prompt do agente; via curl mínimo responde OK)
      #   INDISPONIVEL_TEMPORARIO: nvidia/deepseek-ai/deepseek-v4.1-flash
      #     (streaming timeout mesmo via curl; NIM às vezes retém resposta),
      #     openrouter :free exceto inkling (free-models-per-day esgotado)
      enabled_providers = [
        "local" "local-fast" "local-uncensored" "local-uncensored-4b"
        "local-deepseek-7b" "local-phi-mini" "local-gemma-4b"
        # (15/10, freellmapi E2E provado: provider SEM o gate enabled não
        # existe pro CLI run — "Model not found" embrulhado em "Unexpected
        # server error". Project .opencode/ MERGE foi a prova.)
        "freellmapi"
        # MORTOS 14/10 (arquivos deletados no tree-shake; descomentar = re-baixar):
        # "local-xlam-8b" "local-qwen30b-moe" "local-uncensored-q4kp"
        "google" "cloudflare" "cohere" "nvidia" "openrouter"
        "groq" "huggingface" "cerebras" "sambanova"
        # Zen HABILITADO (dono confirmou 08/10: funciona; o erro de hoje era
        # cota diária esgotada por uso dele, não defeito).
        "opencode"
      ];

      # Higiene de contexto global (03/10): vale p/ todos os providers.
      # prune poda tool outputs velhos; tool_output capa outputs gigantes
      # (prompt de 33k matou o Qwen 2x); small_model tira titles/resumos do 35B.
      small_model = "local_small_model/bonsai";
      warming = true;
      compaction = {
        auto = true;
        prune = true;
      };
      tool_output = {
        max_lines = 200;
        max_bytes = 8192;
      };

      # Default E2E-validado 16/09 ("opencode run" respondeu): Gemini free
      # via GEMINI_API_KEY. openrouter/free era slug morto = causa raiz do
      # "opencode quebrado".
      model = "local/bonsai";

      # MCP Jarvis: RAG, memória, vault, files, shell, nix — via stdio.
      # Handshake validado (tools/list retorna 20 tools). Env inline no
      # bash -c porque o campo environment nem sempre é repassado.
      mcp = {
        jarvis = {
          type = "local";
          # Launcher em vez de PYTHONPATH inline (2026-10-02): o path fixo
          # apontava para um env SEM pillow/pytesseract, então o MCP rodava sem
          # PIL, o vision.py mandava PNG cru de 1,5MB, o Gemini respondia
          # "Unable to process input image" e a chamada estourava o timeout.
          # O launcher resolve as deps em runtime, então não depende de
          # re-gitar o Nix depois de cada rebuild. Ver o script p/ o porquê.
          # Env do proprio MCP, construido aqui: pillow/pytesseract/requests
          # etc. NOTA (2026-10-02): `dependencies` do buildPythonPackage do
          # jarvis-voice NAO vai para o sys.path do wrapper (medido: closure
          # sem pillow, `grep -c PYTHONPATH bin/jarvis-mcp` -> 0) e forcar por
          # makeWrapper quebra o build. Em vez de depender dos internos do
          # pacote, o MCP recebe um env proprio e explicito.
          command = [
            "bash"
            "/home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-mcp-launcher.sh"
            # env do proprio MCP (2026-10-02): `dependencies` do
            # buildPythonPackage do jarvis-voice nao vai para o sys.path do
            # wrapper (closure sem pillow; `grep -c PYTHONPATH bin/jarvis-mcp`
            # -> 0) e forcar por makeWrapper quebra o build. Entao o MCP
            # recebe um env explicito. pillow e obrigatorio: vision.py
            # redimensiona a captura antes de mandar pra API — sem ele o
            # Gemini recusa a imagem ("Unable to process input image").
            "${pkgs.python3.withPackages (ps: with ps; [
              pillow pytesseract requests httpx numpy evdev
            ])}/${pkgs.python3.sitePackages}"
          ];
          cwd = "/home/nixos/projects/nixos-ai";
          enabled = true;
          # 30s era pouco: o observe_screen medido levou 12,4s / 21,0s / 48,4s
          # (visão + OCR). Com 30s, 2 de 3 davam timeout.
          timeout = 180000;
        };
        # (26/09) Playwright MCP standalone REMOVIDO: redundante com o
        # jarvis_browser do MCP jarvis (mesma engine Playwright por baixo,
        # 1 set de tools de browser só — menos contexto duplicado p/ o
        # agente). Se um dia precisar de isolamento (sessão de browser
        # separada da do jarvis), religar aqui com type=local.
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
