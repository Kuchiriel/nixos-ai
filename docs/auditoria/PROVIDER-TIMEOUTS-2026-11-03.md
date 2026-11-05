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

## 429 resolvido: nv-gate (03/11, 11:55–12:05)

**Causa raiz medida**: o free tier do `integrate.api.nvidia.com` responde **40
requests/minute por chave** (limite documentado no fórum NVIDIA; há também
controle automático de "free-tier abusers" que pune rajadas de agentes). Com
2–3 agentes simultâneos, cada turno = 1 request por passo de tool-call → 40
RPM estourados em segundos → `AI_APICallError: Too Many Requests` matando o
turno inteiro (o opencode só faz 3 retries rápidos).

**Solução**: `scripts/nv-gate.py` — proxy TRANSPARENTE na frente do provider:
- token bucket compartilhado (24 RPM, burst 4) → rajada vira fila, não 429;
- 429 do upstream → retry com backoff (honra `Retry-After`) → o cliente opencode
  **vê a resposta**, não um erro;
- SSE em streaming (chunk a chunk, sem bufferizar);
- o header `Authorization` é repassado intacto: **o gate não guarda chave**;
- `GET /__gate/health` → contadores (sem segredo).

**Declarativo**: `modules/ai/free-providers.json` → `providers.nvidia.gate`
(porta/rpm/burst/upstream = fonte única) → `home-manager/home.nix`
(`mkCloudProvider`) emite `baseURL = http://127.0.0.1:8095/v1` e o module
`home-manager/modules/services/nv-gate.nix` sobe o serviço (user systemd,
`Restart=always`).

**Medido**:
- sintético (upstream falso 429×2 → 200): `upstream_429: 2, retries: 2` ✓;
- real: request direto deu 200; pelo gate, **1 upstream 429 foi absorvido** e o
  cliente recebeu 200 ✓;
- `opencode run -m nvidia/minimaxai/minimax-m3.1-flash` → "gate-ok" e o
  contador do gate subiu para 1 → a cadeia config→gate→provider funciona ✓;
- serviço `nv-gate.service` active; `opencode.json` live com
  `baseURL: http://127.0.0.1:8095/v1` ✓.

**Caveat**: cliente já aberto (TUI) mantém o config em memória → as sessões
**antigas** continuam batendo no endpoint cru até reiniciar o processo. Sessões
novas já nascem com o gate.

## Vazamento de segredos no journal (03/11, corrigido)

`/etc/litellm.env` usa `export KEY=...`. O `EnvironmentFile` do systemd recusa
essa forma e **loga a linha inteira** (`Ignoring invalid environment
assignment 'export NVIDIA_API_KEY=nvapi-...'`): 206 linhas/dia no journal do
`jarvis-telegram`, com `sk-or-v1-*`, `sk-*` e `nvapi-*` em cleartext — e a
variável nem entrava no ambiente do serviço.

**Fix**: `modules/services/jarvis-keys-env.nix` gera o espelho
`/run/jarvis/litellm.env` (formato `KEY=valor`, 0600 root) num unit oneshot
(`jarvis-keys-env.service`, `before=jarvis-telegram.service`) + um
`systemd.path` que regenera quando a fonte muda (rotação de chave sem
reboot). O `jarvis-telegram` passou a ler o espelho. O `/etc/litellm.env`
continua intacto (o shell precisa de `export`).

**Verificado**: mirror com 35 chaves, 0600 root; `jarvis-telegram` com **24
variáveis API_KEY no ambiente** (antes: 0); **0** novas linhas
"Ignoring invalid environment assignment" depois do restart.

> As chaves que já ficaram no journal devem ser consideradas expostas:
> rotação é ação do dono (dashboard). O journal não é apagado aqui
> (proibido deletar histórico).

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
