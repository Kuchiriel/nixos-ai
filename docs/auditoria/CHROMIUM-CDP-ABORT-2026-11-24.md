# O chromium-cdp aborta: 4 hipóteses já provadas (não repetir)

(24/11/2026, coord-naming) O `chromium-cdp` da casa (o Chromium 154 que o
`jarvis_browser` usa para ler páginas) **não sobe**: aborta com core-dump.
O sintoma exato:

```
[FATAL:dbus/bus.cc:1245] D-Bus connection was disconnected. Aborting.
[ERROR:third_party/crashpad/crashpad/util/process/process_memory_range.cc:75] read out of range
```

## O que já foi provado (4 experimentos, com o Chromium real do store)

| hipótese | teste | resultado |
|---|---|---|
| falta a `libstdc++.so.6` | `LD_LIBRARY_PATH` resolvido pelo `asrd_env.py` | **não era a causa** (o erro muda de mensagem, mas o abort continua) |
| falta a sessão D-Bus | `dbus-run-session -- chromium ...` | **não sobe** (o mesmo abort) |
| falta `DBUS_SESSION_BUS_ADDRESS` | exportado à mão (`unix:path=/run/user/1000/bus`, que é o valor real do `systemctl --user show-environment`) | **não sobe** (o mesmo abort) |
| falta `XDG_RUNTIME_DIR` / falta GPU | os dois exportados + `--disable-gpu` | **não sobe** (o mesmo abort) |
| o **sandbox setuid** do Chromium não existe | o wrapper do Nix aponta `CHROME_DEVEL_SANDBOX=/run/wrappers/bin/__chromium-suid-sandbox`, e esse diretório **não tem nenhum helper do Chromium** (medido: `ls /run/wrappers/bin/ | grep -c chromium` = **0**) | `--no-sandbox` no comando | **não sobe** (o mesmo abort) |

Ou seja: **o abort não é de ambiente**. Com o bus certo, com o
`XDG_RUNTIME_DIR` certo, sem GPU e sem sandbox, o Chromium 154 aborta igual
⇒ a hipótese que sobra é o **build do Nix** (o binário em
`/nix/store/s8l73vx0mmvmdarhx2i893iysdiklqh7-chromium-154.0.8037.97`).

**Achado de meio caminho (24/11):** o wrapper do Nix tenta usar
`CHROME_DEVEL_SANDBOX=/run/wrappers/bin/__chromium-suid-sandbox`, e
**`/run/wrappers/bin/` não tem nenhum helper do Chromium** (medido: 0
ocorrências). Não é a causa do abort (o `--no-sandbox` também falha), mas
é a evidência de que **os wrappers do Nix estão incompletos neste host** —
o que é da lane da config do host (`hosts/nitro-v15/configuration.nix`),
não da minha.

## O comando real (medido)

```
/nix/store/.../chromium-154.0.8037.97/bin/chromium \
  --remote-debugging-port=9223 \
  --user-data-dir=/home/nixos/.config/jarvis-chromium \
  --no-first-run --no-default-browser-check \
  --headless=new https://fish.audio/pt/app/
```

## Impacto na casa

- **A trilha do dono não depende do Chromium** (clipboard + OCR da janela +
  voz), então ela segue funcionando com o browser quebrado.
- O `jarvis_browser` (leitura de página) **não funciona** até isso ser
  consertado — e a config é do **host** (`hosts/nitro-v15/configuration.nix`),
  então o conserto é da lane dela.
- **Como testar rápido** (sem esperar o conserto):
  `CH=$(systemctl --user cat chromium-cdp.service | grep -oE "/nix/store/[^ ]*chromium-[^ ]*/bin/chromium" | head -1)` e rodar o comando acima numa porta livre.

## O que falta (a próxima hypothesis testável)

O build do Chromium precisa do **helper setuid do sandbox**
(`__chromium-suid-sandbox`) em `/run/wrappers/bin/` — ele não está lá. As
hipóteses que sobram, em ordem de teste:

1. o pacote do Chromium no nixpkgs foi empacotado **sem** o
   `chrome-suid-sandbox` (o wrapper referencia um helper que o build não
   instalou): rebuild do pacote, ou overlay do `makeWrapper` que não recria
   o helper;
2. o helper existe em outro prefixo do store (procurar
   `ls /nix/store/*chromium*/lib/ | grep -i suid`) e o wrapper aponta para
   o path errado.

Checar o helper antes de qualquer coisa:

```bash
ls /run/wrappers/bin/ | grep -i chromium        # esperado: 1 helper
ls /nix/store/*chromium*/lib/ 2>/dev/null | grep -i suid
```
