# Allowlist canônica — hardcodes host/IP (2026-11-28, herald-termux-vision)

Objetivo: distinguir hardcodes **intencionais/canônicos** de hardcodes **acidentais**. Sem alterar comportamento.

## Allowlist (exceções documentadas)

| Padrão/arquivo | Motivo | Ação |
|---|---|---|
| `scripts/agent-config.json` | SSOT de endpoints tailnet/host | manter; mudar só com prova + atualização coordenada |
| `hosts/nitro-v15/**` | configuração Nix específica do host | manter |
| `home-manager/home.nix` | wiring host-specific | manter; preferir opções quando possível |
| `home-manager/modules/services/opencode-serve.nix` | bind tailnet intencional | manter |
| `home-manager/modules/services/coord-mcp.nix` | bind tailnet intencional | manter |
| `home-manager/modules/services/jarvis-knowledge-mcp.nix` | bind tailnet intencional | manter |
| `home-manager/modules/agent-hub.nix` | forward tailnet intencional | manter |
| `tests/test_agent_msg_channel.py` | teste de contrato da config | manter alinhado ao contrato |
| `modules/ai/jarvis/src/jarvis/core/{comms,coord,coord_roster}.py`, `scripts/agent-roster.py` | aliases/normalização de identidade (nitro-v15 etc) | manter; não dinamizar como hostname |

## Fora da allowlist (corrigir ou justificar)
- Literais de IP/hostname em scripts py/sh/mjs/js novos devem usar env/config/hostname.
- Fallback literal só com comentário explícito e exceção registrada aqui.

## Check rápido (evidência)
```bash
cd ~/projects/nixos-ai
git ls-files '*.py' '*.sh' '*.mjs' '*.js' '*.nix' '*.json' | \
  xargs grep -lE '100\.104\.175\.123|100\.121\.100\.103' | sort
```
Comparar saída com allowlist acima; diferença = candidato a correção/documentação.

## Números (sweep 2026-11-28)
- Hits totais IP/hostname: 644 (inclui docs/histórico).
- Código/config IP: 12 arquivos; nitro-v15 code: 24 arquivos.
- 2ª passada nitro-v15 scripts/módulos: 9 hits / 6 arquivos, todos alias/comentário/teste.
