#!/usr/bin/env bash
# Rebuild do sistema NixOS a partir do flake local.
# Valida avaliação ANTES de executar o switch.
# Uso: ./rebuild-host.sh [--host-only] [--quick] [--debug] [--home]
#   --host-only: valida host+HM sem flake-check total (lab quebrado não trava o host).
#   --quick:    só sintaxe+eval (pula builds/testes; p/ iterar rápido em .nix).
#   --debug:    executa tudo com output redirecionado para log e exibe o log ao final.
#   --home:     SÓ O HOME-MANAGER (13/10, dono: "pode modificar os scripts de
#               build pra aceitar flag só pro home manager e rebuildar se quiser").
#               Build do activationPackage do usuário + activate — NÃO roda
#               nh os switch, NÃO toca host/services/serviços do sistema.
#               Renicia os units de usuário alterados (daemon-reload +
#               restart dos timers agents-*).
# NOTA (IMP-018): este script faz `git add -A` + commit automático
# "chore: update N file(s)" com sua identidade — o flake SÓ enxerga o índice
# git, então sem isso arquivos novos são invisíveis p/ o build. Efeito real:
# todo rebuild commita a árvore suja. Revise com `git show HEAD` após o
# rebuild; mensagens genéricas são o preço da visibilidade do flake.
set -e

DEBUG=false
HOME_ONLY=false
VALIDATE_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --debug) DEBUG=true ;;
        --home) HOME_ONLY=true ;;
        *) VALIDATE_ARGS+=("$arg") ;;
    esac
done

if [ "$DEBUG" = true ]; then
    LOG_FILE="/tmp/rebuild-$(date +%Y%m%d-%H%M%S).log"
    exec > >(tee "$LOG_FILE") 2>&1
    echo "🔍 Modo DEBUG ativo. Log: $LOG_FILE"
fi

FLAKE_DIR="$HOME/projects/nixos-ai"
TARGET_HOST="nitro-v15"

# nh 4.4.2+: usa NH_FLAKE; o FLAKE antigo (sessão pré-upgrade) dispara warning.
export NH_FLAKE="$FLAKE_DIR"
unset FLAKE

# ═══ Multi-Layer Validation ═══
# Roda validação completa antes de qualquer rebuild.
# Se qualquer camada falhar, o rebuild NÃO é executado.

echo "===================================================="
echo "EXECUTANDO VALIDAÇÃO MULTI-CAMADA"
echo "===================================================="

if ! "$FLAKE_DIR/scripts/nix-validate.sh" --host "$TARGET_HOST" "${VALIDATE_ARGS[@]}"; then
  echo ""
  echo "[ERRO CRÍTICO] Validação falhou!"
  echo "Corrija os erros acima ANTES de fazer rebuild."
  echo "O rebuild NÃO será executado."
  exit 1
fi

echo ""
echo "===================================================="

echo "===================================================="
echo "INDEXANDO ALTERAÇÕES NO GIT"
echo "===================================================="
cd "$FLAKE_DIR"
git add -A
# Flakes só enxergam arquivos versionados no Git.
if git diff --cached --quiet; then
  echo "      (nenhuma alteração pendente)"
else
  N_FILES=$(git diff --cached --name-only | wc -l)
  echo "      Arquivos staged p/ este rebuild (commit automático abaixo):"
  git diff --cached --name-status | sed 's/^/        /'
  git commit -m "chore: update $N_FILES file(s)"
  echo "      (revise depois com: git show HEAD --stat)"
fi
cd - > /dev/null

echo ""
echo "===================================================="
echo "EXECUTANDO REBUILD"
echo "===================================================="

if [ "$HOME_ONLY" = true ]; then
    echo "[--home] build do activationPackage do usuário ($USER) + activate"
    nix build "$FLAKE_DIR#nixosConfigurations.$TARGET_HOST.config.home-manager.users.$USER.home.activationPackage" \
        --out-link /tmp/opencode/hm-activation --print-build-logs
    /tmp/opencode/hm-activation/activate
    # units de usuário alterados precisam de reload + restart explícito
    # (o activate faz daemon-reload; restart não é garantido p/ timers)
    systemctl --user daemon-reload
    systemctl --user restart agents-heartbeat-watchdog.timer 2>/dev/null || true
    echo "[--home] HOME-MANAGER ATUALIZADO (host intocado)"
    echo ""
    echo "===================================================="
    echo "✅ HOME ATUALIZADO COM SUCESSO (--home)"
    echo "===================================================="
    exit 0
fi

if [ "$DEBUG" = true ]; then
  nh os switch "$FLAKE_DIR" -H "$TARGET_HOST" -- --show-trace --option binary-caches-parallel-connections 4 --option http-connections 5 2>&1 | tee -a "$LOG_FILE"
else
  nh os switch "$FLAKE_DIR" -H "$TARGET_HOST" -- --option binary-caches-parallel-connections 4 --option http-connections 5
fi

echo ""
echo "===================================================="
echo "✅ SISTEMA ATUALIZADO COM SUCESSO"
echo "===================================================="