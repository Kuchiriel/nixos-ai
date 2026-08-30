{
  lib,
  python3Packages,
  makeWrapper,
  mcp-nixos,
  mcpNixos ? mcp-nixos,
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

    dependencies = with python3Packages; [
      requests
      numpy
      prompt-toolkit
    ];

    nativeBuildInputs = [makeWrapper];

    # mcp-nixos (MCP server read-only de packages/options do nixpkgs) é usado
    # pelo agente via stdio; entra como propagado para o binário jarvis saber
    # o caminho (JARVIS_MCP_NIXOS_BIN) sem hardcode de store path.
    # `mcpNixos` é o fast (cache de canais pré-computado) quando vem do overlay.
    propagatedBuildInputs = [mcpNixos];

    nativeCheckInputs = with python3Packages; [pytest hypothesis];
    checkPhase = ''
      runHook preCheck
      # Sandbox-safe subset: skip tests that write to ~/.local/state/jarvis/.
      # These fail in Nix sandbox (/homeless-shelter is read-only).
      # They pass on host: nix develop --command pytest tests/
      pytest -m "not integration" -q \
        --ignore=tests/test_agent.py \
        --ignore=tests/test_longrun_e2e.py \
        --ignore=tests/test_harness_e2e.py \
        --ignore=tests/test_nightwatch_real_e2e.py \
        --ignore=tests/test_memory.py \
        --ignore=tests/test_logging.py \
        --ignore=tests/test_bulldozer.py \
        --ignore=tests/test_mcp_tools_e2e.py \
        --ignore=tests/test_hackmd.py \
        --ignore=tests/test_nightwatch_e2e_full.py
      runHook postCheck
    '';

    # O subprocesso mcp-nixos (stdio) herda o env: aponta para o cache de
    # canais pré-computado no store (zero probes HTTP de descoberta).
    postInstall = ''
      for bin in $out/bin/*; do
        wrapProgram "$bin" \
          --prefix PATH : ${lib.makeBinPath [mcpNixos]} \
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
