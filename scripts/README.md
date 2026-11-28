# scripts/

Scripts operacionais do nixos-ai. Regra: sem hardcode acidental de host/IP; usar env/config.

## Checks

- `./scripts/check-hardcodes.sh` — verifica literais de IP tailnet fora da allowlist canônica.
  - Allowlist/decisão: `docs/auditoria/HARDCODES-ALLOWLIST-2026-11-28.md`
  - Esperado atual (28/11): `total_hits=13 allowlisted=13 outside_allowlist=0`
