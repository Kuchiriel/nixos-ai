# Interação com o SO pelo JARVIS — o que funciona e o que não (2026-10-02)

Diagnóstico feito one-shot, medido no host `nitro-v15` (Hyprland, Wayland).
Tudo aqui foi **medido**, não deduzido. Referência: `jarvis/core/gameinput.py`
(helper interno) e `jarvis/core/vision.py` (foco + opacidade na captura).

## A causa raiz que custou horas

**`ydotoold` estava no lugar errado, e falhava em silêncio.**

- `ydotool` procura o socket em `/run/user/1000/.ydotool_socket`
  (XDG_RUNTIME_DIR do usuário).
- O `ydotoold` havia sido iniciado via `sudo`, sem `XDG_RUNTIME_DIR`, e criava
  o socket em `/tmp/.ydotool_socket`.
- Resultado: **todo** comando `ydotool` falhava com `rc=0` e a mensagem
  `failed to connect socket`. Nenhum erro, nenhum clique, nenhuma tecla.

Sintoma enganoso: parecia que o jogo (OpenGL) ignorasse evento sintético.
Não ignorava — o evento nunca saiu.

**Correção:** rodar `ydotoold` como serviço do **usuário** (o grupo `uinput`
dá acesso a `/dev/uinput`; sudo é desnecessário), com o `XDG_RUNTIME_DIR`
certo. Declarativo em `home-manager/modules/services/ydotoold.nix`.
No instante em que o socket passou a existir, clique e tecla funcionaram.

## Backends: o que funciona

| backend | uso | status |
|---|---|---|
| `hyprctl dispatch movecursor` | posicionar mouse | ✅ compositor, confiável |
| `hyprctl dispatch focuswindow address:0x…` | focar janela | ✅ só por **address** |
| `ydotool click 0xC0` | clique | ✅ depois do fix do socket |
| `ydotool key 28:1 28:0` | Enter | ✅ idem |
| `ydotool type --delay 12 <texto>` | digitar | ✅ |
| `wtype` | digitar | ❌ **não digita nada** aqui |
| `wtype -k` | tecla | ❌ mesmo uinput quebrado |

`humanize.type` usava `wtype` char a char — trocado para `ydotool`
(fallback `wtype`).

## Foco de janela no Hyprland

`hyprctl dispatch focuswindow title:OTClient` → **`No such window found`**.
O OTClient tem **class vazio** e o title real é `OTClient - Redemption`;
no Hyprland o seletor por title é regex exato.

Correto: `hyprctl clients -j` → pegar `address` → `focuswindow address:0x…`.

**Esperar o foco CONFIRMAR antes de digitar.** Sem essa espera o keystroke
dispara com a janela ainda inativa e se perde. `gameinput._focus()` faz o
loop de confirmação (`activewindow`) antes de qualquer ação.

## Transparência atrapalha visão e OCR

O Hyprland deixa as janelas semitransparentes; o `grim` captura o **composto**,
então o OCR lia o terminal que estava por trás do jogo e a visão descrevia a
janela errada.

`jarvis_observe_screen` ganhou dois argumentos **genéricos**:
- `focus_window` (default true quando `mode=window`) — foca antes de capturar;
- `opaque` (default true) — aplica
  `windowrule = opaque/alpha 1, noblur 1, nofade 1, address:0x…`.

## Modelo de interação do OTClient (medido)

1. `Enter` → chat **ON** e o campo recebe foco.
2. Digita o texto.
3. `Enter` de novo → **envia**.
4. Para chat **OFF** (e religar WASD): clicar no botão `Chat Off`.

O `Enter` é **toggle**, nunca "enviar". Por isso existe `chat_state()` (lê o
rótulo do botão por OCR de um recorte) e `ensure_chat()` (idempotente):
**nunca mandar `Enter` avulso** — em 02/10 um Enter de teste desligou o chat e o
comando seguinte foi digitado num campo fechado, sem erro visível.

## O que AINDA não funciona

`!scanitens <regex>` **não chega ao servidor**. Diagnosticado até o limite:

- o texto **é digitado** no campo (OCR do campo mostra `!scanitens ore`);
- `Enter` é enviado;
- o talkaction **existe e está registrado** no container:
  `/canary/data-sandbox/scripts/talkactions/player/scanitens.lua`, com
  `TalkAction("!scanitens")`;
- o log do servidor não registra **nada** — nem o comando;
- este fork do OTClient **não tem `OTalkAction` no fonte** (`grep` em
  `modules/` e `src/` não acha a construção), ou seja o relay de `!` do chat
  para o servidor não está presente da forma esperada.

Ou seja: o caminho **teclado → client → servidor** está quebrado num elo
desconhecido dentro do client. **Mouse funciona** — e os verbos do jogo
(`Chop down`, `Till soil`, `Plant seed`) são acionados por **clique**, então o
ciclo de jogo não depende do chat. `scan` é só diagnóstico e fica de fora.

## Regras para não repetir

1. Antes de culpar o app, verificar se o **atuador** existe: `ydotool key`
   devolvendo `rc=0` **não** significa que funcionou.
2. `wtype` é suspeito por padrão neste host.
3. Foco = `address`, não `title`; e confirmar antes de agir.
4. Ação que alterna estado = ler estado antes, agir depois. Nada de `Enter`
   avulso.
5. Provar por OCR de **recorte pequeno** (o botão, o campo) em vez de
   reenviar a tela inteira — é mais barato e mais preciso.