{
  homeStateVersion,
  user,
  pkgs,
  inputs,
  projectLib,
  ...
}: let
  # ══════════════════════════════════════════════════════════════
  # FONTE ÚNICA: modules/ai/free-providers.json
  # Consumido por: model_policy.py (CASCADE_MAP) + ESTE arquivo.
  # NÃO editar providers cloud hardcoded abaixo — editar o JSON.
  # Testado ao vivo 28/10/2026 (ver JSON p/ detalhes por modelo).
  # ══════════════════════════════════════════════════════════════
  freeProviders = builtins.fromJSON (builtins.readFile ../modules/ai/free-providers.json);

  # Gera config opencode provider a partir do JSON.
  # Retorna: { <name> = { npm, options, models }; ... }
  mkCloudProvider = name: prov: let
    # builtins.getEnv retorna "" em flake pura — usar sintaxe {env:VAR} do
    # opencode que expande em runtime. Converte {VAR} → {env:VAR}.
    # Ex.: {CLOUDFLARE_ACCOUNT_ID} → {env:CLOUDFLARE_ACCOUNT_ID}.
    # GATE local (03/11): provider com "gate" no catálogo passa a apontar
    # para o nv-gate (token bucket + retry de 429) em vez do endpoint cru.
    # O gate é transparente: repassa o Authorization do cliente, não guarda
    # chave nenhuma. Ver scripts/nv-gate.py.
    gate = prov.gate or null;
    baseURL =
      if gate != null && (gate.enabled or false)
      then "http://127.0.0.1:${toString gate.port}/v1"
      else builtins.replaceStrings
        ["{CLOUDFLARE_ACCOUNT_ID}"]
        ["{env:CLOUDFLARE_ACCOUNT_ID}"]
        prov.base_url;
    apiKeyEnv = if prov.env_key != null then "{env:${prov.env_key}}" else null;
    headers = if prov.requires_headers or false then prov.headers else {};
    # Headroom de contexto (02/11): ver lib/opencode-limits.nix. SEM
    # limit.input o opencode usa usable = context - maxOutputTokens = o
    # TETO EXATO da API (prompt + max_tokens ≤ context) → folga zero →
    # 400 "Bad Request" (medido no NIM: 262146 tokens > 262144).
    # Com limit.input o limiar de compactação fica `headroom` tokens
    # ABAIXO do teto (cobre o crescimento de 1 turno).
    headroom = prov.headroom or projectLib.opencode-limits.defaultHeadroom;
    mkModel = m: let
      lim = projectLib.opencode-limits.limits {
        inherit (m) context output;
        inherit headroom;
      };
      # (05/11) VARIANTES DE REASONING por modelo. Cada variante carrega o
      # body EXATO que a spec da NIM aceita (medido 04/11 em
      # mt5/opencode/NVIDIA_NIM_GROUND_TRUTH.md §3): reasoning_effort
      # (topo), reasoning_budget (topo) ou chat_template_kwargs (objeto).
      # Os dois campos NUNCA no mesmo body (a spec do nemotron diz que o
      # reasoning_budget tem precedencia sobre o effort).
      #
      # SHAPE (medido na 1.18.34 com eco-server local, 05/11):
      #   variants = { <id>: { <campo>: <valor> } }   (DICT, nao lista)
      #   - reasoningEffort (camelCase) -> o AI SDK converte pra
      #     reasoning_effort no body e SOBREPOE o default do modelo
      #     (options.reasoningEffort) -> e o que faz a variante valer.
      #   - reasoning_budget / chat_template_kwargs (snake_case) -> passam
      #     CRUOS no body (o NIM e' quem entende esses nomes).
      #   - `modelParams` NAO existe na 1.18.34 (vira a chave literal
      #     modelParams no body) e `reasoning_effort` snake_case no variant
      #     PERDE para o default do modelo -> por isso a conversao abaixo.
      camelize = name: if name == "reasoning_effort" then "reasoningEffort" else name;
      variantBody = body: pkgs.lib.mapAttrs'
        (name: value: pkgs.lib.nameValuePair (camelize name) value)
        body;
      variants = builtins.listToAttrs
        (map (v: { name = v.id; value = variantBody v.body; }) (m.variants or []));
    in ({
      name = m.name or m.id;
      limit = {
        context = m.context;
        output = m.output;
      } // (if lim.input != null then {input = lim.input;} else {});
      # (05/11) `reasoning` (schema 1.18.34: booleano no nivel do modelo,
      # nao capabilities.reasoning.supported) -> sem isso o opencode trata
      # o modelo como nao-reasoning e as variantes nao aparecem no seletor.
      reasoning = builtins.elem "reasoning" (m.capabilities or []);
    }
    // (if variants != {} then { inherit variants; } else {})
    // (if (m.reasoning_effort_default or null) != null then { options.reasoningEffort = m.reasoning_effort_default; } else {})
    // (if (prov.interleaved_field or null) != null then { interleaved = { field = prov.interleaved_field; }; } else {}));
    # (05/11) VISIBILIDADE: so active/rate_limited entram no seletor. Os
    # demais (unstable/untested/disabled) ficam DECLARADOS no JSON (fonte
    # unica, com a janela medida e as variantes) mas NAO no config: na
    # 1.18.34 nao existe `disabled` no nivel do modelo (o equivalente e
    # status=deprecated, que o runtime apaga do catalogo).
    activeModels = builtins.listToAttrs
      (map
        (m: {
          name = m.id;
          value = mkModel m;
        })
        (builtins.filter (m: m.status == "active" || m.status == "rate_limited") prov.models));
  in {
    npm = "@ai-sdk/openai-compatible";
    options =
      {
        baseURL = baseURL;
      }
      // (if apiKeyEnv != null then {apiKey = apiKeyEnv;} else {})
      // (if headers != {} then {headers = headers;} else {})
      # (03/11) TIMEOUT do provider declarativo: o default do opencode é
      # 300000ms (5 min) p/ headers/chunks. Num prompt de ~145k tokens o
      # NIM free passa de 5 min no prefill → ProviderHeaderTimeoutError
      # (3 retries x 5 min e o turno morre). Valores vêm do
      # free-providers.json (fonte única), por provider.
      // (if (prov.header_timeout or null) != null
          then {headerTimeout = prov.header_timeout;} else {})
      // (if (prov.chunk_timeout or null) != null
          then {chunkTimeout = prov.chunk_timeout;} else {})
      # (04/11) TIMEOUT TOTAL da requisição (o 'timeout' do schema V1 do
      # opencode = teto do request inteiro, nao só dos headers/chunks).
      # Sem ele, o opencode aborta no headerTimeout enquanto o nv-gate
      # ainda está tentando (orçamento interno) — o turno morre sem
      # resposta útil.
      # Ordem: timeout >= headerTimeout >= orçamento do gate.
      # (schema v1.18.34: options.timeout — "Timeout in milliseconds for
      # full requests to this provider").
      // (if (prov.timeout or null) != null
          then {timeout = prov.timeout;} else {});
    models = activeModels;
  };

  cloudProviders = builtins.mapAttrs mkCloudProvider freeProviders.providers;

  # ══════════════════════════════════════════════════════════════
  # REASONING EFFORT (variant) DECLARATIVO POR MODELO — 03/11
  # POR QUÊ: o TUI do opencode guarda a variante escolhida em
  # ~/.local/state/opencode/model.json (fora do git, fora do Nix).
  # Quando o opencode-serve reinicia (o rebuild reinicia o unit),
  # o server re-resolve a variante como "default" e o cliente grava
  # isso de volta no state -> o dono perde o "max" e tem que ir
  # escolher de novo (reclamação do dono, 03/11).
  # FIX: o effort vira FALLBACK no config do modelo. A variante
  # explícita do TUI continua com precedência (docs v2: provider ->
  # model -> variant), então o dono ainda troca na hora se quiser.
  # Fonte das escolhas: ~/.local/state/opencode/model.json (03/11).
  # ATENÇÃO: declarar um modelo no config SUBSTITUI a entrada do
  # catálogo (models.dev) — por isso os modelos que só existem lá
  # carregam o limit próprio (via mkEffortModel, mesma conta de
  # headroom do mkModel). Os do catálogo curado (free-providers.json)
  # mantêm o limit de lá (o recursiveUpdate só acrescenta o options).
  # ══════════════════════════════════════════════════════════════
  mkEffortModel =
    context: output: effort:
    let
      lim = projectLib.opencode-limits.limits {
        inherit context output;
        headroom = projectLib.opencode-limits.defaultHeadroom;
      };
    in {
      limit = {
        inherit context output;
      } // (if lim.input != null then {input = lim.input;} else {});
      options.reasoningEffort = effort;
    };

  reasoningEffortDefaults = {
    # (05/11) NVIDIA saiu deste bloco: effort, janela e VARIANTES por
    # modelo passaram a viver no free-providers.json (fonte unica) — o JSON
    # traz `reasoning_effort_default` (default do request) e as variantes
    # com o body exato de cada modelo (reasoning_effort x reasoning_budget
    # x chat_template_kwargs; ver §3 do ground truth medido em 04/11).
    # Aqui so ficam os providers que NAO tem essa fonte (openrouter,
    # ovhcloud). O "z-ai/glm-5.3" foi REMOVIDO: o catalogo NIM medido em
    # 05/11 tem 84 modelos e nao tem o glm-5.3 (so o glm-5.3-flash) —
    # declarado aqui ele dava 404 na hora de usar.
    openrouter.models = {
      "meta/muse-spark-1.3" = mkEffortModel 1048576 943718 "max";
      "meta/muse-spark-open" = mkEffortModel 1048576 943718 "xhigh";
      "inclusionai/ling-3.1-flash" = mkEffortModel 1000000 262144 "medium";
      "nvidia/nemotron-3-ultra-550b-a55b" = mkEffortModel 262144 182520 "high";
      "nvidia/nemotron-3-ultra-550b-a55b:free" = mkEffortModel 1000000 65536 "high";
      "~deepseek/deepseek-flash-latest" = mkEffortModel 1048576 943718 "max";
    };
    ovhcloud.models."qwen3.5-397b-a17b" = mkEffortModel 262144 262144 "high";
  };
in {
  imports = [
    ./modules
    ./home-packages.nix
    ./modules/rclone-sync.nix
    ./modules/xref-watch.nix
    ./modules/sandbox-verificacao.nix
    ./modules/agents-watcher.nix
    # keepawake da tela: sempre ligado (o watcher é AFK-only)
    ./modules/agents-keepawake.nix
    # jobs noturnos (bench 04:00 / probe do default 05:00) — declarativos
    ./modules/bench-nightly.nix
    # layout das janelas opencode sobrevive ao reboot (captura 60s + restore)
    ./modules/session-snapshot.nix
    # gate de taxa do free tier NVIDIA (fila + retry de 429)
    ./modules/services/nv-gate.nix
    # higiene dos artefatos do harness mt5 (logs de 263 MB/run -> truncados + rotacionados)
    ./modules/services/rotate-mt5-logs.nix
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
    # Fonte única de verdade: /etc/litellm.env
    # Normaliza aliases entre chaves.

    set -a
    source "/etc/litellm.env" 2>/dev/null || true
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
  # 02/11: injeta também a REGRA DO RESGATE no system prompt
  # (experimental.chat.system.transform) — o resgate não pode depender de
  # o agente lembrar (2602.11988: disciplina sozinha não é sistema).
  home.file.".config/opencode/plugins/memory.js".source = ./files/opencode/plugins/memory.js;

  # Red-team plugin — modo de auditoria + tools nativas `redteam_matrix`,
  # `redteam_payload` e `redteam_probe` (06/11). O opencode.json e
  # read-only (symlink do store), entao as tools NAO podem ser registradas
  # la: elas vao no proprio plugin (o registry aceita JSON Schema puro, sem
  # zod — o plugin vive no store, sem node_modules).
  # O modo e OPT-IN e se liga pelo slash command `/jailbreak on` (o plugin
  # resolve o comando via command.execute.before; o modelo nunca ve o
  # template). A transliteracao trigger<->decoy (o modelo ve uma palavra, o
  # disco tem outra) fica entre tool.execute.before/after.
  home.file.".config/opencode/plugins/redteam.js".source =
    ./files/opencode/plugins/redteam.js;

  # Slash command /jailbreak — liga/desliga o modo red-team sem rebuild.
  # Resolvido pelo plugin (hook command.execute.before): o modelo nunca ve
  # o template, so a resposta do toggle.
  home.file.".config/opencode/command/jailbreak.md".source =
    ./files/opencode/command/jailbreak.md;

  # Skill de coordenação multi-agente — DECLARATIVA (02/11): antes vivia
  # solta em ~/.config/opencode/skills/ (fora do git, sem backup). O
  # opencode carrega o corpo sob demanda (só name+description no prompt:
  # progressive disclosure, 2609.35692) — o corpo é memória procedural.
  home.file.".config/opencode/skills/opencode-coordination/SKILL.md".source =
    ./files/opencode/skills/opencode-coordination/SKILL.md;

  # opencode.json do PROJETO (~/projects) — DECLARATIVO (15/10).
  # POR QUÊ: o arquivo vivia solto na raiz do repo e um agente o encheu de
  # freellmapi + enabled_providers ['local','freellmapi'] — e a lista de
  # projeto SOBRESCREVE a global, derrubando nvidia/google/etc ("modelos
  # sumiram", "Unexpected server error" no CLI). Fonte única de providers =
  # ~/.config/opencode/opencode.json (gerado daqui do home.nix); no projeto
  # vai só a higiene de contexto. Symlink read-only da store: edição manual
  # na mão fica IMPOSSÍVEL — se um agente recriar o arquivo, a ativação
  # seguinte o substitui de volta.
  home.file."projects/opencode.json".text = builtins.toJSON {
    "$schema" = "https://opencode.ai/config.json";
    compaction = { auto = true; prune = true; };
    tool_output = { max_lines = 200; max_bytes = 8192; };
  };

  # ── VS Code + Roo Code — configurado via módulo vscode-roo.nix ──
  # (extensões, userSettings, MCP, custom modes são declarativos)
  vscode-roo = {
    enable = true;
  };

  # Aliases rápidos para as ferramentas de IA em nuvem
  home.shellAliases = {
    kilo = "opencode";
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
      provider = pkgs.lib.recursiveUpdate ({
        # (14/10, dono: small_model NUNCA `local` — pc fraco puxaria modelo
        # inútil. Nome dedicado pro tier leve, endpoint do bonsai.)
        local_small_model = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            # (03/11) porta + contexto de models.nix (fonte única): o
            # catálogo dizia 8192 aqui e 49152 no provider `local` para o
            # MESMO server (o preset prism serve c=49152). Drift real.
            baseURL = "http://127.0.0.1:${toString pkgs.aiModels.routing.models.bonsai.endpoint}/v1";
          };
          models = {
            bonsai = {
              name = "Bonsai 8B Ternário (leve)";
              limit = {
                context = pkgs.aiModels.routing.models.bonsai.ctx;
                output = 2048;
              };
            };
          };
        };
        local = {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "http://127.0.0.1:${toString pkgs.aiModels.routing.models.bonsai.endpoint}/v1";
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
                context = pkgs.aiModels.routing.models.bonsai.ctx;
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
            baseURL = "http://127.0.0.1:${toString pkgs.aiModels.routing.models.jarvis-fast.endpoint}/v1";
          };
          models = {
            "jarvis-fast" = {
              name = "Qwen3-4B Local (fast)";
              limit = {
                context = pkgs.aiModels.routing.models.jarvis-fast.ctx;
                output = 4096;
              };
            };
          };
        };

        # ══════════════════════════════════════════════════════════
        # CLOUD PROVIDERS: fonte única = modules/ai/free-providers.json
        # Gerados via mkCloudProvider acima. NÃO editar aqui — editar
        # o JSON e re-testar. Testado ao vivo 28/10/2026.
        # ══════════════════════════════════════════════════════════
      } // cloudProviders // pkgs.lib.mapAttrs'
        (name: svc: pkgs.lib.nameValuePair svc.opencode.key {
          npm = "@ai-sdk/openai-compatible";
          options = {
            baseURL = "http://127.0.0.1:${toString svc.port}/v1";
          };
          models = {
            # (26/10) id = alias do server quando existe (medido: com
            # --alias o /v1/models anuncia o alias; sem ele = path do
            # gguf). opencode VALIDA o id contra o server (bug 16/09:
            # "model not found" quando divergem) → tem que ser o mesmo.
            "${svc.alias or svc.modelFile}" = {
              name = svc.opencode.name;
              limit = {
                context = svc.opencode.context;
                output = svc.opencode.output;
              };
            };
          };
        })
        (pkgs.lib.filterAttrs (n: s: s ? opencode) pkgs.aiModels.directServers))
      # Effort (reasoning) declarativo por modelo — 03/11: o recursiveUpdate
      # preserva nome/limit do catálogo e só acrescenta o options.reasoningEffort.
      reasoningEffortDefaults;

      # Reasoning effort (variant) do agente build — 03/11 (dono): o TUI
      # guardava a variante em ~/.local/state/opencode/model.json; quando o
      # opencode-serve reiniciava (o rebuild reinicia o unit), o server
      # re-resolvia a variante como "default" e o cliente gravava isso de
      # volta -> o dono perdia o "max" a cada rebuild. O effort do MODELO
      # (reasoningEffortDefaults, acima) é o fallback do request; aqui a
      # VARIANTE default do agente, para o server resolver "max" e o TUI
      # mostrar o que o dono escolheu. A variante explícita da sessão
      # continua sobrescrevendo (o dono pode trocar na hora).
      # model+variant CASADOS: a variante do agente só vale para o modelo
      # configurado dele (schema v2) — por isso o build passou a declarar o
      # nvidia/minimax (o modelo que o dono usa de verdade nas sessões).
      # Decisão do dono 03/11. O 4B local segue como root model, small_model
      # e selecionável na mão; se o nvidia cair/rate-limitar, o build não
      # cai sozinho (escolher o 4B no TUI).
      agent.build = {
        model = "nvidia/minimaxai/minimax-m3.1-flash";
        variant = "max";
      };

      # ════════════════════════════════════════════════════════════
      # FILTRO DO CATÁLOGO — fonte única: modules/ai/free-providers.json
      # Testado ao vivo 28/10/2026 (todos os providers abaixo).
      # O JSON tem o estado por modelo (active/rate_limited/agentic_only).
      # ════════════════════════════════════════════════════════════
      # RESULTADO DOS TESTES 28/10 (via curl direto):
      #   ✅ GROQ: gpt-oss-120b, qwen3.8-27b, gpt-oss-20b (todos OK)
      #   ✅ NVIDIA NIM: nemotron-3-ultra-550b, nemotron-3.5-lightning (OK)
      #   ✅ CLOUDFLARE: gpt-oss-120b, llama-3.3-70b, gemma-4-26b,
      #      qwen3.8-27b, mistral-small-3.1 (todos OK com Bearer)
      #   ✅ GEMINI: 2.5-flash, 2.5-flash-lite, 3-flash-preview (OK)
      #   ✅ OPENROUTER: 8/16 :free OK (com headers HTTP-Referer+X-Title);
      #      5 rate_limited (volta sozinho); 2 agentic_only (inkling)
      #   ✅ OVHCLOUD: gpt-oss-120b/20b, llama-3.3-70b, qwen3.5-397B (anon)
      #   ✅ KILOCODE: kilo-auto/free, nemotron-ultra/lightning (anon)
      #   ✅ LLM7: gpt-oss:20b, nemotron-3-nano:30b (anon)
      #   ⚠️ COHERE: trial 1k calls/mês, NON-COMMERCIAL (curl timeout 28/10)
      #   ❌ DESATIVADOS: cerebras (payment), together (bad key),
      #      huggingface (no credits), sambanova (high demand)
      # Locais: bonsai, jarvis-fast, uncensored-4b, uncensored-35b, etc.
      enabled_providers = [
        "local" "local-fast" "local-uncensored" "local-uncensored-4b"
        "local-deepseek-7b" "local-phi-mini" "local-gemma-4b"
        # Cloud (gerados do free-providers.json):
        "groq" "nvidia" "cloudflare" "gemini" "openrouter"
        "ovhcloud" "kilocode" "llm7" "cohere"
        "opencode"
      ];

      # Higiene de contexto global (03/10): vale p/ todos os providers.
      # prune poda tool outputs velhos; tool_output capa outputs gigantes
      # (prompt de 33k matou o Qwen 2x); small_model tira titles/resumos do 35B.
      # (03/11) small_model = o DEFAULT residente (:8092). Antes era
      # local_small_model/bonsai (:8080) — com o 4B-MTP de pé (4474MiB) o
      # bonsai (4.3GB) não carrega no router → small_model quebraria.
      # (03/11) provider+id DERIVADOS de models.nix (fonte única):
      # directServers.uncensored-4b.opencode.key + .alias (= routing.default).
      small_model = "${pkgs.aiModels.directServers."uncensored-4b".opencode.key}/${pkgs.aiModels.directServers."uncensored-4b".alias}";
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
      # (02/11) Default = 4B-MTP+LoRA (:8092, alias jarvis-mtp-lora) —
      # dono: "tira o bonsai de default". O bonsai (:8080) fica no catálogo
      # p/ uso manual (precisa do :8092 parado: 4.1G+4.3G > 6.1G VRAM).
      # (03/11) derivado de models.nix (fonte única).
      model = "${pkgs.aiModels.directServers."uncensored-4b".opencode.key}/${pkgs.aiModels.directServers."uncensored-4b".alias}";

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

  # (05/11) MCP de coordenação entre IAs: as ferramentas de roster/msg
  # servidas por HTTP (streamable-http) no IP do tailnet, para os agentes
  # de outra máquina (Windows) falarem com o roster daqui direto — sem
  # depender do issue do GitHub. Ver modules/services/coord-mcp.nix.
  services.jarvis.coordMcp = {
    enable = true;
    host = "100.121.100.103";
    port = 8765;
  };

  services.jarvis-wakeword = {
    # (21/10, dono) DESABILITADO — o duplex de voz contínua substituiu o
    # wakeword: address gate no classify cumpre a mesma função sem o
    # daemon openwakeword competindo pelo microfone.
    enable = false;
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
