# Calibração de Áudio do Legado (Manjaro → NixOS)

> Conhecimento recuperado do snapshot Manjaro (`/mnt/manjaro/kuchiriel/Projects/AI_SYSTEM/`).
> Estas tunagens foram calibradas empiricamente num notebook com ventoinha + sons de casa
> (chuva, TV, ventilador de teto) — **deu muito trabalho acertar**. Preservar.

## O problema

O wakeword (openwakeword) ativava sozinho OU nunca ativava, e o STT transcrevia errado.
Causas raiz (na ordem em que foram descobertas):

1. **RNNoise no PipeWire foi tentado e DESATIVADO no legado** — o plugin LADSPA
   (`librnnoise_ladspa.so`, do projeto werman/noise-suppression-for-voice) **não existia**
   no Arch (`setup-pipewire-denoise.sh` criava a config, mas o plugin faltava).
   **Resolvido no NixOS**: o nixpkgs empacota o plugin como `rnnoise-plugin`
   (1.10) — o módulo `nixos/modules/audio.nix` agora cria o source virtual
   `rnnoise_source` (filter-chain LADSPA com VAD threshold 50%, grace 200ms)
   via `services.pipewire.extraConfig` — 100% declarativo, o plugin vive no store.
   No host final, wakeword/STT podem apontar para `rnnoise_source` em vez do
   device cru (lembrando: o wakeword do lab usa `arecord hw:X,Y` — o denoise do
   PipeWire só entra se o wakeword capturar do source virtual).
2. **O wakeword precisava de calibração própria** — thresholds e gates, não denoise externo.
3. **O VAD do STT cortava palavras** (silence timeout curto demais).

## Parâmetros calibrados (valores finais que funcionaram)

### Wakeword (openwakeword, modelo `hey_jarvis_v0.1.onnx`)
| Parâmetro | Valor final | Evolução | Notas |
|---|---|---|---|
| Score threshold | **0.85** | 0.05 → 0.15 → 0.30 → 0.70 → 0.75 → 0.65 → 0.85 | Scores reais ~0.002–0.05; threshold alto = menos false positives |
| Trigger cooldown | **5.0s** | — | Lockout anti-loop após trigger |
| RMS gate | **2093** | — | Filtro de ruído ambiente (mais tarde desabilitado — gate por RMS relativo ao pico funcionou melhor) |
| Silence detection | **40% drop do pico RMS por 1.0s** | — | "Adaptive VAD": `silence_threshold = max_rms_seen * 0.6` |
| Captura máx | **12s** | — | Limite de segurança da gravação |
| Sample rate | **16000 Hz** | — | `arecord -D hw:1,7 -f S16_LE -r 16000 -c 2` (device ALSA raw, bypass PyAudio) |
| Normalização | `(mono - mean) * 10.0` clip | — | DC removal + ganho fixo antes do `oww.predict()` |

### VAD / STT (faster-whisper)
| Parâmetro | Valor final | Notas |
|---|---|---|
| `min_silence` | **600ms** | (era 300ms) — parar gravação mais rápido |
| `speech_pad_ms` | **300–400ms** | 400ms evita cortar fins de palavras |
| Silence timeout pós-trigger | **4.0s** | **CRITICAL FIX**: TTS demorava 2–3s para falar o comando; com 1.8s o sistema cortava a gravação antes |

### Noise profile (ambiente de referência)
- RMS avg **2539**, P95 **3181** (ventoinha PC + plataforma + teto + TV + chuva)
- Mic com ganho baixo (-46dB) precisou **boost 150% via pactl**
- `profile_audio_noise.py` (10s, device 12, 48kHz) gera `noise.prof` para calibrar gates

## Fluxo completo (como ficou funcionando)

```
daemon → arecord hw:1,7 @16k → mono mix (L+R)/2 → normalize → oww.predict()
  → score > 0.85 E cooldown 5s OK
    → kill TTS/audiobook (pkill paplay/aplay/enhanced_audiobook.py)
    → beep + notify "Escutando comando..."
    → status waybar: listening → processing
    → grava até 12s, parando após 1.0s de silêncio relativo (40% drop do pico)
    → salva /tmp/jarvis_cmd_<ts>.wav → brain process (STT → LLM → TTS)
    → restart arecord, status idle
```

## Porta NixOS (declarativa)

- `home-manager/modules/services/jarvis-wakeword.nix` — opções:
  `threshold` (default 0.85), `device` (default `hw:1,7`), `rate`, `cooldownSeconds`,
  `maxRecordSeconds`, `silenceDrop` (default 0.6), `rmsGate` (opcional),
  `killTTSOnTrigger` (default true).
- RNNoise: **resolvido** — `rnnoise-plugin` (1.10) do nixpkgs + filter-chain no
  `nixos/modules/audio.nix` (source virtual `rnnoise_source`). Alternativa leve
  ao easyeffects (mais pesado, não é necessário para denoise do wakeword).
- VAD do STT: quando o STT entrar (Fase 8), usar `min_silence=600ms`, `speech_pad_ms=400ms`.

## Lições

- **Denoise no PipeWire ≠ solução mágica**: sem o plugin, o wakeword calibrado (threshold +
  cooldown + silence adaptativo) resolveu sozinho. A cadeia inteira é mais robusta que
  qualquer filtro externo.
- **Silence relativo ao pico** (não absoluto) funciona melhor que gate fixo: adapta ao volume
  da voz vs. ruído ambiente em tempo real.
- **O cooldown de 5s é essencial**: sem ele, o próprio beep de confirmação re-triggerava o wakeword.
