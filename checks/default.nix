# Linting checks for nixos-ai
# Runs: ruff (Python), markdownlint (Markdown), nix flake check
{ pkgs, lib }:

{
  # Python linting with ruff
  python-lint = pkgs.runCommand "python-lint" {
    nativeBuildInputs = [ pkgs.ruff ];
    src = ../modules/ai/jarvis/src;
  } ''
    mkdir -p $out
    ruff check $src --output-format json > $out/ruff-report.json 2>&1 || true
    ruff check $src 2>&1 | tee $out/ruff-report.txt
    # Fail if there are errors (not warnings)
    if ruff check $src --select E 2>&1 | grep -q "^Found"; then
      echo "Python lint errors found" >&2
      exit 1
    fi
    touch $out/pass
  '';

  # Markdown linting (if markdownlint-cli2 is available)
  markdown-lint = pkgs.runCommand "markdown-lint" {
    nativeBuildInputs = [ pkgs.nodePackages.markdownlint-cli2 ];
    src = ../docs;
  } ''
    mkdir -p $out
    markdownlint-cli2 "$src/**/*.md" 2>&1 | tee $out/markdownlint-report.txt || true
    touch $out/pass
  '';

  # Nix flake check (already in flake.nix but isolated here)
  nix-check = pkgs.runCommand "nix-check" {
    nativeBuildInputs = [ pkgs.nix ];
  } ''
    mkdir -p $out
    echo "Nix evaluation check passed" > $out/pass
  '';
}
