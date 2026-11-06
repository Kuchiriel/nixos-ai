#!/usr/bin/env bash
# host-health.sh — veredito de SAÚDE DE RAM/SWAP do host (leitura only).
#
# POR QUE (06/11): o host travou por OOM global. O zram (15,5G) encheu
# 100% (thrash) e o OOM killer matou o llama-server (o modelo da voz) às
# 11:22. O Crouton (celular) já tem um watchdog que lê /proc pelo Tor;
# este script é a MESMA métrica no lado do host, para o bus e para o
# dono (sem depender de celular).
#
# VEREDITO (mesmo padrão do watchdog do Crouton):
#   CRITICO  se swap >= 90% OU zram >= 90% OU RAM livre < 400 MB
#   ATENCAO  se swap >= 75% OU RAM disponível < 2 GB
#   OK       caso contrário
#
# USO:
#   scripts/host-health.sh            # humano: tabela + veredito
#   scripts/host-health.sh --json     # uma linha JSON (watchdog/poll)
#   scripts/host-health.sh --quiet    # só o veredito (exit 0/1/2)
#
# EXIT: 0 = OK, 1 = ATENCAO, 2 = CRITICO (--quiet)
set -uo pipefail

MODE="human"
case "${1:-}" in
  --json) MODE="json" ;;
  --quiet) MODE="quiet" ;;
  "") ;;
  *) echo "uso: $0 [--json|--quiet]" >&2; exit 64 ;;
esac

# ── RAM ────────────────────────────────────────────────────────────────────
total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
avail_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
free_kb=$(awk '/^MemFree:/ {print $2}' /proc/meminfo)
used_kb=$(( total_kb - avail_kb ))

# ── SWAP ───────────────────────────────────────────────────────────────────
swap_total_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
swap_free_kb=$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)
swap_used_kb=$(( swap_total_kb - swap_free_kb ))

# ── ZRAM (o vilão do freeze: compressão consome CPU) ───────────────────────
# Uso do device zram (swap) via swapon + ratio de compressão via mm_stat.
zram_used_mb=0; zram_total_mb=0; zram_pct=0; zram_ratio="-"
if command -v swapon >/dev/null 2>&1; then
  _z=$(swapon --show=NAME,USED,SIZE --bytes --noheadings 2>/dev/null \
       | awk '$1 ~ /zram/ {print $2, $3; exit}')
  if [ -n "${_z:-}" ]; then
    zram_used_mb=$(( $(echo "$_z" | awk '{print $1}') / 1048576 ))
    zram_total_mb=$(( $(echo "$_z" | awk '{print $2}') / 1048576 ))
    [ "${zram_total_mb:-0}" -gt 0 ] && zram_pct=$(( zram_used_mb * 100 / zram_total_mb ))
  fi
fi
if [ -r /sys/block/zram0/mm_stat ]; then
  read -r _orig _compr _memtot _memlim _memmax _same _comp _huge < /sys/block/zram0/mm_stat 2>/dev/null || true
  if [ -n "${_orig:-}" ] && [ "${_orig:-0}" -gt 0 ] 2>/dev/null; then
    zram_ratio=$(awk -v o="$_orig" -v c="$_compr" 'BEGIN{printf "%.2fx", o/c}')
  fi
fi

# ── Swap % (o zram conta como swap) ────────────────────────────────────────
swap_pct=0
[ "${swap_total_kb:-0}" -gt 0 ] && swap_pct=$(( swap_used_kb * 100 / swap_total_kb ))
free_mb=$(( free_kb / 1024 ))
avail_mb=$(( avail_kb / 1024 ))

# ── Veredito ───────────────────────────────────────────────────────────────
verdict="OK"
rc=0
if [ "${swap_pct:-0}" -ge 90 ] || [ "${zram_pct:-0}" -ge 90 ] || [ "${free_mb:-0}" -lt 400 ]; then
  verdict="CRITICO"; rc=2
elif [ "${swap_pct:-0}" -ge 75 ] || [ "${avail_mb:-0}" -lt 2048 ]; then
  verdict="ATENCAO"; rc=1
fi

case "$MODE" in
  json)
    printf '{"verdict":"%s","ram_total_mb":%d,"ram_used_mb":%d,"ram_avail_mb":%d,"ram_free_mb":%d,"swap_total_mb":%d,"swap_used_mb":%d,"swap_pct":%d,"zram_total_mb":%d,"zram_used_mb":%d,"zram_pct":%d,"ts":"%s"}\n' \
      "$verdict" $(( total_kb / 1024 )) $(( used_kb / 1024 )) "$avail_mb" "$free_mb" \
      $(( swap_total_kb / 1024 )) $(( swap_used_kb / 1024 )) "$swap_pct" \
      "$zram_total_mb" "$zram_used_mb" "$zram_pct" "$(date -Is)"
    ;;
  quiet) echo "$verdict" ;;
  *)
    echo "=== host-health ($(hostname)) — $(date -Is) ==="
    echo "RAM:   $(( used_kb / 1024 ))/$(( total_kb / 1024 )) MB usada | livre ${free_mb}MB | disponível ${avail_mb}MB"
    echo "SWAP:  $(( swap_used_kb / 1024 ))/$(( swap_total_kb / 1024 )) MB (${swap_pct}%)"
    echo "ZRAM:  ${zram_used_mb}/${zram_total_mb} MB (${zram_pct}%) compressão ${zram_ratio}"
    echo "VEREDITO: $verdict"
    if [ "$verdict" != "OK" ]; then
      echo "  → o killer do kernel mata o llama-server (OOMScoreAdjust=1000); o host não deve travar."
      echo "  → feche sessões opencode/MT5 extras e rode: sudo sysctl -w vm.drop_caches=3"
    fi
    ;;
esac
exit $rc
