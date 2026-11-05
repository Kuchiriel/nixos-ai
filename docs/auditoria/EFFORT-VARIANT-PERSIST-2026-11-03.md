# Reasoning effort (variant) que não volta após o rebuild — 2026-11-03

## Sintoma (dono)

> "depois do rebuild o reasoning effort seu no opencode vai pra default e sai
> do max e eu tenho que ficar voltando pro max"

O `max` escolhido no TUI voltava para `default` depois de cada
`./rebuild-host.sh`, e o dono tinha que escolher de novo.

## Onde o opencode guarda o effort

Em opencode v2 o "reasoning effort" é a **variant** do modelo
(`provider/model#max`). Ela vive em três lugares, e a confusão vem de eles
não coincidirem:

| lugar | o que guarda | quem escreve |
|---|---|---|
| `~/.local/state/opencode/model.json` → `variant` | mapa `model → variant` | o cliente (TUI) |
| `session.model.variant` no banco (`opencode.db` / `opencode-stable.db`) | a variant da sessão | o servidor |
| `opencode.json` (config, symlink do nix store) | `provider.<id>.models.<m>.options.reasoningEffort` e `agent.<n>.variant` | o Nix (declarativo) |

Ordem de aplicação da config (docs v2): **provider → model → variant**.
`default` é uma variant que **não** acrescenta nada (mantém o default do
provider), então o `options.reasoningEffort` do modelo continua valendo.

## Causa

O `rebuild-host.sh` → home-manager → **reinicia o `opencode-serve.service`**
(o unit é gerado pelo HM). Com o servidor novo:

1. o server re-resolve a variant da sessão a partir do agente/config →
   `default` (a config não tinha nada de variant);
2. o cliente lê isso e **reescreve** `model.json`, gravando `default` no lugar
   do `max` que o dono tinha escolhido.

Prova (03/11, antes do fix): o banco dizia `variant=max` para a sessão e a
API do servidor dizia `default` para a **mesma** sessão — o servidor não
restaura a variant do banco, ele re-resolve.

## Fix (3 camadas, todas declarativas)

1. **`options.reasoningEffort` por modelo** (`home-manager/home.nix`,
   `reasoningEffortDefaults`): o fallback do request. As escolhas vieram do
   próprio `model.json` do dono (o mapa `variant`). Merge com
   `pkgs.lib.recursiveUpdate` para **preservar** o `limit` do catálogo curado
   (`modules/ai/free-providers.json`); os modelos que só existem no
   models.dev carregam o `limit` próprio via `mkEffortModel` (mesma conta de
   headroom do `mkModel`).
2. **`agent.build = { model, variant }` casados** (schema v2: a variant do
   agente só vale para o modelo configurado dele): `build` = o
   `nvidia/minimaxai/minimax-m3.1-flash` com `variant = "max"` — decisão do
   dono em 03/11. Sem casar os dois, a variant do agente nunca entra em
   vigor para as sessões que rodam nvidia.
3. A **variant explícita da sessão** continua sobrescrevendo: o dono continua
   trocando na hora, e o que ele escolher passa a ser a fonte da verdade
   daquela sessão.

## Prova (03/11)

```
$ opencode run "diga apenas: ok"      # sem --model, agente build
> build · minimaxai/minimax-m3.1-flash
  id=ses_e5fe7b93…  agent=build  model=minimaxai/minimax-m3.1-flash  variant=max   ✔
  id=ses_e5fe8052…  agent=explore model=minimaxai/minimax-m3.1-flash  variant=default (esperado: só o build é pinado)
```

E o state do cliente voltou a guardar `max`:
`~/.local/state/opencode/model.json` → `nvidia/minimaxai/minimax-m3.1-flash: max`.

## Armadilhas (medidas)

- O **CLI 1.18.34 não entende a sintaxe `#variant`** (`opencode run --model
  provider/model#max` → "Unexpected server error"; ele manda o id inteiro
  como modelo). A sintaxe é do v2.
- O **servidor é opencode 2.2.1** (`opencode-serve.service`) e o **CLI é
  1.18.34** (`programs.opencode.package = pkgs.kilo`) — versões diferentes, o
  mesmo `opencode.json`. O schema do v2 tem `additionalProperties: false` na
  raiz: chave nova fora do schema **quebra** o servidor.
- Declarar um modelo no config **substitui** a entrada do catálogo
  (models.dev) → por isso o `limit` precisa vir junto.
- O provider nvidia é `@ai-sdk/openai-compatible`; a API aceita
  `reasoning_effort` (low/medium/high/xhigh/max) mas **no minimax-m3.1-flash
  o comprimento do thinking varia com o prompt, não com o nível** (medido:
  636/689/301/814 tokens de reasoning para low/high/xhigh/max na mesma
  pergunta). Ou seja: o nível é o que o dono **quer ver e manter**, não um
  ganho mensurável de qualidade nesse modelo.
- As sessões **já abertas** guardam a variant resolvida; o fix vale para as
  novas (e para as antigas assim que o cliente reescrever o `model.json`).

## Onde mexer

- `home-manager/home.nix` → `reasoningEffortDefaults` (effort por modelo) e
  `agent.build` (model + variant do agente build).
- `modules/ai/free-providers.json` → catálogo curado (limites/status).
- `~/.local/state/opencode/model.json` → o que o dono escolheu no TUI (fonte
  das escolhas do item 1; fora do Nix, se regenerar, pegue de novo aí).
