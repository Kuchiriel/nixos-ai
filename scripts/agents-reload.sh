#!/usr/bin/env bash
# agents-reload.sh — empurra mudanças para os agentes LOCAIS, sem reiniciar nada.
#
# POR QUE (15/11, crouton-alpha): a casa nao tinha um comando unico para
# isso, e o plugin do opencode vive como symlink do nix store (read-only) —
# ninguem conseguia tocar o arquivo para o watcher recarregar. Este script
# resolve o que a casa ja tem:
#
#   1) PLUGINS: o opencode tem WATCHER (medido: "watcher subscribe" no log).
#      Apontar o symlink do plugin para o arquivo VIVO do repo e tocar o
#      arquivo faz TODAS as sessoes vivas recarregarem o plugin — sem
#      restart, sem rebuild.
#   2) CONFIG: `opencode reload` recarrega a config sem reiniciar o server
#      ("Running sessions continue with fresh services at the next step
#      boundary" — doc do opencode).
#   3) MODELOS: a casa tem hot-swap de modelo (models.nix extraProfiles +
#      `/model jarvis-raw*` no TUI, com o llama-server servindo os presets).
#      Este comando mostra o que esta VIVO agora (alias + porta + ctx) e o
#      alias para trocar; nao inventa: se o router nao serve o preset, diz.
#
# uso:
#   agents-reload.sh              # plugins + config + estado dos modelos
#   agents-reload.sh plugins      # so plugins (hot reload das sessoes vivas)
#   agents-reload.sh config       # so config
#   agents-reload.sh models       # so o estado dos modelos (locais + API)
set -uo pipefail
REPO="$HOME/projects/nixos-ai"
PLUGDIR="$HOME/.config/opencode/plugins"
SRC="$REPO/home-manager/files/opencode/plugins"
export PATH="$HOME/bin:/etc/profiles/per-user/nixos/bin:$PATH"

log() { echo "[reload] $*"; }

reload_plugins() {
  local n=0
  [ -d "$SRC" ] || { log "sem fonte de plugins em $SRC"; return 0; }
  for f in "$SRC"/*.js "$SRC"/*.ts; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    live="$PLUGDIR/$base"
    # (1) o symlink aponta para o store (read-only) -> aponta para o REPO
    if [ -L "$live" ]; then
      ln -sfn "$f" "$live"
    elif [ ! -e "$live" ]; then
      ln -sfn "$f" "$live"
    fi
    # (2) MEDIDO 15/11: tocar o arquivo NAO recarrega nada (o watcher compara
    # o DIGEST do caminho watchado, que e o symlink; mtime/content do alvo
    # nao entra). O que recarrega de verdade: (a) re-apontar o symlink
    # (mudanca de caminho) ou (b) `opencode reload` (forca tudo). Por isso
    # este script NAO toca: ele re-aponta e deixa o reload para a etapa
    # seguinte (que roda opencode reload).
    n=$((n+1))
  done
  log "plugins: $n symlink(s) apontando para o arquivo VIVO do repo"
  log "  (o proximo rebuild do HM pode voltar a apontar pro store; este script refaz)"
}

reload_config() {
  if command -v opencode >/dev/null 2>&1; then
    out=$(timeout 60 opencode reload 2>&1 | head -2)
    log "config: ${out:-sem retorno}"
  else
    log "config: opencode nao encontrado"
  fi
}

reload_models() {
  echo "[reload] modelos LOCAIS vivos (descobertos do opencode.json + servidores):"
  python3 "$REPO/scripts/model-catalog.py" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print('  (nao deu p/ ler o catalogo)'); raise SystemExit(0)
for m in d.get('local_live', []):
    print('  %-44s porta %-6s ctx %s' % (m.get('full_id'), m.get('port'), m.get('context') or '?'))
gate = (d.get('rate_limit') or {}).get('nvidia_gate') or {}
if gate:
    print('  nvidia-gate: %s requests · %s 429 upstream · %s retries · rpm %s' %
          (gate.get('requests'), gate.get('upstream_429'), gate.get('retries'), gate.get('rpm_limit')))
print('  hot-swap da casa: /model <alias> no TUI (models.nix extraProfiles)')
" 2>/dev/null
}

case "${1:-all}" in
  plugins) reload_plugins ;;
  config) reload_config ;;
  models) reload_models ;;
  all) reload_plugins; reload_config; reload_models ;;
  *) echo "uso: $0 [all|plugins|config|models]"; exit 1 ;;
esac
