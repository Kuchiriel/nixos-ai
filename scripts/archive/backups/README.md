# archive/backups — backups históricos do agent-hub

Convenção da casa: **nunca deletar backups, arquivar com data**. Estes
foram mantidos na raiz de `scripts/` por acidente e agora estão aqui.

| Arquivo | Origem | Motivo do arquivo |
|---|---|---|
| `agent-hub.mjs.bak-16-11` | versão de 16/11 | backup pré-refatoração do hub |
| `agent-hub.mjs.bak-17-11` | versão de 17/11 | backup antes da UI ser separada para agent-hub-ui.html |
| `agent-hub.mjs.bak-17-11-house` | versão de 17/11 | variante com foco na casa |
| `agent-hub.mjs.bak-171949` | versão antiga | backup pré-limpeza de hardcoded |
| `agent-hub.mjs.bak-185303` | versão antiga | backup pré-mudança de BIND |
| `agent-hub.mjs.bak-20261114` | versão de 14/11 | backup pré-token do hub |
| `agent-hub.mjs.bak-20261115-bus` | versão de 15/11 | backup pré-integração com bus |
| `agent-hub-ui.html.bak-17-11-house` | versão de 17/11 | backup da UI antiga |

O único `agent-hub.mjs` ativo é o que está em `scripts/`. Os backups
ficam aqui para referência; não são carregados por nenhum serviço.

Se precisar restaurar um backup, copie de volta para `scripts/` e
reinicie o hub (sem `rm` — use `cp` para preservar o original).
