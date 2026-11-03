# Provider timeouts / Bad Request — diagnóstico e guard (03/11/2026)

## Sintoma (relato do dono)
- Turno do agente morre com `Provider response headers timed out after 300000ms`.
- `Bad Request` intermitente.
- Depois do timeout, a variant de reasoning effort volta de `max` para default.

## Evidência (`~/.local/share/opencode/log/opencode.log`, 03/11)
| classe | ocorrências | onde |
|---|---|---|
| `ProviderHeaderTimeoutError` (300000ms) | 9 | `ses_eb612ed53ffeyqq6z3SMv6OSSf` (nvidia/minimax-m3.1-flash), 06:11→06:37 local, de 5 em 5 min |
| `Too Many Requests` (429) | 270 | várias sessões (peer 05:42, `ses_e6008b7d…` 05:53) |
| `Bad Request` (400) | 5 | subagentes de research `ses_e6173c1b…` (00:25) e `ses_e6173c18…` (01:30) |
| `exceeds the available context size` | 1 | local-uncensored-4b, 20490 > 20480 tokens (`ses_e5ffac78…`, 06:08) |

## Causa raiz
1. **Timeout**: o default do opencode é `headerTimeout=300000ms`; a sessão carrega
   ~145k tokens de contexto e o prefill do NIM free passa de 5 min → o opencode
   **retenta 3×** (15 min) e só então falha. Não é bug de tool nem de rede local.
2. **429**: free tier do NIM saturado — vários agentes/sessões na mesma chave.
3. **400**: teto medido do NIM é `prompt_tokens + max_tokens ≤ context`
   (262146 > 262144 = 400); os subagentes estouram porque **subagente não compacta**.
4. **Overflow local**: server 4B com c=20480 e request de 20490.

## Mitigação implementada (hoje)
- **`scripts/agent-provider-guard.py`** (novo): lê o log do opencode (rabo de 4MB),
  classifica TIMEOUT/RATE/CTX/BADREQ/API, deduplica por epoch
  (`~/.local/state/jarvis/provider-guard.seen.json`) e, para cada evento novo,
  manda `notify-send -u critical` no desktop + nota (`agent-msg.sh --note`) p/ a peer.
  Uso: `scan [--since-min 20] [--max 5] [--dry-run] [--no-notify] [--no-peer]`.
  Testado verde: detecta o evento sintético e deduplica na 2ª rodada.
- **`scripts/agents-watcher.sh`**: bloco novo no ciclo (a cada `GUARD_EVERY=1` ciclo,
  janela `GUARD_SINCE=20` min) — o dono recebe o ping em ≤ ~2,5 min, não em 15.
  Watcher reiniciado (`active`).
- **`modules/ai/free-providers.json`**: `header_timeout`/`chunk_timeout` = 600000 no
  nvidia (fonte única) → **`home-manager/home.nix`** emite
  `provider.nvidia.options.{headerTimeout,chunkTimeout}` (schema 2.2.1 confirma).
  Semântica provada em `nix eval` (com/sem chave). **Só aplica no rebuild.**

## O que falta (decisão/estado do dono)
- **Rebuild** (bloqueado pelo reboot pendente, driver mismatch) p/ valer o timeout de 10 min.
- **429**: reduzir concorrência (wakes) ou rotear subagentes p/ outro provider free.
- **Subagentes sem compactação**: capar contexto/limite no agente `general`/`explore`.
- **Variant após timeout**: o reset em `model.json` é do cliente; as 3 camadas
  declarativas (EFFORT-VARIANT-PERSIST-2026-11-03.md) cobrem o rebuild, não o
  caminho "timeout → default".

## Validação
- `agent-provider-guard.py`: `py_compile` + `classes` + scan sintético + dedup ✓
- `agents-watcher.sh --check`: sintaxe + execução ✓
- `test_free_providers.py`: 6 passed ✓ · `json.tool` + `nix-instantiate --parse` ✓
- Suíte completa #2: 1822 passed, 21 skipped, 5 xpassed, 1 falha preexistente
  (`test_legacy_index.py::test_parity_with_synthetic_index`); `nix flake check` verde.
