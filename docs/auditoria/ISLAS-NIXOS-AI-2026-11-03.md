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
caminhos.

**Medição A/B do eco (03/11, piper +3,5 dB = clipping proposital):**

| fonte | rms durante o TTS | rms no silêncio | STT (`bench-stt`, vad_on) |
|---|---|---|---|
| ALSA cru (o que o duplex usa hoje) | **0,030202** | 0,001809 | transcreve o TTS inteiro ("Jarvis, teste de cancelamento de ego…"), logprob -0,422 |
| `echo_cancel_source` (AEC3) | **0,000014** | 0,000028 | **texto vazio** (decode 102 ms vs 2.474 ms) |

⇒ **AEC3 atenuou 66,4 dB** e a transcrição fantasma desaparece. Bônus: sem
o TTS para transcrever, o STT gastou 102 ms em vez de 2.474 ms (CPU).

> ⚠️ **CORREÇÃO 03/11 16:00 — o número 66,4 dB é INVÁLIDO.** A medição
> comparava duas fontes em **instantes diferentes** e, pior, com o
> **default source do pipewire no Mic2 (Stereo Mic, MORTO)**. O AEC3
> captura do default source ⇒ o lado "AEC" media um mic quase morto
> (rms 0,000014), e o lado "ALSA" media o Mic1 (Digital) — a diferença
> era **o mic errado**, não cancelamento de eco.
>
> **Medição CORRETA (simultânea, default source = Mic1, tom 1 kHz nos
> alto-falantes):** ALSA cru rms **1282,7** (−28,1 dBFS) · AEC3 rms
> **132,1** (−47,9 dBFS) ⇒ atenuação real de **19,7 dB**, com correlação
> AEC/ALSA de **−0,198** (o tom residual está decorrelacionado = o eco
> foi de fato removido, não apenas escalado). **Fala real** (arquivo
> TTS tocado nos alto-falantes): ALSA rms 132,1 → AEC rms 32,1
> (−12,3 dB) e o STT do AEC devolve " E aí" em vez do eco inteiro.
>
> Conclusão: o AEC3 **funciona** (é um cancelador de eco de voz, não de
> tom puro — 20 dB num tom de 1 kHz é o comportamento esperado), mas o
> ganho real é **~12-20 dB**, não 66 dB. O default source correto é
> **essencial** (regra nova no WirePlumber, `nixos/modules/audio.nix`).

Nota honesta: com o TTS em volume normal o eco neste hardware fica perto
de -90 dB (portas de áudio do laptop) — o ganho aparece quando o
áudio é audível pelo mic (notebook com auto-falante + mic colado, ou
volume alto). E `vad_off` no caminho AEC vira alucinação pura
("Miki Javais Feral Jove…") — o VAD continua obrigatório no duplex.

### 1.6 A1 aplicado: duplex no AEC3+RNNoise (03/11, lane `voice-flags-en`)

`scripts/duplex-voice.py` gravava do **ALSA cru** → o TTS entrava no mic e o
STT transcrevia a própria voz. Agora grava de **`rnnoise_source`** (a cadeia
AEC3 → RNNoise do grafo do pipewire), com fallback para o ALSA cru se o nó
não existir (mesma disciplina do wakeword: mic mudo é pior que sem AEC).

```python
MIC_SOURCE_PREFERRED = "echo_cancel_source"  # AEC3 direto (o rnnoise_source
                                           # pode ficar sem link de entrada)
MIC_SOURCE_FALLBACK  = "alsa_input...HiFi__Mic1__source"
def mic_source() -> str: ...                 # resolve 1x, loga a escolha
```

**Medição própria (mesmo protocolo: wav de TTS de 19,6 s tocado nos
alto-falantes enquanto o mic grava, 7 s):**

| fonte | rms durante o TTS | rms no silêncio |
|---|---|---|
| ALSA cru (antes) | **0,049417** | 0,001832 |
| `rnnoise_source` (AEC3→RNNoise, agora) | **0,000000** | 0,000001 |
| `echo_cancel_source` (AEC3 direto, agora) | 123,4 | — |

CORRECAO (03/11 14:20, lane `voice-flags-en`): o rms **0,000000** do
`rnnoise_source` NAO era "cancelamento perfeito" — era **node morto**:
`pw-cli ls Link` mostra o `rnnoise_source` (id 47) **sem link de ENTRADA**
(so `echo_cancel_source` -> `capture.rnnoise_source` e ->198). Medicao do
`coord-naming` (13:45) + reconferida aqui: gravando agora, os tres nos
entregam audio (`echo_cancel_source` rms 123,4 · `rnnoise_source` 70,6 ·
`capture.rnnoise_source` 177,6) — o grafo do pipewire e **dinamico** (o
link nasce quando alguem consome o source). Ou seja: silencio no rms e
ARMADILHA ("parece cancelamento perfeito, e o node sem entrada").

O eco do TTS some (o STT volta a devolver texto vazio em vez de transcrever o
próprio TTS) e o near-end continua vivo: o **wakeword já grava desse mesmo
caminho** (com fallback) e continua detectando a voz — se o AEC matasse o
near-end, o wakeword já estaria cego.

Mudança: 1 constante + 1 resolvedor + 2 call sites (`mic_stream()` e o
`pw-record` do enrollment). `vad_off` continua desligado (no caminho AEC o
VAD vira alucinação).

---

## 2. Ilhas e hardcodes ainda abertos

| # | Item | Onde | Risco | Ação proposta |
|---|------|------|-------|---------------|
| A1 | ~~**Duplex fora do AEC**~~ RESOLVIDO 03/11 | `scripts/duplex-voice.py:139` agora grava de `echo_cancel_source` (AEC3) com fallback pro ALSA cru | ~~STT transcrevia o TTS~~ → eco cancelado (medido: −12 a −20 dB, STT devolve " E aí" em vez do eco) | **feito** (commit `0088287d`) + regra de default source no WirePlumber (`nixos/modules/audio.nix`) — sem ela o AEC3 captura o Mic2 MORTO |
| A1b | **ASR do duplex morria no boot (CUDA OOM)** — NOVO 03/11 16:00 | `whisper-server` era subir manual (setsid no `duplex-voice-run.sh`) | VRAM disputada: 4B-MTP 4582 MiB + embeddings 446 MiB → sobra < 800 MiB e o whisper precisa ~900 ⇒ **morre no boot ⇒ duplex surdo** ("falo com ele e nada") | **feito**: `modules/services/whisper-server.nix` (systemd, `before = llama-cpp-embeddings.service` p/ pegar VRAM primeiro) + `duplex-voice-run.sh` usa o serviço. Medido: GPU 198-341 ms/segmento (CPU: 10,4 s, inviável) |
| A1c | **Default source do pipewire = Mic2 (morto)** — NOVO 03/11 16:00 | runtime (`wpctl set-default 74`), não persistido | após reboot o AEC3 volta a capturar o Stereo Mic (rms 0,000257 vs 0,005585 do Digital) ⇒ duplex surdo de novo | **feito**: regra WirePlumber `10-default-source.rules` casa por `node.name` (índice muda entre boots) |
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
