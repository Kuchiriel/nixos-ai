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
# NOTA (07/11, dono + lane crouton-alpha): este script faz `git add -A` p/ o
# flake enxergar o índice — mas NÃO commita mais por default. O
# "chore: update N file(s)" automático varreria o WIP de TODAS as lanes numa
# árvore compartilhada (medido 3x). Default = stage sem commit (flake ok,
# histórico limpo). Commit = opt-in explícito com --commit.
#   --commit  : comportamento legado (commit "chore: update N file(s)")
set -e

DEBUG=false
HOME_ONLY=false
AUTO_COMMIT=false
VALIDATE_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --debug) DEBUG=true ;;
        --home) HOME_ONLY=true ;;
        --commit) AUTO_COMMIT=true ;;
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

# (13/11) Symlink absoluto dentro do repo quebra o eval puro ("access to
# absolute path ... is forbidden") e ja custou dois rebuilds: o home-manager
# gerenciou arquivos cujo diretorio em ~/.config era symlink para a arvore.
# Falhar aqui, com o path na mao, e mais barato que descobrir no Layer 3.
if ! python3 "$FLAKE_DIR/scripts/check-repo-symlinks.py" "$FLAKE_DIR" --quiet; then
  echo ""
  echo "[ERRO CRÍTICO] Symlink absoluto no repo (eval puro falha)."
  echo "Troque por arquivo regular ou link relativo e rode de novo."
  exit 1
fi

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
  echo "      Arquivos staged p/ este rebuild:"
  git diff --cached --name-status | sed 's/^/        /'
  if [ "$AUTO_COMMIT" = true ]; then
    git commit -m "chore: update $N_FILES file(s)"
    echo "      (commit automático — revise com: git show HEAD --stat)"
  else
    echo "      (sem commit — rode com --commit se quiser o 'chore' automático)"
  fi
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

# (11/11, sweep-2026-11) AS UNITS DE SISTEMA VOLTAM. O switch para as parts do
# jarvis.target quando o arquivo da unit muda, mas o TARGET e estatico (sempre
# ativo, sem timestamp proprio): como ele nunca e parado nem reiniciado, as
# parts nao voltam. MEDIDO 11/11: o router (llama-cpp-server, :8080) ficou
# INACTIVE das 15:10:09 as 22:5x, ou seja 7h37 com o LLM local fora do ar e
# ninguem percebendo (o proprio script documenta que "rebuild ativa config e
# reinicia servicos": aqui ele nao reiniciava). O restart do target propaga
# para as parts (PartOf=jarvis.target), e um restart do grupo inteiro custa
# alguns segundos de inferencia local, que e o que o rebuild ja faz.
if [ "$HOME_ONLY" != true ]; then
    echo "[rebuild] religando o jarvis.target (e as parts: router, embeddings, rerank, qdrant, webui)"
    systemctl restart jarvis.target 2>/dev/null || \
        echo "[rebuild] AVISO: restart do jarvis.target falhou; conferir as units de inferencia"
fi

echo ""
echo "===================================================="
echo "✅ SISTEMA ATUALIZADO COM SUCESSO"
echo "===================================================="