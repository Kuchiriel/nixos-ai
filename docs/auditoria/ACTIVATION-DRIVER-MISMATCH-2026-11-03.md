# Driver/library mismatch na activation (2026-11-03) — runbook de recuperação

## Sintoma

`./rebuild-host.sh` **constroi** certo e **falha na activation**:

```
Error:
   0: Activation (test) failed
   1: Activating configuration (exit status ExitStatus(Exited(4)))
      ...
      the following new units were started: docker.service
      warning: the following units failed: nvidia-container-toolkit-cdi-generator.service
```

Depois da falha:

```
$ nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader
Failed to initialize NVML: Driver/library version mismatch
NVML library version: 615.78
$ cat /proc/driver/nvidia/version
NVRM version: NVIDIA UNIX x86_64 Kernel Module  615.71.09
```

Efeito cascata: `llama-vram-guard` (ExecStartPre) nao consegue ler a VRAM -> o
`llama-uncensored-4b` fica preso em `activating` -> **o LLM default fica fora**
(o guard exige ~4.2 GB livres). O `llama-cpp-server` (router :8080) continua de pe.

## Causa

O `nix flake update` (commit `f8b864f0`) trouxe nixpkgs novo, que atualizou o
driver NVIDIA **userspace** para 615.78 e o kernel para 7.2.14. O modulo do
kernel em execucao continua sendo o do boot anterior (615.71.09, kernel 7.2.9).
A generation nova so e coerente **depois de um reboot** (modulo 615.78 + kernel
7.2.14 juntos); ate la, userspace e modulo nao casam.

A activation faz um "test" que ja reinicia unidades e aplica o home-manager de
verdade -> o host fica com as libs novas (615.78) e o modulo antigo (615.71),
mesmo com a activation reportando erro. Por isso o host fica degradado
**mesmo apos o erro**, e nao volta sozinho.

## Recuperacao sem reboot (o que foi feito em 03/11)

1. Descobrir a generation boa (a anterior, com as libs que casam com o modulo):

   ```bash
   readlink -f /nix/var/nix/profiles/system-366-link
   # /nix/store/2rk93g7c8c66v4qdp381p69i1gcd7wz8-nixos-system-nitro-v15-...
   ```

2. Ativar o closure antigo **direto** (sem rebuild, sem eval do flake):

   ```bash
   GEN366=$(readlink -f /nix/var/nix/profiles/system-366-link)
   sudo "$GEN366"/bin/switch-to-configuration switch
   ```

   Isso repõe as libs antigas (615.71 == modulo em execucao) -> `nvidia-smi`
   volta, o vram-guard passa, o 4B sobe.

   Armadilhas nesse caminho:
   - `nh os rollback` falha com **"Current generation not found"** (ele nao
     acha a generation corrente depois de uma activation abortada).
   - `nixos-rebuild switch --profile <link>` **nao existe** nesta versao
     ("unrecognized arguments"). O flag que existe e `--store-path`, mas ele
     re-avalia o flake e falha com `file 'nixos-config' was not found in the Nix
     search path`.
   - O script de ativacao dentro do closure chama-se `switch-to-configuration`
     (nao `switch-system-configuration`).

3. Deixar a generation nova como **boot default** (sem ativar — ativar agora
   quebraria o NVML de novo):

   ```bash
   cd ~/projects/nixos-ai
   nh os boot "$HOME/projects/nixos-ai" -H nitro-v15
   # -> "Adding configuration to bootloader"; boot default = generation nova
   ```

   Daí o proximo reboot do dono entra na generation nova (kernel 7.2.14 +
   driver 615.78, casados) e o NVML funciona de primeira.

4. Conferir:

   ```bash
   nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader
   systemctl is-active llama-uncensored-4b llama-cpp-server
   curl -sf http://127.0.0.1:8092/health && echo "4B ok"
   readlink -f /run/current-system   # generation em execucao
   readlink -f /nix/var/nix/profiles/system  # generation de boot
   ```

## Regra para o futuro

- `nix flake update` que mexe no driver NVIDIA exige **reboot planejado** antes
  do proximo `./rebuild-host.sh` (ou Immediately depois dele, sem medir nada
  no meio).
- Se a activation falhar com `nvidia-container-toolkit-cdi-generator.service`,
  **nao** insistir em rebuild: e mismatch de driver, nao erro de configuracao.
- Depois de ativar a generation nova, o `nvidia-smi` so volta a funcionar com o
  reboot; ate la, medir VRAM e subir servicos que dependem do guard e futile.

## Nota sobre `rebuild-host.sh`

O script faz `git add -A` + commit automatico `chore: update N file(s)` (IMP-018,
porque o flake so ve o indice git). Por isso um rebuild pode "roubar" arquivos
nao commitados de outro agente — revisar `git show HEAD` depois de cada rebuild.
