#!/usr/bin/env bash
# fix-qdrant.sh — Reparo one-shot do Qdrant após o upgrade NixOS 24.11 → 26.05.
#
# Contexto: o storage do Qdrant foi criado com a versão 1.12.x (nixpkgs 24.11).
# O upgrade para 26.05 trouxe o Qdrant 1.17.1, que não consegue ler o formato
# antigo dos segment states (`unknown variant 'on_disk', expected 'mmap' or
# 'in_ram_mmap'`), derrubando o serviço em start-limit-hit.
#
# A solução é descartar o storage antigo (é estado de runtime recriável pela
# migração/indexação — nada declarativo se perde) e reiniciar o serviço.
#
# Uso:
#   sudo ./fix-qdrant.sh
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${YELLOW}=== FIX QDRANT: storage incompatível pós-upgrade 1.12 → 1.17 ===${NC}"

# 0. Mata processos qdrant manuais que possam segurar a porta 6333
#    (ex: instâncias de teste iniciadas à mão com --config-path)
echo -e "[0/5] Encerrando processos qdrant manuais (se houver)..."
pkill -f "qdrant --config-path" 2>/dev/null || true
sleep 1

# 1. Para o serviço (se estiver rodando)
if systemctl is-active --quiet qdrant; then
    echo -e "[1/5] Parando qdrant.service..."
    systemctl stop qdrant
else
    echo -e "[1/5] qdrant.service já está parado."
fi

# 2. Descarta o storage antigo (estado de runtime, recriável)
#    /var/lib/qdrant é symlink → /var/lib/private/qdrant (StateDirectory).
STORAGE="/var/lib/private/qdrant/storage"
if [ -d "$STORAGE" ]; then
    echo -e "[2/5] Removendo storage antigo: $STORAGE"
    rm -rf "$STORAGE"
else
    echo -e "[2/5] Storage não encontrado em $STORAGE (nada a remover)."
fi

# 3. Reinicia o serviço (reset-failed limpa o start-limit-hit)
echo -e "[3/5] Iniciando qdrant.service..."
systemctl reset-failed qdrant || true
systemctl start qdrant

# 4. Verifica o health
echo -e "[4/5] Aguardando Qdrant subir na 6333..."
for i in $(seq 1 20); do
    if curl -sf "http://127.0.0.1:6333/collections" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Qdrant ativo em http://127.0.0.1:6333${NC}"
        exit 0
    fi
    sleep 1
done

echo -e "${RED}✗ Qdrant não respondeu na 6333. Veja: journalctl -u qdrant -n 50${NC}"
exit 1
