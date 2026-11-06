---
description: Liga/desliga o modo red-team (transliteracao trigger/decoy + bloco de estrategia)
agent: build
---

O comando `/jailbreak` e resolvido pelo plugin `redteam.js` (hook
`command.execute.before`) — o modelo nao ve este texto.

Subcomandos:

- `/jailbreak on` — liga o modo (transliteracao + bloco de estrategia)
- `/jailbreak off` — desliga
- `/jailbreak status` — mostra o estado
- `/jailbreak pair <trigger> <decoy>` — define o par de palavras

Exemplo: `/jailbreak pair senha s3nh4`

Estado em `~/.local/state/opencode/redteam.json`.
Log da transliteracao em `~/.local/state/opencode/redteam-audit.log`.
