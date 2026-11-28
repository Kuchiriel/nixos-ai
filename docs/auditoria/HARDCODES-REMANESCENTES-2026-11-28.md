# Hardcodes remanescentes — sweep 2026-11-28 (herald-termux-vision)

## Escopo medido
- Scan: `git ls-files | xargs grep -nE '100\.104\.175\.123|100\.121\.100\.103|nitro-v15'`
- Total hits: **644** (inclui docs/arquivo/histórico).
- Hits em código/config (`*.py,*.sh,*.mjs,*.js,*.nix,*.json,*.toml,*.yaml,*.yml`):
  - IPs tailnet: **12 arquivos**.
  - `nitro-v15`: **24 arquivos**.

## Classificação (IPs tailnet)

### Dinâmico/aceitável (env-first, fallback literal documentado)
- `modules/ai/jarvis/src/jarvis/coord_http.py` — `TERMUX_PHONE_SSH/TERMUX_PHONE_PORT` env; fallback literal mantido (conveniência local; default neutro quebraria alcance do phone sem config). Exceção documentada.
- `scripts/async-fleet.py`, `scripts/async-fleet2.py` — `TERMUX_PHONE_SSH` env; fallback literal local, env tem precedência. Exceção documentada.
- `scripts/fleet-milestone.py` — `TERMUX_PHONE_SSH/PHONE` env; fallback literal local, env tem precedência. Exceção documentada.
- Decisão 28/11: manter fallback literal + comentário explícito; não trocar para default neutro sem prova de não regressão.

### Contrato/config canônico (exceção documentada, não alterar cegamente)
- `scripts/agent-config.json` — SSOT de endpoints tailnet do host.
- `hosts/nitro-v15/configuration.nix`, `home-manager/home.nix`, `home-manager/modules/services/opencode-serve.nix`, `home-manager/modules/services/coord-mcp.nix`, `home-manager/modules/services/jarvis-knowledge-mcp.nix`, `home-manager/modules/agent-hub.nix` — topologia Nix do host; valores intencionais.
- `tests/test_agent_msg_channel.py` — asserts de contrato contra config atual.

## nitro-v15
Maioria é host-specific esperado (`hosts/nitro-v15/*`, `flake.nix`, módulos Nix, rebuild). Hardcodes funcionais em scripts devem ser migrados para `hostname`/env quando seguro; não aplicar em massa sem teste.

## Próximo passe
1. Converter fallbacks literais para defaults neutros só onde houver prova de não regressão.
2. Varrer `nitro-v15` em scripts Python/sh/mjs (excluir hosts/flake/docs).
3. Adicionar check de CI/lint para novos IPs literais fora de allowlist.


## Passe nitro-v15 em scripts (28/11, herald-termux-vision)
- Escopo: `scripts/*.py,sh,mjs,js`, `modules/**/*.py,sh`, `tests/*.py` (excl. archive/hosts/flake/docs).
- Hits: 12 arquivos.
- Alterados (cosmético/seguro): `scripts/async-fleet.py`, `scripts/f30-dashboard.py`, `scripts/host-proxy.mjs` (comentário/display genérico).
- Exceções funcionais (não dinamizar cego): aliases/normalização de identidade em `modules/ai/jarvis/src/jarvis/core/comms.py`, `core/coord.py`, `core/coord_roster.py`, `scripts/agent-roster.py`; testes de contrato/fixtures em `modules/ai/jarvis/tests/*`, `tests/test_agent_model_rotation.py`, `tests/test_agent_msg_channel.py`.
