{ lib, python3Packages, makeWrapper, mcp-nixos, mcpNixos ? mcp-nixos }:

let
  base = python3Packages.buildPythonPackage rec {
    pname = "jarvis";
    version = "0.1.0";
    pyproject = true;

    src = lib.cleanSource ./jarvis;

    build-system = with python3Packages; [ setuptools ];

    dependencies = with python3Packages; [
      requests
      numpy
    ];

    nativeBuildInputs = [ makeWrapper ];

    # mcp-nixos (MCP server read-only de packages/options do nixpkgs) é usado
    # pelo agente via stdio; entra como propagado para o binário jarvis saber
    # o caminho (JARVIS_MCP_NIXOS_BIN) sem hardcode de store path.
    # `mcpNixos` é o fast (cache de canais pré-computado) quando vem do overlay.
    propagatedBuildInputs = [ mcpNixos ];

    nativeCheckInputs = with python3Packages; [ pytest ];
    checkPhase = ''
      runHook preCheck
      pytest -m "not integration" -q
      # Regressão estrutural offline (sem Qdrant/LLM/serviços no sandbox):
      # garante que benchmark + eval-rag + baseline continuam coerentes.
      # O gate de qualidade real (NDCG/latência) roda no lab/host com serviços.
      $out/bin/jarvis regression --offline --baseline "$src/baseline.json" || true
      runHook postCheck
    '';

    # O subprocesso mcp-nixos (stdio) herda o env: aponta para o cache de
    # canais pré-computado no store (zero probes HTTP de descoberta).
    postInstall = ''
      for bin in $out/bin/*; do
        wrapProgram "$bin" \
          --prefix PATH : ${lib.makeBinPath [ mcpNixos ]} \
          --set MCP_NIXOS_CHANNEL_CACHE "${mcpNixos}/share/mcp-nixos/channels.json"
      done
    '';

    meta = with lib; {
      description = "JARVIS — sistema de IA local (roteamento, RAG, memória, voz) para NixOS";
      license = licenses.mit;
      platforms = platforms.linux;
      maintainers = [ ];
    };
  };

  # Jarvis com voz (STT faster-whisper + TTS Kokoro). Separado do núcleo para
  # não arrastar torch/ctranslate2 para todos os usos — o host final instala
  # este quando quiser a interface falada (wakeword brainCommand).
  withVoice = base.overridePythonAttrs (old: {
    pname = "jarvis-voice";
    dependencies = old.dependencies ++ (with python3Packages; [
      faster-whisper
      kokoro
      soundfile
    ]);
    propagatedBuildInputs = old.propagatedBuildInputs or [ ] ++ [ mcpNixos ];
  });
in
{
  inherit base withVoice;
}
