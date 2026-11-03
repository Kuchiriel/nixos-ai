# Auditoria: ilhas e hardcodes no nixos-ai — 2026-11-03

Escopo: unificar o que está fragmentado (pacotes, CLI×MCP, voz, modelos) e
listar os hardcodes que ainda existem. Status por item: **RESOLVIDO** /
**ABERTO** / **PROPOSTA**.

Método: leitura do código + medição no host (gen 372), não opinião.
Comandos de evidência no fim.

---

## 1. Ilhas resolvidas nesta sessão

### 1.1 Pacote `jarvis` × `jarvis-voice` (RESOLVIDO)

O split existia para não arrastar `torch`/`ctranslate2` no pacote "base" —
mas **o `base` não tinha nenhum consumidor de runtime**: dev shell usava
só a lista de deps, e todos os consumidores reais (host, wakeword, MCP,
vscode) usavam a versão **com** voz.

Medido: `jarvis-voice` = 4,7 GiB de closure; `base` = 1,8 GiB; e o `base`
mesmo não era instalado em lugar nenhum. Resultado: dois pacotes, dois
conjuntos de closure, uma lista de "quem usa o quê" que ninguém mantinha.

→ **Um pacote** (`jarvis`, com a voz dentro). Consumidores atualizados:
`flake.nix` (outputs + dev shell), `hosts/nitro-v15/configuration.nix`,
`home-manager/modules/services/jarvis-wakeword.nix` (PATH),
`home-manager/modules/vscode-roo.nix` (binário do MCP),
`modules/ai/jarvis/jarvis-env.sh` + `jarvis-mcp-launcher.sh` (glob do store).

### 1.2 CLI/MCP sem as deps de voz (RESOLVIDO — era o bug mais grave)

O *console script* do pacote (`jarvis`) recebia as deps no `sys.path`
(o hook de python do nixpkgs injeta via `site.addsitedir`), mas a CLI e o
MCP rodam `python3 -m jarvis...` com `PYTHONPATH` — e aí:

```
$ jarvis speak ...
ERROR: falha no TTS: [Errno 2] No such file or directory:
  '/home/nixos/.local/share/kokoro/config.json'
```

Ou seja: **a CLI e o MCP não tinham `faster_whisper`, `kokoro` nem `torch`**
— o STT/TTS só funcionava pelo binário `jarvis` do store (outro caminho,
outro ambiente). Duas ilhas para a mesma voz.

→ `jarvis-env.sh` agora extrai a **mesma** lista de `site-packages` que o
console script embute e a exporta (`PYTHONPATH` + `NIX_PYTHONPATH`, o
segundo para processar `.pth`). Medido: 195 entradas; `import faster_whisper,
kokoro, torch` OK (1.2.1 / 2.11.0).

Descartado no caminho: `python.withPackages` (embute o python e duplica o
`wheel` no closure → build falha) e `makeSearchPathOutput` como
`propagatedBuildInputs` (envenena o `pythonPath` do hook → "build input …
does not exist").

### 1.3 Modelos de voz: symlinks podres (RESOLVIDO)

Os symlinks dos modelos (`~/.local/share/kokoro/*` e o snapshot do
`faster-whisper-small`) eram criados **pelo módulo do wakeword**, que está
**desabilitado desde 21/10**. Sem referência no closure do sistema, o GC
levou os store paths e os links viraram dangling:

```
BROKEN  ~/.local/share/kokoro/config.json
BROKEN  ~/.local/share/kokoro/kokoro-v1_0.pth
BROKEN  ~/.local/share/kokoro/voices/af_heart.pt
BROKEN  ~/.local/share/jarvis/voice/.../faster-whisper-small/.../model.bin
```

Efeito real: o TTS Kokoro caía no fallback (espeak = voz "horrível") e o
`jarvis stt` não tinha modelo. Medido depois do fix: Kokoro fala (WAV de
4,6 s, RTF 0,49 no STT) e o whisper transcreve em PT-BR sem erro.

→ Módulo novo `home-manager/modules/jarvis-models.nix` (sempre ligado):
referencia os modelos (closure) e religa os symlinks a cada activation.
O wakeword perdeu a cópia duplicada.

### 1.4 Cobertura CLI × MCP (RESOLVIDO — parcial)

O MCP expõe **37** tools; a CLI tinha ~20 atalhos e o resto era inacessível
por linha de comando.

→ `jarvis-cli.sh tools` (lista + buraco de cobertura), `jarvis-cli.sh tool
<nome> <json>` (dispatch genérico para qualquer tool), atalhos novos
`rehydrate` (a tool mais usada: 68 chamadas/7d) e `web-search`.
Cobertura: **24/37 nativas**, as 13 restantes via `tool`.

### 1.5 AEC3 antes do RNNoise (RESOLVIDO no PaperWire; não está no duplex)

O STT ouvia a própria voz do TTS no duplex (o gate por RMS não distingue
TTS de fala). Lógica do FluidVoice portada (AEC3 do WebRTC):

- `nixos/modules/audio.nix`: módulo `libpipewire-module-echo-cancel`
  (`library.name = aec/libspa-aec-webrtc`, `monitor.mode = true` → a
  referência far-end vem do **monitor do sink default**, então qualquer
  TTS que sai pelos alto-falantes é cancelado do mic — sem wrapper de
  `pw-play`);
- o RNNoise passou a capturar **de** `echo_cancel_source` (cadeia
  AEC → NS);
- o wakeword grava de `echo_cancel_source` com **fallback** para
  `rnnoise_source` (se o módulo não carregar, mic mudo é pior que sem AEC).

Medido: nós `echo_cancel_source` / `capture.echo_cancel_source` /
`rnnoise_source` existem após restart do pipewire; o áudio passa nos dois
caminhos (rms 0,0024). **O eco audível no mic é ~-90 dB neste hardware**
(portas de áudio do laptop), então o ganho do AEC aqui é pequeno — a
medição honesta é essa, não "AEC magic".

---

## 2. Ilhas e hardcodes ainda abertos

| # | Item | Onde | Risco | Ação proposta |
|---|------|------|-------|---------------|
| A1 | **Duplex fora do AEC** | `scripts/duplex-voice.py:128` grava do ALSA cru (`HiFi__Mic1__source`) | o eco do TTS entra no STT; a guarda é por estado (`TTS_SELF`), não por DSP | medir com `bench-stt` (piper + voz alta) e, se o eco passar de -40 dB, apontar o duplex para `rnnoise_source` |
| A2 | **TTS por contexto** | duplex usa **piper** (latência, RTF 0,033) ✓; `jarvis speak`/ack usam **kokoro** ✓ | piper não deve entrar no duplex (latência), kokoro não deve entrar no duplex | manter: piper = duplex, kokoro = resto (direção do dono, 03/11) |
| A3 | **IP do tailnet hardcoded** | `scripts/agent-msg.sh:59`, `scripts/agents-watcher.sh:170`, `home-manager/modules/services/opencode-serve.nix:10` | muda de tailnet → scripts quebram | ler de `tailscale ip -4` ou de um arquivo de estado do HM |
| A4 | **`/home/nixos` no código** | `cli/dev.py`, `cli/main.py`, `core/context_budget.py`, `core/laya_*.py`, `runtime/context.py` | não portável, quebra em outro usuário | `Path.home()` / env `JARVIS_HOME` |
| A5 | **Glob do pacote no env** | `modules/ai/jarvis/jarvis-env.sh:34` | depende do nome do pacote no store | o console script do pacote é a fonte de verdade (resolvido em 1.2); o glob fica só como fallback |
| A6 | **Portas 8080/8081/8082/6333** | `core/config.py:88-113` | já vêm do registry (`_registry_service_url`) ✓ | nada a fazer — só documentar que o registry é a fonte |
| A7 | **Mic como string** | `home.nix:744` e `duplex-voice.py:128` repetem o nome do device ALSA | renomear o device quebra os dois | variável única (HM → env do serviço) |
| A8 | **`AGENTS_QUEUE` default** | plugin `memory.js` / `jarvis-cli.sh` | fila errada → estado errado | manter o default, mas logar a fila usada |

---

## 3. O que NÃO foi feito (e por quê)

- **Não** mexi em `core/voice.py` (WIP do colega: porta 8092 → registry) —
 misturar o commit quebraria o HEAD.
- **Não** troquei o duplex para kokoro: piper é o TTS de baixa latência do
  duplex (RTF 0,033; kokoro é 1,7–2 s quente por frase).
- **Não** quebrei o pin de nixpkgs: gen 372 mantém kernel 7.2.9-zen1 +
  driver 615.71.09.

---

## 4. Evidência (comandos)

```bash
# cobertura CLI x MCP
bash scripts/jarvis-cli.sh tools

# deps de voz na CLI/MCP (o bug da ilha)
bash -c '. modules/ai/jarvis/jarvis-env.sh; $JARVIS_PY -c "import faster_whisper, kokoro, torch; print(faster_whisper.__version__, torch.__version__)"'
# -> 1.2.1 2.11.0

# links dos modelos (devem existir)
for f in ~/.local/share/kokoro/config.json ~/.local/share/kokoro/voices/pm_alex.pt; do [ -e "$f" ] && echo OK $f; done

# AEC presente
pw-cli list-objects Node | grep -E 'echo_cancel|rnnoise'

# STT medido (ASR_BENCH)
bash scripts/jarvis-cli.sh bench-stt <wav> --model small
```
