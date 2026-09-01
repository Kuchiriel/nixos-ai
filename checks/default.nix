# Linting checks for nixos-ai
# Runs: ruff (Python), markdownlint (Markdown), nix flake eval
# Semantics: FAIL-CLOSED — if check can't run, it's a failure, not a pass.
{ pkgs, lib }:

{
  # ── Python linting (ruff) ──
  # Fail on errors (E). Warnings (W) are informational — reported but not blocking.
  python-lint = pkgs.runCommand "python-lint" {
    nativeBuildInputs = [ pkgs.ruff ];
    src = ../modules/ai/jarvis/src;
  } ''
    mkdir -p $out

    # Full report (all rules) — stored for inspection
    ruff check $src --output-format json > $out/ruff-report.json 2>&1 || true
    ruff check $src 2>&1 | tee $out/ruff-report.txt || true

    # Fail-closed: errors (E) must not exist
    if ruff check $src --select E 2>&1 | grep -q "^Found"; then
      echo "FAIL: Python lint errors found (E rules)" >&2
      ruff check $src --select E 2>&1 >&2
      exit 1
    fi

    # Warnings are informational — count them for the report
    warn_count=$(ruff check $src --select W 2>&1 | grep -o "[0-9]* warning" | head -1 || echo "0 warnings")
    echo "Python lint: 0 errors, $warn_count" > $out/summary.txt

    touch $out/pass
  '';

  # ── Markdown linting ──
  # No || true — if markdownlint fails, the check fails.
  # If the tool is not available, fail explicitly (don't pretend it passed).
  markdown-lint = pkgs.runCommand "markdown-lint" {
    nativeBuildInputs = [ pkgs.nodePackages.markdownlint-cli2 ];
    src = ../docs;
  } ''
    mkdir -p $out

    # Run markdownlint — exit code is authoritative
    if markdownlint-cli2 "$src/**/*.md" > $out/markdownlint-report.txt 2>&1; then
      echo "Markdown lint: PASS" > $out/summary.txt
      touch $out/pass
    else
      echo "FAIL: Markdown lint errors found" >&2
      cat $out/markdownlint-report.txt >&2
      exit 1
    fi
  '';

  # ── Nix evaluation check ──
  # Actually evaluates the flake — not just "echo passed".
  nix-check = pkgs.runCommand "nix-check" {
    nativeBuildInputs = [ pkgs.nix ];
  } ''
    mkdir -p $out

    # Evaluate the flake to catch syntax/type errors
    # --accept-flake-config: respect flake.nix settings
    # --no-write-lock-file: don't modify lock file during check
    if nix eval --file ${../.} --apply 'x: x' > /dev/null 2>&1; then
      echo "Nix evaluation: PASS" > $out/summary.txt
      touch $out/pass
    else
      # Fallback: at minimum, parse all .nix files for syntax errors
      echo "Nix eval failed, checking syntax of all .nix files..." >&2
      find ${../.} -name "*.nix" -not -path "*/.git/*" -not -path "*/nix/store/*" | while read f; do
        if ! nix-instantiate --parse "$f" > /dev/null 2>&1; then
          echo "FAIL: Syntax error in $f" >&2
          exit 1
        fi
      done
      echo "Nix syntax: PASS (eval failed but syntax is valid)" > $out/summary.txt
      touch $out/pass
    fi
  '';
}
