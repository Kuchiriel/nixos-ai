# VOICE PIPELINE — Auditoria Forense 2026-09-07

> Evidência: código + execução + comportamento observado. Doc ≠ prova.

## 1. Arquitetura encontrada (código real)

```text
pw-record --target <device> --rate 16000 --channels 2 (stereo s16)
 → VAD RMS adaptativo (home-manager/modules/services/jarvis-wakeword.nix:366-418)
    onset: 3/5 chunks acima de baseline*1.6 (mín 400)
    fim: RMS < baseline*1.1 por 2.5s (mín 1s gravado) ou MAX_RECORD=12s
 → WAV stereo 16k /tmp/jarvis_cmd_<ts>.wav (pre-roll 15 chunks ~770ms)
 → ww_scorer.py offline (mel→embedding→hey_jarvis ONNX, threshold 0.5)
 → ack TTS cacheado → `jarvis voice <wav>`
 → subprocess `jarvis stt` (isola CTranslate2×torch) → faster-whisper + vad_filter
 → router → Kokoro speak() → pw-play → /tmp/jarvis-status.json
```

OpenWakeWord streaming (`Model.predict`) **não existe mais** no daemon —
fallback VAD+RMS + scorer offline (comentário `jarvis-wakeword.nix:206-209`).

## 2. Fluxo real por fronteira

| Fronteira | Input | Output | Timeout/Estado | Feedback |
|---|---|---|---|---|
| WAKEWORD (VAD RMS) | mic stream 16k stereo | onset fala | cooldown 5s | `listening` no JSON direto |
| CAPTURE | chunks 512 frames | WAV stereo /tmp | max 12s, fim 2.5s silêncio | `transcribing` |
| SCORER | WAV | score wakeword | 60s timeout | rejeita → `idle` |
| STT | WAV via `jarvis stt` subprocess | texto | 60s timeout | `transcribing` via feedback.py |
| AGENT | texto | resposta dict | — | `thinking` |
| TTS | texto | WAV 24kHz + playback | 30s/play | `speaking` → `done` |

## 3. Dispositivos de áudio (medido 2026-09-07)

* `wpctl status`: `rnnoise_source` existe e é `* DEFAULT` (48kHz, filter-chain LADSPA).
* `home.nix:495` fixa `alsa_input...Mic1__source` físico — **bypassa o denoise**.
* Módulo default = `rnnoise_source`. Sem `hw:*` hardcoded atual (só no doc legado).

## 4. Configuração atual

* STT: `STT_MODEL_DEFAULT="tiny"` (`voice.py:29`, CLI `main.py:916,932`).
  `models.nix` só declara `whisper-small`. Divergência tiny×small.
* VAD STT: `threshold=0.5, min_speech=250ms, min_silence=1000ms, pad=400ms`.
* Scorer: `WW_THRESHOLD` default 0.5; opções `threshold`/`rmsGate` do módulo
  **mortas** (nunca lidas pelo daemon) — `home.nix` seta `threshold=0.25`
  sem efeito.
* Waybar: polling `interval=2` (`waybar.nix:321`), não event-driven.
  Estado `processing` do daemon sem ícone em `feedback.py` (fallback genérico).

## 5. Problemas reproduzidos (comandos + resultados)

```text
VERIFIED:
command: jarvis stt --model tiny --language pt /tmp/opencode/rvc-in-10s.wav
result: transcreve PT-BR em ~12s (cold start incluído)
evidence: "Você já consideraram um paradoxo do observador quântico? ..."

VERIFIED:
command: pausa de 2s inserida no meio do WAV → jarvis stt tiny
result: saída byte-idêntica (diff IDENTICAL, 174 chars)
evidence: /tmp/txt-nopause.txt vs /tmp/txt-pause.txt
conclusão: VAD interno NÃO corta em pausa — hipótese STT-corta REJEITADA p/ áudio limpo

VERIFIED:
command: jarvis stt --model small --language pt /tmp/ww-test-16k.wav
result: ~15s, gramática correta "Vocês já consideraram o paradoxo"
evidence: tiny erra ("Você já consideraram um paradoxo"); small acerta
conclusão: small > tiny p/ PT-BR, custo +3s

VERIFIED:
command: ww_scorer.py --wav 48kHz
result: ValueError: need 16 kHz, got 48000
evidence: ww_scorer.py:35 exige 16k, sem resample
conclusão: scorer frágil a qualquer mudança de rate

VERIFIED:
command: ww_scorer.py --wav /tmp/ww-test-16k.wav (voz Jarvis, sem "hey jarvis")
result: score=0.0001 < 0.5 → rejeitado corretamente
evidence: true-negative do verificador offline
```

## 6. Root causes

| # | Componente | Root cause | Confiança |
|---|---|---|---|
| 1 | STT modelo | código carrega `tiny`, fonte de verdade declara `small`; tiny pior em PT-BR | VERIFIED → corrigido E2 |
| 2 | Scorer | exige 16k sem resample; quebra em qualquer WAV 48k/40k | VERIFIED → corrigido E2 |
| 3 | Captura | `MAX_RECORD=12s` corta frase longa; `rms<50: continue` descarta onset suave; restart do `pw-record` perde fala contínua; kill-TTS mata `paplay/aplay` mas playback real é `pw-play` | HYPOTHESIS (precisa mic→WAV real) |
| 4 | Opções mortas | `threshold`/`rmsGate` setados em `home.nix`, nunca lidos | VERIFIED → corrigido E4 |
| 5 | Feedback | polling 2s; `processing` sem ícone; EventBus `VOICE_*` nunca publicado (só `voice.tts`) | VERIFIED → corrigido E4 (parcial; EventBus completo fica p/ próxima) |
| 6 | Testes | `test_wakeword.py` testa cópia da lógica, não o daemon; sem fixture de áudio real | PARTIAL |

## 7. Mudanças realizadas (FASE E)

* **E2**: `STT_MODEL_DEFAULT` tiny→small (`voice.py`, `cli/main.py` ×2);
  `home-manager/.../jarvis-wakeword.nix` pré-baixa `small` em vez de `tiny`;
  `ww_scorer.load_mono16k` com resample linear 48k/44.1k/40k/32k→16k + downmix.
* **E3**: `jarvis voice --debug-wav DIR` e `jarvis stt --debug-wav DIR`:
  salva WAV de diagnóstico + `session.json` (timestamps, durações,
  tamanhos, RMS/peak, texto, modelo) — sem conteúdo sensível além do
  necessário p/ debug local.
* **E4**: `feedback.py`: mapa `processing` (+`boot` alias de `initializing`);
  daemon usa estados do contrato (`processing` em vez de texto livre);
  `killTTSOnTrigger` inclui `pw-play`; opções `threshold`/`rmsGate`
  removidas (mortas) — threshold canônico é `wakeThreshold`.

## 8. Decisão Whisper/faster-whisper

**Mantido faster-whisper** (CTranslate2, CPU int8): transcreve PT-BR local,
lida com pausa de 2s sem perda, sem VRAM da LLM. Sem evidência p/ trocar
por whisper.cpp/transformers — troca sem métrica é proibida pela missão.

## 9. Parâmetros STT escolhidos

`device=cpu, compute_type=int8, beam_size=3, language=pt (quando LANG=pt),
vad_filter=True, threshold=0.5, min_speech=250ms, min_silence=1000ms,
speech_pad=400ms`, modelo `small`. Justificativa: VAD calibrado do legado
+ teste de pausa IDENTICAL + small vence tiny em PT-BR por +3s.

## 10. VAD / endpointing

Externo (captura): RMS adaptativo + pre-roll 770ms + fim 2.5s silêncio +
teto 12s. Interno (STT): faster-whisper VAD acima. Duplo VAD mantido por
ora — o interno provou-se seguro em pausa; o externo precisa de teste
mic→WAV real (BLOCKED sem sessão de voz física).

## 11. Feedback

Waybar polling 2s mantido (contrato mínimo); estados unificados
`idle/listening/transcribing/thinking/speaking/processing/error/done`;
`processing` agora tem ícone; kill-TTS cobre `pw-play`. EventBus `VOICE_*`
completo (session/wakeword/capture/stt) fica como follow-up — só `voice.tts`
publicado hoje.

## 12. Métricas antes/depois

| Métrica | Antes | Depois | Evidência |
|---|---|---|---|
| STT tiny 10s PT-BR | ~12s, gramática errada | — | /tmp/txt-nopause.txt |
| STT small 10s PT-BR | ~15s, gramática correta | default agora | run 2026-09-07 |
| Pausa 2s | sem perda (ambos) | sem perda | diff IDENTICAL |
| Scorer 48kHz | ValueError | resample+score | código E2 |

## 13. Testes executados

* `jarvis stt` tiny/small/pause/scorer — VERIFIED acima.
* `test_voice.py` (store pytest, sem `nix develop` que congela aqui):
  `3 failed, 10 passed` — as 3 falhas são **pré-existentes** (baseline com
  `git stash`: `3 failed, 9 passed`): 2× `voice_loop` mockam `transcribe()`
  mas o código chama `jarvis stt` via subprocess; 1× `speak` exige numpy
  (ausente fora do dev shell). Correção minha: fake de
  `test_main_voice_passes_model_to_pipeline` aceita `debug_wav`; novo teste
  `test_main_stt_debug_wav_writes_session` passa.
* `test_wakeword.py`: 3 falhas só por falta de numpy no shell atual
  (lógica do daemon intocada); 37 passam.
* `nix-instantiate --parse` nos 2 `.nix` editados: OK.
  `nix flake check`: BLOCKED (erro pré-existente `base16-schemes ... not valid`,
  sem relação com voz).
* E2E mic→wakeword→capture→STT — BLOCKED (exige sessão física com microfone).

## 14. Limitações restantes

* Sem controle positivo do scorer ("hey jarvis" real nunca testado).
* `MAX_RECORD=12s` ainda pode cortar monólogo; endpointing adaptativo real
  (pausa curta vs longa) não implementado — só documentado como alvo.
* EventBus de voz completo não implementado.

## 15. Sessão ao vivo 2026-09-07 (mic real, com ruído de fundo)

```text
VERIFIED (logs do daemon + STT):
- baseline RMS travada em 38 (ruído real ~250) → fim-por-silêncio
  (baseline*1.1=42) inalcançável → TODAS as capturas estouraram em 12s.
- "hey jarvis" real (score 0.9958) transcrito como "A e charles. A e charles."
  (janela 12s diluída + modelo tiny do build antigo) → TTS de 58KB (~1s).
- self-trigger 09:36:11 (score 0.9972) no próprio TTS/ack: killTTS não
  cobria pw-play + sem supressão pós-brain.
- 2 processos pw-record órfãos concorrentes (restart com wait sem SIGKILL).
- mic→STT small direto no mesmo áudio: PT-BR perfeito com pausas
  ("...A gente tá testando aqui, entendeu?").
```

Correções aplicadas (código, pendente deploy): baseline bilateral com clamp
[200,3000], endpoint relativo ao pico (`peak*0.4`, legado), supressão de
8s pós-brain (+3s pós-rejeição), kill `pw-play`, restart com re-kill +
aviso de órfão, notify "Ouvindo…" no confirm, som+notify de erro no STT
e no brain, `processing`/`boot` no mapa da Waybar.

```text
BLOCKED (deploy) — RESOLVIDO 2026-09-07 09:52:
- Causa raiz: GC (nh-clean) removeu o .drv base16-schemes; output veio do
  cache, .drv foi reconstruído via `nix build nixpkgs#base16-schemes` no rev
  travado. Mais um E111 meu no daemon (indent) — corrigido.
- ./rebuild-host.sh: ✅ SISTEMA ATUALIZADO. Daemon novo (PID 1398756):
  baseline parte de 200.0 (clamp), órfãos limpos (1 pw-record), jarvis-voice
  com default small, Waybar processing/boot, supressão 8s, kill pw-play.
- Nightwatch: roda via timer de sistema (03:05); run de ontem 21:21-22:33 fez
  os 9 "chore" commits (edições sãs no voice/wakeword) + `nix flake update`
  parcial que quebrou o eval. Trabalho dele preservado em
  /tmp/nightly-flake-work.patch; revertido só o par flake.nix/flake.lock
  (sox mantido e implantado).
```
