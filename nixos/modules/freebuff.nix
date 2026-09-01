{
  config,
  lib,
  pkgs,
  ...
}: let
  # Freebuff CLI — agente de coding gratuito (freebuff.com). O pacote npm é um
  # LAUNCHER leve (~18KB, única dep: tar): na primeira execução ele baixa o
  # agente real (repo privado CodebuffAI/freebuff-private) para ~/.config.
  # Empacotamos o launcher declarativamente (registry npm, sem GitHub) e a
  # primeira execução faz o bootstrap — como fazemos com os modelos GGUF.
  freebuff = pkgs.buildNpmPackage {
    pname = "freebuff";
    version = "0.0.149";

    src = pkgs.fetchurl {
      url = "https://registry.npmjs.org/freebuff/-/freebuff-0.0.149.tgz";
      sha256 = "sha256-bCgYcyJWGhRijEF9Bn8RGXFHOj0h4KWDFAAOpEPVGrI=";
    };

    # Lock gerado com: npm install --package-lock-only (repo, versionado).
    # Remove os scripts prepack/postpack: referenciam cli/release-core do repo
    # de desenvolvimento (não existem no tarball) e quebrariam o npm pack.
    postPatch = ''
      cp ${./freebuff-package-lock.json} package-lock.json
      sed -i '/"prepack"/d; /"postpack"/d' package.json
    '';

    npmDepsHash = "sha256-wdmzWuNFTG7l3qG8J/jdXWagimGLInCQ6GZahX8mfWs=";

    # o launcher não tem script build — só instala as deps e expõe o bin;
    # --ignore-scripts: o prepack/postpack do package.json referenciam o repo
    # de desenvolvimento (cli/release-core) e quebrariam o build Nix
    dontBuild = true;
    npmInstallFlags = ["--ignore-scripts"];
    dontStrip = true;

    meta = {
      description = "Freebuff — the free coding agent (CLI launcher)";
      homepage = "https://freebuff.com";
      license = lib.licenses.mit;
      mainProgram = "freebuff";
    };
  };
in {
  options.programs.freebuff = {
    enable = lib.mkEnableOption "Freebuff CLI (agente de coding gratuito)";
  };

  config = lib.mkIf config.programs.freebuff.enable {
    environment.systemPackages = [freebuff];

    # ── Reproducibility boundary ──
    # This Nix module installs the LAUNCHER only (~18KB npm package).
    # The real agent (CodebuffAI/freebuff-private) is downloaded by the
    # launcher to ~/.config/freebuff on first run. This bootstrap is
    # MUTABLE and NOT reproducible by Nix.
    #
    # What IS reproducible (Nix Store):
    #   - freebuff launcher binary + npm dependencies
    #   - Version pinned: 0.0.149 (sha256 verified)
    #
    # What is NOT reproducible (mutable):
    #   - ~/.config/freebuff/ (downloaded agent, config, state)
    #   - Agent version (auto-updates on each run)
    #
    # This is analogous to how GGUF models are fetched at runtime.
    # If full reproducibility is needed, the agent binary would need
    # to be packaged separately with a fixed hash.
  };
}
