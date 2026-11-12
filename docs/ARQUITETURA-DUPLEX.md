# Duplex Voice Assistant — arquitetura e estado medido

## Mapa dos 3 componentes

```
┌─────────────────┐
│  Audio (USB)    │
│  pw-record      │
└────────┬────────┘
         │ int16 PCM 16kHz
         ▼
┌─────────────────┐                   ┌─────────────────┐
│  ASRD           │   text stream     │  Whisper turbo  │
│  duplex-asrd    ├──►──►──►──►───────►  :8097          │
│  (whisper turbo)│                   │  turbo-q5_0     │
└────────┬────────┘                   └─────────────────┘
         │ JSON lines
         ▼
┌──────────────────────┐                     ┌──────────────────┐
│ ORQUESTRADOR         │    /v1/completion    │ 4B-MTP :8092     │
│ duplex-voice.py      │─── llama-server ────►│ Qwen3.5-4B       │
│ (cascade JARVIS,     │    /lora-adapters     │ + microturn-4b   │
│  gate, AEC, TTS)     │    microturn LoRA     │ = classificador  │
└──────────┬───────────┘                     └──────────────────┘
           │ electric-speech
           ▼
┌──────────────────────┐                     ┌──────────────────┐
│ TTS                  │    /tmp/jarvis-     │ Kokoro v1        │
│ duplex-ttsd.py       │ FIFO ── speak.py ──►│ (nvidia nemotron)│
│ (kokoro synth +      │                     │ piper otherwise) │
│  piper backend)      │                     └──────────────────┘
└──────────────────────┘
```

## Papel de cada componente

### 1) Microturn-4B LoRA (no 4B-MTP :8092)
**O que faz**: classifica o turno transcripto do usuário em 4 classes:
- `RESPOND` — fala completa, pergunta/comando, responde
- `WAIT` — frase incompleta, espere mais fala
- `SILENCE` — backchannel/ruído, TTS fica calado
- `BARGE` — usuário interrompeu a fala do assistente

**Como funciona**: slot llama-server com `draft-mtp` + `--lora init-without-apply`; o
client ativa o adapter via `POST /lora-adapters` para inferência e desativa para CHAT livre
quando precisa de modelo forte. É um classificador, não um gerador.

**Estado medido**: bench `benchmarks/voice/bench_gate.py` — 27 falas rotuladas, recall=1.0,
precision ~0.65, F1=0.79. Filtra quase 90% das intrusões sem cortar as de fala real.
MOROSIDADE real (lote): mean ~500ms por classify call.

**Alternativa avaliada**: Laya (100+ idiomas, non-autoregressive, 33ms, calibrada via RLCD).
Laya casa melhor com o problema (decisão, não geração) e roda ~10x mais rápido;
fine-tune 4 classes seria bem direto (CC0-style dataset v3, já organizado para isso).
Modelo base público `convaiinnovations/laya`.

### 2) Laya (não assumida, em avaliação)
**O que faz**: decisão tipada não-autoregressiva em ~30–80 ms. Base zero-shot é fraca
(passa ~55% em conversões genéricas); fine-tune on-domain entrega 0.77. Rodar como slot
próprio ou como fallback ao microturn-4b-lora.

**Por que não foi assumida ainda**: ONNX export exigido, e o DuplexCascade stem uma
hipótese de decisão só com o token atual (sem AUDB/context quando multi-party).

### 3) Cactus Needle3
**O que faz**: 8–29 MB, ~8–121M parâmetros, on-device tool-call automático e extração
de texto. **Não é um classificador de turno** — papéis totalmente diferentes.

**Caso no duplex**: "fragmento com intenção de tool" → Needle executa a tool direto
(confiança alta) ou escala pro 35B (confiança baixa). Já clonado em ~/projects/cactus-needle,
pesos needle3.cact em cache. Writeline: ~30–200 ms.

## Onde vive o código

DURABLE stuff (de não se perder):
- `nixos-ai/scripts/duplex-voice.py` — orquestrador principal (cascade + microturn gate + cascade + TTS + AEC)
- `nixos-ai/scripts/duplex-asrd.py` — wrapper whisper turbo-q5_0 com noise-cancellation e anti-halluc gate
- `nixos-ai/scripts/duplex-ttsd.py` — daemon TTS (FIFO, kokoro + piper)
- `nixos-ai/benchmarks/voice/bench_gate.py` — bench de gate (27 falas)
- `nixos-ai/scripts/bench_mic_fill.py` — medir WAILS real do mic com2

SRA-cascade (o arquétipo de microturn):
- `DuplexCascade/` (upstream MIT, da paper arXiv 2603.09180) — não roda em produção,
  é a referência teórica que motivou a escolha de micro-turns em vez de VAD.
- `nixos-ai/scripts/` é o fork Brooke Labor com
  - cascade 4B→groq→nvidia→openrouter (recarrega limpo, ver docs/auditoria/*)
  - microturn-4b-lora por slot llama-server
  - cascade de LADs com muito mais espaço de rádio

## Estado medido de cada parte

| Componente | Estado | Comentário |
| --- | --- | --- |
| VAD (silero) | fechado | |
| ASR turbo-q5_0 | 250 ms/seg | OK; PT-BR impecavel |
| Microturn-4b-LoRA | 500 ms mean | precision 0.65 vs recall 1.0; F1 0.79 |
| Cascade (groq->nvidia->openrouter) | 0.5-3 s | fast* + extra_reasoning=low, 11/11 conteudo |
| TTS Kokoro | ~200-400 ms/sentence | piper fallback se kokoro falhar |
| Speaker-ID (mic logs) | embeddings glued | preciso validar antes de usar no gate |
| Acronomy wakeword | nao assumido | PoC em `reports/duplex-eval/needle-poc.json` |
| FDT e2e | sem teste | manter 4B-MTP cada semana |

## O que trava a evolução hoje
- Classifier de turno é LoRA-style (proxy shader): avaliados 27 exemplos, mas o "se intromete"
  do dono persistiu mesmo com LoRA+gate.
- O gate falha em: TV portuguesa (path: `"ahá"`), background speech (path turns: `"então..."`+`"ahá"`),
  ou próprio dono tentando interromper o assistente (passage BARGE).
- Cascade sem cascade → todos os request puros exigem LLM.

## Próximo do roteiro

1. **Laya** como gate de turno — remove o LoRA
2. **Needle3** para tool-calls — separa decisão de execução: execution acha a tool e preenche argumento, backbone só verifica
3. **Microturn cascade** único: ASR → decider → agent → executor TTS

Referência de checkpoints desse roteamento já está implicitamente em `duplex-voice.py`'s `self._idx`.
FALTA: documentar `self._idx`, separar test plan, eMeasure latency before/after.
