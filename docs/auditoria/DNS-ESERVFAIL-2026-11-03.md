# DNS SERVFAIL (ESERVFAIL) em `integrate.api.nvidia.com` — 2026-11-03

Sintoma na outra agente (sessão opencode): `getaddrinfo ESERVFAIL integrate.api.nvidia.com
[retrying in 8s attempt #5]` → a chamada do provider `nvidia` (catálogo em
`integrate.api.nvidia.com/v1/models`) morre depois do backoff do opencode.

## Diagnóstico (não é a NVIDIA)

Cadeia real do DNS desta box:

```
glibc → /etc/resolv.conf → 100.100.100.100 (MagicDNS do Tailscale)
      → tailscaled forwarder → 181.213.132.2 / 181.213.132.3  ← resolver do ISP (NetworkManager/DHCP)
      → root
```

Evidências:

1. `/etc/resolv.conf` é **sobrescrito** pelo Tailscale (modo `resolvconf-overwrite`) e
   contém **só** os servidores do MagicDNS (`100.100.100.100` + `fd7a:115c:a1e0::53`).
2. `resolvconf -l` mostra três entradas: NetworkManager (181.213.132.2/3 — **do roteador**),
   `static` (8.8.8.8/1.1.1.1) e `tailscale`. O cliente nunca vê a estática porque o
   Tailscale sobrescreve o arquivo final.
3. `journalctl -u tailscaled` às 01:06:
   `dns: resolver: forward: forwarder.send("181.213.132.3"): successfully retried via TCP`
   repetido + `[RATELIMIT] format("dns: resolver: forward: ...")` → o forwarder do
   Tailscale estava tropeçando no resolver do ISP (UDP truncado → retry em TCP) e o
   próprio log entrou em rate-limit. O SERVFAIL chega ao cliente como `ESERVFAIL`.
4. `networking.nameservers = ["8.8.8.8" "1.1.1.1"]` **já existia** em
   `hosts/nitro-v15/configuration.nix:276` → mas, por causa do item 2, esses resolvers
   **nunca entraram no caminho** (o Tailscale usava os do ISP como upstream).
5. No momento do diagnóstico a resolução estava normal (0/20 falhas, 65 ms) → o
   problema é **intermitente**, e some sozinho.

## Correção aplicada

O `tailscale set --override-dns` **não existe** no Tailscale 1.104.4 (só `--accept-dns`);
o override do DNS é ajuste do painel admin da tailnet. O caminho equivalente, e mais
simples, é **tirar o resolver do ISP do caminho**:

```bash
nmcli con mod "CasaMargareth-IoT" ipv4.ignore-auto-dns true ipv4.dns "1.1.1.1,8.8.8.8"
```

Aplicado e **salvo** na conexão (verificado: `ipv4.dns=1.1.1.1,8.8.8.8`,
`ipv4.ignore-auto-dns=yes`). Efeito: a entrada do NetworkManager em `resolvconf -l` passa
a ser 1.1.1.1/8.8.8.8 → o `tailscaled` reencaminha nomes públicos para Cloudflare/Google
em vez do resolver do ISP → os nomes do tailnet (`*.ts.net`) continuam no MagicDNS.

> Observação: o perfil Wi-Fi é **ad-hoc** do NetworkManager (tem PSK) → importá-lo para
> Nix exigiria o segredo no repositório. Por isso a mudança é via `nmcli` (persistida no
> armazenamento do NM), não declarativa no `configuration.nix`. Para torná-la
> declarativa sem segredo, o caminho é um oneshot NixOS que roda o mesmo `nmcli`
> (idempotente) na ativação.

## Como evitar recorrência (se voltar)

1. `journalctl -u tailscaled | grep forwarder` → se aparecer `181.213.132.x` de novo, o
   forwarder voltou ao resolver do ISP (reaplicar o `nmcli` + reiniciar o `tailscaled`).
2. `resolvectl` não serve aqui (systemd-resolved está **inativo**); o diagnóstico é
   `resolvconf -l`.
3. Alternativa mais forte: **painel admin da tailnet → DNS → Override local DNS =
   1.1.1.1 / 8.8.8.8** (o CLI desta versão não expõe).
4. Reduzir o gatilho: o provider `nvidia` do opencode busca o catálogo em
   `integrate.api.nvidia.com/v1/models`; os 3 models já estão declarados na config
   (com `limit`), então a busca é enriquecimento — mas a falha dela ainda mata a
   chamada da tool.

## Efeito colateral descoberto no mesmo momento

O `nix flake update` (nixpkgs novo) trouxe o driver NVIDIA **615.78.08**, mas o kernel
em execução continuava **7.2.9-zen1** com o módulo antigo carregado →

```
Failed to initialize NVML: Driver/library version mismatch
NVML library version: 615.78
```

→ `nvidia-smi` quebrado → o `llama-vram-guard` (ExecStartPre do 4B, exige 4200 MiB)
morre com `[: Failed to initialize NVML ...: integer expected` → **`llama-uncensored-4b`
(:8092) não sobe**. O sistema novo já traz o kernel **7.2.14-zen1** → **reboot** resolve
(kernel + driver + DNS de uma vez).
