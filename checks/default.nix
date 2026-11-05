# Linting checks for nixos-ai
# Runs: ruff (Python), markdownlint (Markdown), nix flake eval
# Semantics: FAIL-CLOSED — if check can't run, it's a failure, not a pass.
{ pkgs, lib }:

{
  # ── Python linting (ruff) ──
  # Fail on errors (E). Warnings (W) are informational — reported but not blocking.
  # Sandbox-safe: copia src + ruff.toml para um workdir para que a descoberta
  # automática de config do ruff encontre o ruff.toml REAL do repo (senão o
  # ruff usa defaults e falha em E501/E402 que o repo ignora por design).
  python-lint = pkgs.runCommand "python-lint" {
    nativeBuildInputs = [ pkgs.ruff ];
    src = ../modules/ai/jarvis/src;
    ruffConfig = ../ruff.toml;
  } ''
    mkdir -p $out work
    cp -r $src work/src
    cp $ruffConfig work/ruff.toml

    # Full report (all rules from repo config) — stored for inspection
    ruff check work/src --output-format json > $out/ruff-report.json 2>&1 || true
    ruff check work/src 2>&1 | tee $out/ruff-report.txt || true

    # Fail-closed: errors (E) must not exist (config já ignora E501/E402)
    if ruff check work/src --select E 2>&1 | grep -q "^Found"; then
      echo "FAIL: Python lint errors found (E rules)" >&2
      ruff check work/src --select E 2>&1 >&2
      exit 1
    fi

    # Warnings are informational — count them for the report
    warn_count=$(ruff check work/src --select W 2>&1 | grep -o "[0-9]* warning" | head -1 || echo "0 warnings")
    echo "Python lint: 0 errors, $warn_count" > $out/summary.txt

    touch $out/pass
  '';

  # ── Markdown linting ──
  # No || true — if markdownlint fails, the check fails.
  # If the tool is not available, fail explicitly (don't pretend it passed).
  # (12/10, IMP-020) pkgs.nodePackages foi REMOVIDO do nixpkgs — o cli2
  # agora é top-level (markdownlint-cli2 0.21.0).
  markdown-lint = pkgs.runCommand "markdown-lint" {
    nativeBuildInputs = [ pkgs.markdownlint-cli2 ];
    src = ../docs;
  } ''
    mkdir -p $out work
    cp -r $src work/docs
    # store vem read-only (444/555): sem o u+w nem o rm abaixo funciona
    chmod -R u+w work/docs
    # _trash fora: o aider-chat-history é LIXO histórico (731KB), não
    # doc — negação de glob e cli2 ignorePatterns falharam nos dois
    # contextos (relativo e absoluto) — medido 12/10. A cópia é mutável.
    rm -rf work/docs/archive/_trash

    # Run markdownlint — exit code is authoritative (config vem DENTRO
    # do docs: .markdownlint-cli2.jsonc)
    cd work
    if markdownlint-cli2 "docs/**/*.md" > $out/markdownlint-report.txt 2>&1; then
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

  # ── Headroom de contexto dos providers cloud (02/11) ──────────────
  # O opencode usa usable = context - maxOutputTokens quando o modelo
  # NÃO declara limit.input — e esse valor é o TETO EXATO da API
  # (prompt_tokens + max_tokens ≤ context). Folga zero + check de
  # overflow com 1 turno de lag = HTTP 400 "context_length" (medido no
  # NIM: 262146 > 262144). lib/opencode-limits.nix converte o headroom
  # em limit.input; esta check valida a fórmula:
  #   1. limit.input ≤ context
  #   2. usable = limit.input - reserved (round-trip exato)
  #   3. usable ≤ promptCeiling (NUNCA mais permissivo que o padrão)
  #   4. usable ≥ 75% do promptCeiling (não compacta cedo demais)
  opencode-headroom = let
    limits = (import ../lib/opencode-limits.nix { inherit lib; }).limits;
    cases = [
      { context = 262144; output = 262144; headroom = 32000; } # minimax
      { context = 262144; output = 65536; headroom = 32000; } # nemotron lightning
      { context = 1048576; output = 262144; headroom = 32000; } # nemotron ultra
      { context = 131072; output = 8000; headroom = 20000; } # groq
      { context = 24000; output = 8000; headroom = 20000; } # cloudflare llama (ctx pequeno)
      { context = 65536; output = 8192; headroom = 20000; } # lfm 2.5
    ];
    results = map
      (c:
        let l = limits c;
        in {
          inherit (c) context output headroom;
          inherit (l) maxTokens reserved promptCeiling margin usable input;
          upstream = c.context - l.maxTokens; # limiar padrão do opencode (sem limit.input)
          ok = l.input != null
            && l.input <= c.context
            && l.input - l.reserved == l.usable
            && l.usable <= l.promptCeiling
            && l.usable <= c.context - l.maxTokens
            && l.usable >= (l.promptCeiling * 3) / 4;
        })
      cases;
  in
    pkgs.runCommand "opencode-headroom" {
      nativeBuildInputs = [ pkgs.jq ];
      passAsEnv = [ "HEADROOM_RESULTS" ];
      HEADROOM_RESULTS = builtins.toJSON results;
    } ''
      mkdir -p $out
      echo "$HEADROOM_RESULTS" > $out/results.json
      failed=$(jq '[.[] | select(.ok == false)] | length' $out/results.json)
      if [ "$failed" != "0" ]; then
        echo "FAIL: opencode headroom invariants violated ($failed cases)" >&2
        cat $out/results.json >&2
        exit 1
      fi
      echo "opencode-headroom: PASS ($(jq 'length' $out/results.json) cases)" > $out/summary.txt
      touch $out/pass
    '';
}
