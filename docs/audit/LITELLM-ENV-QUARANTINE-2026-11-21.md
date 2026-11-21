# Quarentena do `/etc/litellm.env` (21/11)

Após a adoção do sops-nix, o arquivo plain-text antigo ainda era lido por 17
arquivos ativos (`keys.py`, `webui/api.py`, launchers, `keys-wrapper.sh`,
`keys.env`, serviços). Antes de movê-lo, todos os consumidores foram migrados
para `/etc/litellm-sops.env` (49 substituições) e o sistema foi buildado e
aplicado com `nixos-rebuild switch` rc=0.

## Quarentena

- Origem: `/etc/litellm.env`, 4031 bytes, sha256 `a97657d631b881…`, mtime
  2026-11-08 08:58:55 -0300.
- Destino: `/var/backups/quarentena-litellm-20261121/litellm.env.pre-sops-20261121`,
  600 root:root.
- Manifesto: `/var/backups/quarentena-litellm-20261121/MANIFEST.json` (600),
  com caminho, sha, tamanho, mtime, motivo e comando de restauração.
- **Nada apagado**: sha conferido antes/depois (`SHA_OK`); arquivo original
  não existe mais em `/etc`.

## Validação pós-movimento

- 35 linhas `export` no segredo descriptografado e 35 em `~/.config/opencode/keys.env`.
- `keys-wrapper.sh` aponta para o segredo sops.
- Hub `/api/state` 200, `opencode-serve.service` active, 4 processos opencode.
- Nenhuma referência a `/etc/litellm.env` na nova geração do NixOS.

## Bloqueio de push (fora do escopo desta mudança)

O push de `b4905899` foi rejeitado pelo GitHub Push Protection: há **Resend
API Keys** em commits antigos (`f49d66a`, `f7eb040`), em
`docs/sessions/ses_f3151b…md` e `ses_f0d36…md`. São 6 detecções em histórico
prévio — o diff do commit `b4905899` tem **0** marcadores `re_…`/`sk-…`.
Não reescrevi histórico nem usei o link de unblock (§10.4): isso exige
decisão do dono. Commit permanece local até a intervenção.
