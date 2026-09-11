#!/usr/bin/env bash
# Faxina SEGURA do NixOS: nunca deixa o sistema sem rollback.
#
# Regras duras:
#   1. Mantém SEMPRE a geração atual + a anterior (rollback garantido).
#   2. NUNCA `nix-collect-garbage -d` (apagaria tudo, inclusive rollback).
#   3. Verifica saúde da geração atual ANTES de apagar qualquer coisa.
#   4. Cada etapa é best-effort com aviso (faxina não pode quebrar boot).
# Uso: ./clean.sh

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # Sem cor

SYSTEM_PROFILE="/nix/var/nix/profiles/system"
KEEP_DAYS=7   # gerações mais antigas que isso são candidatas (respeitando regra 1)

echo -e "${BLUE}=== FAXINA SEGURA DO NIXOS (mantém atual + rollback) ===${NC}"

# ── 0. Pré-voo: geração atual íntegra? ──────────────────────────────
echo -e "\n${YELLOW}[0/5] Verificando saúde da geração atual...${NC}"
CURRENT_GEN=$(readlink "$SYSTEM_PROFILE" 2>/dev/null || echo "")
if [ -z "$CURRENT_GEN" ]; then
    echo -e "${RED}Não identifiquei a geração atual. ABORTANDO (regra 1).${NC}"
    exit 1
fi
if ! nix path-info --derivation "$SYSTEM_PROFILE" > /dev/null 2>&1; then
    echo -e "${RED}Geração atual com store path inválido. ABORTANDO.${NC}"
    exit 1
fi
echo -e "${GREEN}Atual OK: $(basename "$CURRENT_GEN")${NC}"

# ── 1. Home Manager: expira por tempo (mantém recentes) ─────────────
echo -e "\n${YELLOW}[1/5] Home Manager: expirando gerações > ${KEEP_DAYS}d...${NC}"
if command -v home-manager &> /dev/null; then
    home-manager expire-generations "-${KEEP_DAYS} days" || echo -e "${YELLOW}Aviso: expire-generations falhou, seguindo.${NC}"
else
    echo -e "${YELLOW}Home Manager não encontrado, pulando...${NC}"
fi

# ── 2. Sistema: apaga gerações velhas, SALVA as 2 mais novas ────────
echo -e "\n${YELLOW}[2/5] Sistema: removendo gerações > ${KEEP_DAYS}d (exceto as 2 mais novas)...${NC}"
GEN_LIST=$(sudo nix-env --profile "$SYSTEM_PROFILE" --list-generations 2>/dev/null | awk '{print $1}' | sort -n)
N_GEN=$(echo "$GEN_LIST" | wc -l)
# IDs das 2 mais novas (nunca apagar, mesmo se velhas)
KEEP_IDS=$(echo "$GEN_LIST" | tail -2 | tr '\n' ' ')
echo "      Gerações: $N_GEN total; preservadas (atual+rollback): $KEEP_IDS"
# Candidatas: mais velhas que KEEP_DAYS, fora das preservadas
CUTOFF=$(date -d "$KEEP_DAYS days ago" +%s 2>/dev/null || echo 0)
TO_DELETE=""
for g in $GEN_LIST; do
    case " $KEEP_IDS " in *" $g "*) continue;; esac  # regra 1: preservada
    GDATE=$(sudo nix-env --profile "$SYSTEM_PROFILE" --list-generations 2>/dev/null | awk -v id="$g" '$1==id {print $2, $3}')
    GTS=$(date -d "$GDATE" +%s 2>/dev/null || echo 0)
    if [ "$GTS" -lt "$CUTOFF" ] && [ "$GTS" -ne 0 ]; then
        TO_DELETE="$TO_DELETE $g"
    fi
done
if [ -z "$TO_DELETE" ]; then
    echo "      Nada a remover (tudo recente ou preservado)."
else
    echo "      Removendo gerações:$TO_DELETE"
    # shellcheck disable=SC2086
    sudo nix-env --profile "$SYSTEM_PROFILE" --delete-generations $TO_DELETE || echo -e "${YELLOW}Aviso: remoção parcial, seguindo.${NC}"
fi

# ── 3. GC sem -d: só o inalcançável ─────────────────────────────────
echo -e "\n${YELLOW}[3/5] Garbage collector (só inalcançável; rollback protegido)...${NC}"
nix-collect-garbage --delete-older-than ${KEEP_DAYS}d || echo -e "${YELLOW}Aviso: GC usuário falhou, seguindo.${NC}"

# ── 4. Optimise (hardlinks) ─────────────────────────────────────────
echo -e "\n${YELLOW}[4/5] Otimizando store (hardlinks)...${NC}"
nix store optimise 2>/dev/null || sudo nix-store --optimise 2>/dev/null || echo -e "${YELLOW}Aviso: optimise indisponível, seguindo.${NC}"

# ── 5. Verificação pós-faxina: rollback ainda existe? ───────────────
echo -e "\n${YELLOW}[5/5] Verificando rollback pós-faxina...${NC}"
N_AFTER=$(sudo nix-env --profile "$SYSTEM_PROFILE" --list-generations 2>/dev/null | wc -l)
if [ "$N_AFTER" -lt 2 ]; then
    echo -e "${RED}ATENÇÃO: só $N_AFTER geração(ões) restante(s)! Rollback comprometido.${NC}"
else
    echo -e "${GREEN}OK: $N_AFTER gerações preservadas (atual + rollback).${NC}"
fi
if ! nix path-info "$SYSTEM_PROFILE" > /dev/null 2>&1; then
    echo -e "${RED}CRÍTICO: geração atual inválida pós-faxina! Não reinicie sem investigar.${NC}"
    exit 1
fi

echo -e "\n${GREEN}=== FAXINA SEGURA CONCLUÍDA ===${NC}"
df -h /nix | tail -1
