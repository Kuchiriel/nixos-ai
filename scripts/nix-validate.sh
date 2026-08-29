#!/usr/bin/env bash
# nix-validate.sh — Multi-layer validation for Nix/NixOS configurations.
#
# Validation layers (in order):
#   1. Nix syntax check (nix-instantiate --parse)
#   2. Flake evaluation (nix flake check)
#   3. Host configuration evaluation (nix eval)
#   4. Home Manager evaluation
#   5. Package builds (nix build)
#   6. Test suite (nix flake check tests)
#
# FAIL CLOSED: Any failure stops execution.
# NO || TRUE: Critical checks never swallow errors.
# NO TIMEOUT AS PROOF: Timeouts are timeouts, not proof of recursion.
#
# Usage:
#   ./scripts/nix-validate.sh              # Full validation
#   ./scripts/nix-validate.sh --quick      # Syntax + eval only
#   ./scripts/nix-validate.sh --host NAME  # Specific host
#
set -euo pipefail

# ═══ Configuration ═══

FLAKE_DIR="${FLAKE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
TARGET_HOST="${TARGET_HOST:-nitro-v15}"
QUICK=false
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --quick) QUICK=true; shift ;;
    --verbose) VERBOSE=true; shift ;;
    --host) TARGET_HOST="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ═══ Colors ═══

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✅ $1${NC}"; }
fail() { echo -e "${RED}❌ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
info() { echo -e "   $1"; }

# ═══ Validation Functions ═══

# Layer 1: Syntax check
validate_syntax() {
  echo ""
  echo "═══ Layer 1: Nix Syntax ═══"
  
  local failed=0
  local checked=0
  
  # Find all .nix files
  while IFS= read -r -d '' file; do
    checked=$((checked + 1))
    if ! nix-instantiate --parse "$file" > /dev/null 2>&1; then
      fail "Syntax error: $file"
      if $VERBOSE; then
        nix-instantiate --parse "$file" 2>&1 | head -5
      fi
      failed=$((failed + 1))
    fi
  done < <(find "$FLAKE_DIR" -name "*.nix" -not -path "*/result*" -not -path "*/.git/*" -print0 2>/dev/null)
  
  if [[ $failed -gt 0 ]]; then
    fail "Syntax check: $failed errors in $checked files"
    return 1
  fi
  
  pass "Syntax check: $checked files OK"
  return 0
}

# Layer 2: Flake evaluation
validate_flake() {
  echo ""
  echo "═══ Layer 2: Flake Evaluation ═══"
  
  # nix flake check runs all checks defined in the flake
  if ! nix flake check "$FLAKE_DIR" --no-build 2>&1 | tee /tmp/nix-validate-flake.log; then
    fail "Flake check failed"
    if $VERBOSE; then
      echo "Full log: /tmp/nix-validate-flake.log"
    fi
    return 1
  fi
  
  pass "Flake check OK"
  return 0
}

# Layer 3: Host configuration evaluation
validate_host() {
  echo ""
  echo "═══ Layer 3: Host Configuration ($TARGET_HOST) ═══"
  
  local expr="$FLAKE_DIR#nixosConfigurations.$TARGET_HOST.config.system.build.toplevel"
  
  # Evaluate with show-trace for debugging
  if ! nix eval "$expr" --show-trace 2>&1 | tee /tmp/nix-validate-host.log; then
    fail "Host evaluation failed"
    echo ""
    echo "Trace (last 20 lines):"
    tail -20 /tmp/nix-validate-host.log
    return 1
  fi
  
  pass "Host evaluation OK"
  return 0
}

# Layer 4: Home Manager evaluation
validate_home_manager() {
  echo ""
  echo "═══ Layer 4: Home Manager ═══"
  
  # Evaluate the home-manager configuration
  local expr="$FLAKE_DIR#nixosConfigurations.$TARGET_HOST.config.home-manager.users.nixos.home"
  
  if ! nix eval "$expr" --show-trace 2>&1 | tee /tmp/nix-validate-hm.log; then
    fail "Home Manager evaluation failed"
    echo ""
    echo "Trace (last 20 lines):"
    tail -20 /tmp/nix-validate-hm.log
    return 1
  fi
  
  pass "Home Manager evaluation OK"
  return 0
}

# Layer 5: Package builds
validate_packages() {
  echo ""
  echo "═══ Layer 5: Package Builds ═══"
  
  local failed=0
  
  # Build jarvis
  echo "   Building jarvis..."
  if ! nix build "$FLAKE_DIR#jarvis" --no-link --print-out-paths 2>&1 | tee /tmp/nix-validate-jarvis.log; then
    fail "Build failed: jarvis"
    failed=$((failed + 1))
  else
    pass "Build OK: jarvis"
  fi
  
  # Build jarvis-voice
  echo "   Building jarvis-voice..."
  if ! nix build "$FLAKE_DIR#jarvis-voice" --no-link --print-out-paths 2>&1 | tee /tmp/nix-validate-voice.log; then
    fail "Build failed: jarvis-voice"
    failed=$((failed + 1))
  else
    pass "Build OK: jarvis-voice"
  fi
  
  if [[ $failed -gt 0 ]]; then
    fail "Package builds: $failed failures"
    return 1
  fi
  
  pass "Package builds OK"
  return 0
}

# Layer 6: Test suite
validate_tests() {
  echo ""
  echo "═══ Layer 6: Test Suite ═══"
  
  # Run flake checks (includes tests)
  if ! nix flake check "$FLAKE_DIR" 2>&1 | tee /tmp/nix-validate-tests.log; then
    fail "Test suite failed"
    if $VERBOSE; then
      echo "Full log: /tmp/nix-validate-tests.log"
    fi
    return 1
  fi
  
  pass "Test suite OK"
  return 0
}

# ═══ Main ═══

echo "╔══════════════════════════════════════════════════════╗"
echo "║        Nix/NixOS Multi-Layer Validation             ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Host: $TARGET_HOST"
echo "║  Flake: $FLAKE_DIR"
echo "║  Mode: $(if $QUICK; then echo 'Quick'; else echo 'Full'; fi)"
echo "╚══════════════════════════════════════════════════════╝"

START_TIME=$(date +%s)
FAILED=0

# Layer 1: Syntax (always run)
if ! validate_syntax; then
  FAILED=$((FAILED + 1))
  echo ""
  fail "VALIDATION FAILED at Layer 1 (Syntax)"
  fail "Fix syntax errors before proceeding."
  exit 1
fi

# Layer 2: Flake check (always run)
if ! validate_flake; then
  FAILED=$((FAILED + 1))
  echo ""
  fail "VALIDATION FAILED at Layer 2 (Flake)"
  fail "Fix flake errors before proceeding."
  exit 1
fi

if ! $QUICK; then
  # Layer 3: Host evaluation
  if ! validate_host; then
    FAILED=$((FAILED + 1))
    echo ""
    fail "VALIDATION FAILED at Layer 3 (Host)"
    fail "Fix host configuration before proceeding."
    exit 1
  fi
  
  # Layer 4: Home Manager
  if ! validate_home_manager; then
    FAILED=$((FAILED + 1))
    echo ""
    fail "VALIDATION FAILED at Layer 4 (Home Manager)"
    fail "Fix Home Manager configuration before proceeding."
    exit 1
  fi
  
  # Layer 5: Package builds
  if ! validate_packages; then
    FAILED=$((FAILED + 1))
    echo ""
    fail "VALIDATION FAILED at Layer 5 (Packages)"
    fail "Fix package builds before proceeding."
    exit 1
  fi
  
  # Layer 6: Tests
  if ! validate_tests; then
    FAILED=$((FAILED + 1))
    echo ""
    fail "VALIDATION FAILED at Layer 6 (Tests)"
    fail "Fix test failures before proceeding."
    exit 1
  fi
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅ ALL VALIDATIONS PASSED                          ║"
echo "║  Duration: ${DURATION}s"
echo "╚══════════════════════════════════════════════════════╝"

exit 0
