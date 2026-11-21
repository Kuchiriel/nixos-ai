# Remoção dos literais de api_key (21/11)

## Escopo e honestidade

A tarefa pedia migração para **agenix/sops**. Medição prévia mostrou que
**não existe infraestrutura agenix/sops neste repositório**: nenhum input no
`flake.nix`, nenhum binário, nenhuma referência `age.secrets`/`sops.secrets` e
nenhuma chave de age em `~/.config/sops/age/`. A afirmação anterior no
`SECRETS-AUDIT-2026-11-20.md` ("agenix/sops já usados em nv-gate/rclone") era
**falsa** — os matches eram palavras "env" em comentários de sync. Corrigida.

Introduzir agenix exigiria chave do dono, novo input do flake e arquivos de
segredo — decisão arquitetural que não foi tomada aqui.

## O que foi feito (sem valor literal no Store)

| ponto | antes | depois |
|---|---|---|
| `home.nix:876` (`.aider.conf.yml`) | `openai-api-key: "sk-dummy"` | linha removida; o aider lê `OPENAI_API_KEY` do ambiente |
| `litellm-cascade.nix:32` | `api_key = "local-not-needed"` | `os.environ/OPENAI_API_KEY` |
| `:39`, `:47`, `:55` | já `os.environ/GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` | inalteradas (já eram referências) |

`OPENAI_API_KEY` existe em `/etc/litellm.env` (environmentFile do serviço,
fora do repo e do Store). Os três outros também.

## Segurança adicional

`/etc/litellm.env` estava **644** (root:root, world-readable) apesar de o
módulo documentar `chmod 600`. Permissão corrigida para **600**.

## Validação

- `nixos-rebuild build --flake .#nitro-v15` rc=0 (com snapshot/restore do
  índice Git); `switch` rc=0 (autorizado nesta tarefa).
- Novo `home-manager-files` (`l0x7298fa…`, 144 alvos únicos após resolver
  symlinks): **0 ocorrências** de `sk-dummy`/`local-not-needed`;
  `.aider.conf.yml` gerado sem linha `openai-api-key`.
- Estado vivo: `/etc/litellm.env` 600, hub `/api/state` 200, processos
  `opencode serve` vivos (nenhum restart explícito), `git staged=0`.
- Nenhum valor de chave foi lido, impresso ou registrado. Nenhum histórico
  Git reescrito e nenhuma credencial rotacionada.
