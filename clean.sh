#!/usr/bin/env bash

# Configuração de cores para o terminal
GREEN='\033[0-32m'
BLUE='\033[0-34m'
YELLOW='\033[1-33m'
RED='\033[0-31m'
NC='\033[0m' # Sem cor

echo -e "${BLUE}=== INICIANDO FAXINA COMPLETA NO NIXOS (MIGRAÇÃO UNSTABLE) ===${NC}"

# 1. Limpar gerações antigas do Home Manager (Usuário Atual)
echo -e "\n${YELLOW}[1/6] Limpando gerações antigas do Home Manager do usuário...${NC}"
if command -v home-manager &> /dev/null; then
    home-manager expire-generations "-0 days"
    home-manager remove-generations old
else
    echo -e "${RED}Home Manager não encontrado isoladamente, pulando...${NC}"
fi

# 2. Limpar perfis e histórico do canal de usuário (Sem Sudo)
echo -e "\n${YELLOW}[2/6] Removendo histórico de perfis locais e pacotes do usuário...${NC}"
nix-env --delete-generations old
nix-collect-garbage --delete-older-than 7d

# 3. Limpar gerações do sistema e histórico de boot (Exige Sudo)
echo -e "\n${YELLOW}[3/6] Limpando gerações antigas do Sistema Operacional (Histórico de Boot)...${NC}"
sudo nix-env --profile /nix/var/nix/profiles/system --delete-generations old
sudo nix-profile wipe-history --profile /nix/var/nix/profiles/system 2>/dev/null || true

# 4. Coleta de lixo eletrônico profunda (Garbage Collector Unstable CLI)
echo -e "\n${YELLOW}[4/6] Disparando Garbage Collector moderno no /nix/store...${NC}"
sudo nix-collect-garbage -d
nix store gc --verbose

# 5. Otimização e Desduplicação pesada (Hardlinks de arquivos idênticos)
echo -e "\n${YELLOW}[5/6] Analisando arquivos idênticos e criando hardlinks de otimização...${NC}"
echo -e "${BLUE}Nota: Isso pode demorar alguns minutos dependendo do tamanho do disco.${NC}"
sudo nix-store --optimise
nix store optimise --verbose

# 6. Verificar espaço final em disco
echo -e "\n${GREEN}=== FAXINA CONCLUÍDA COM SUCESSO! ===${NC}"
echo -e "${BLUE}Espaço atual do sistema de arquivos /nix:${NC}"
df -h /nix

