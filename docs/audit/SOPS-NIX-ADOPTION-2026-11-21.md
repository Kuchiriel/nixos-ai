# sops-nix adotado no nitro-v15 (21/11)

Autorização: `d0010 = Sim` (decisão do dono).

## Configuração

- Flake: input `sops-nix` (`github:Mic92/sops-nix`, nixpkgs follows),
  módulo `sops-nix.nixosModules.sops` e `./modules/secrets.nix` **somente**
  no host `nitro-v15` (o lab não recebe segredos nem chave).
- Chave age privada: `/var/lib/sops-nix/key.txt`, root:root 600, **fora** do
  repo e do Nix Store. Recipient público em `.sops.yaml` (não é segredo).
- Arquivo `secrets/litellm-env.yaml` criptografado com sops a partir do
  `/etc/litellm.env` atual; 35 linhas `export ...` recoveráveis com a chave.
- `sops.secrets."litellm_env"` provisiona `/etc/litellm-sops.env`
  (symlink para `/run/secrets/litellm_env`, 600 root); o serviço litellm agora
  usa esse caminho. `litellm.service` depende de `sops-install-secrets.service`.

## Validação

- `nix flake lock` rc=0; `nixos-rebuild build` e `switch` rc=0.
- Runtime: `/etc/litellm-sops.env -> /run/secrets/litellm_env`, 600 root:root,
  35 linhas `export` no segredo descriptografado.
- Varredura da nova geração no `/nix/store` (12 alvos): **0** ocorrências de
  `OPENAI/GROQ/GEMINI/OPENROUTER/HF_*_KEY=`, `sk-dummy` ou `local-not-needed`.
- Hub `/api/state` 200, processos `opencode serve` vivos.

Nenhum valor de segredo foi impresso, registrado no bus ou commitado em
plain-text. O arquivo `/etc/litellm.env` antigo foi mantido (fora do Store),
apenas deixou de ser a fonte do serviço.
