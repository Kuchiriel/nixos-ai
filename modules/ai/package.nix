{
  lib,
  python3Packages,
  makeWrapper,
  mcp-nixos,
  mcpNixos ? mcp-nixos,
  ripgrep,
  age,
}: let
  base = python3Packages.buildPythonPackage rec {
    pname = "jarvis";
    version = "0.1.0";
    pyproject = true;

    # cleanSourceWith exclui artefatos de build que mudam a cada execução
    # (pytest cache, hypothesis, pycache, egg-info) para evitar rebuilds
    # desnecessários. Sem isso, o hash muda e jarvis-voice rebuilda sempre.
    src = lib.cleanSourceWith {
      filter = path: type:
        let
          base = builtins.baseNameOf (toString path);
          isJunk = builtins.match "(__pycache__|\.pytest_cache|\.hypothesis|.*\.egg-info|build|dist)" base != null;
        in
        !isJunk;
      src = ./jarvis;
    };

    build-system = with python3Packages; [setuptools];

    # FONTE ÚNICA da lista de deps (30/09). Antes esta lista vivia só em
    # `dependencies`, e o ambiente de TESTE do nightwatch precisava dela
    # para não falhar com "No module named 'requests'" — sem acesso, a
    # lista seria duplicada (e driftaria). `dependencies` deriva daqui.
    pythonDeps = with python3Packages; [
      requests
      httpx
      numpy
      prompt-toolkit
      fastapi
      uvicorn
      pathspec # .ragignore: matching gitignore-canônico no index RAG
      cryptography # vault cifrado opt-in (Fernet) p/ perfis isolados
      evdev # computer-use: mouse/teclado via uinput (humanize.py)
      pillow # vision.py redimensiona antes de mandar pro llama vision; sem isso cai no fallback PNG cru e o modelo devolve 500
      pytesseract # fallback do vision.py: OCR quando o vision model falha
      playwright # browser tool via CDP (connect_over_cdp; sem ms-playwright)
    ];

    dependencies = pythonDeps;

    nativeBuildInputs = [makeWrapper];

    # PIL/PYTHONPATH (2026-10-02): `dependencies` do buildPythonPackage NÃO
    # coloca as libs no sys.path deste wrapper — sem isto `import PIL` falha em
    # runtime mesmo com pillow no closure do pacote (diagnosticado: pillow
    # 12.3.0 presente em `nix-store -q --references`, porém "No module named
    # PIL"). Efeito prático: vision.py caía no PNG cru de 1,5MB e o Gemini
    # respondia "Unable to process input image". Agora as deps entram no path.
    pythonDepsPath = lib.makeSearchPathOutput "out" "python3/site-packages" pythonDeps;

    # makeWrapperArgs sozinho NÃO funcionou: o hook de python do nixpkgs monta
    # o wrapper por cima e o PYTHONPATH some (medido: pillow 12.3.0 no closure
    # via `nix-store -q --references`, mas `import PIL` → ModuleNotFoundError


    # mcp-nixos (MCP server read-only de packages/options do nixpkgs) é usado
    # pelo agente via stdio; entra como propagado para o binário jarvis saber
    # o caminho (JARVIS_MCP_NIXOS_BIN) sem hardcode de store path.
    # `mcpNixos` é o fast (cache de canais pré-computado) quando vem do overlay.
    propagatedBuildInputs = [mcpNixos age];

    nativeCheckInputs = with python3Packages; [pytest hypothesis] ++ [ripgrep];
    checkPhase = ''
      runHook preCheck
      # P8: Sandbox-safe subset via markers, not file-name ignores.
      # Tests marked @pytest.mark.integration need external services
      # (LLM server, Qdrant, network, git, audio) and fail in the
      # Nix sandbox (/homeless-shelter is read-only).
      # Run on host: nix develop --command pytest tests/
      pytest -m "not integration" -q
      runHook postCheck
    '';

    # O subprocesso mcp-nixos (stdio) herda o env: aponta para o cache de
    # canais pré-computado no store (zero probes HTTP de descoberta).
    #
    # PYTHONPATH (2026-10-02): `dependencies` do buildPythonPackage NÃO põe as
    # libs no sys.path do wrapper. Medido: pillow 12.3.0 E pytesseract estão no
    # closure (`nix-store -q --references`) mas `import PIL` dá
    # ModuleNotFoundError em runtime. Efeito: vision.py caía no PNG cru de
    # 1,5MB, o Gemini respondia "Unable to process input image", e o
    # `observe_screen` do MCP estourava o timeout de 30s.
    #
    # NOTA: eu tinha tentado num hook `postFixup` — que NÃO EXISTE no stdenv,
    # então foi ignorado em silêncio e o wrapper saía sem o prefixo (por isso
    # "PIL ausente" mesmo com pillow instalado). Aqui, no mesmo `wrapProgram`
    # que já reescreve TODOS os binários, o prefixo vem junto.
    postInstall = ''
      for bin in $out/bin/*; do
        wrapProgram "$bin" \
          --prefix PATH : ${lib.makeBinPath [mcpNixos]} \
          --prefix PYTHONPATH :${pythonDepsPath} \
          --set MCP_NIXOS_CHANNEL_CACHE "${mcpNixos}/share/mcp-nixos/channels.json"
      done
    '';

    meta = with lib; {
      description = "JARVIS — sistema de IA local (roteamento, RAG, memória, voz) para NixOS";
      license = licenses.mit;
      platforms = platforms.linux;
      maintainers = [];
    };
  };

  # Jarvis com voz (STT faster-whisper + TTS Kokoro). Separado do núcleo para
  # não arrastar torch/ctranslate2 para todos os usos — o host final instala
  # este quando quiser a interface falada (wakeword brainCommand).
  withVoice = base.overridePythonAttrs (old: {
    pname = "jarvis-voice";
    dependencies =
      old.dependencies
      ++ (with python3Packages; [
        faster-whisper
        kokoro
        soundfile
      ]);
    propagatedBuildInputs = old.propagatedBuildInputs or [] ++ [mcpNixos];
  });
in {
  inherit base withVoice;
}
