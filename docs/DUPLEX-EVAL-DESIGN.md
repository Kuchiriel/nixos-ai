# DUPLEX-EVAL — design do harness de eval do modo voz (P5, noite 20/10, AGENTE-HB)

> Pendência 8 do VOZ-FULL-DUPLEX.md. Fontes: DuplexCascade 2603.09180
> (Full-Duplex-Bench: Averaged Turn-Taking Accuracy; interrupção/backchannel/thinking),
> Duplex-MPE 2609.31948 (silence-preservation, 4 scores multi-party), transcripts Codacus
> (bateria do vídeo de arquitetura). Runner: `scripts/duplex-eval.py` (novo, lane HB).

## O que avaliamos (classes do classify_turn v21: RESPOND/WAIT/SILENCE/BARGE)

### 1. Unit: turn-taking accuracy (classify_turn puro, sem áudio)
Cenários byte-a-byte do protocolo, gold-label por classe:
- pergunta direta → RESPOND · pensamento alto ("deixa eu ver…") → WAIT ·
  backchannel do dono ("hum", "pois é" durante resposta) → WAIT (nunca RESPOND!) ·
  silêncio/ruído/música → SILENCE · fala por cima do TTS (barge real) → BARGE.
- Score = Averaged Turn-Taking Accuracy (média simples por classe, estilo FDB);
  dataset = estender a bateria 6/6 p/ ≥30/cena (semear do semantic-turn-taking traduzido).

### 2. E2E acústico (stack live :8092 + :8097) — as métricas do dono
| métrica | definição | alvo |
|---|---|---|
| BARGE latency | dono começa a falar sobre o TTS → `_aplay` morto | P99 < 800ms |
| TimeSpeak | fim da pergunta do dono → 1ª sílaba TTS | P99 < 1.2s |
| tick latency | ciclo classify_turn (medido 132-192ms) | P99 < 400ms |
| silence preservation | clipe de fala REAL vira transcrição, nunca descartado | ≥ 98% |
| **hallucination-on-trigger** | clipe silence/nonspeech/music → saída do ASR deve ser VAZIA | ≤ 2% alucina |

Fixtures: **parquets Scicom** (kaggle-pkg) — os MESMOS do retreino servem de eval:
silence (42), nonspeech (1168), music (600). Hallucination-on-trigger roda HOJE: POST
/inference em :8097 com os FLACs, gate asrd v6 ON — reporta taxa de alucinação por
categoria (é o regression smoke do asrd/gate/lexicon juntos).

### 3. Regressão permanente (smoke noturno/CI)
- Chemicals demo (cena "Stop! Do not mix…") como smoke de interrupção — transcript
  canônico no card do LoRA.
- Hallucination-on-trigger em amostra fixa (20 clips aleatórios com seed) — compara
  baseline vs pós-mudança de gate/modelo (detona o "asrd piorou sem ninguém ver").
- Bateria unit 1. roda offline (sem GPU, sem stack) a cada commit de duplex-voice.py.

### 4. Guardas de inteligência (futuro, dono citou IFEval)
Respostas do :8092 a prompts de instrução simples — não implementar antes do
genuíno-PT resolver o viés de "calado".

## Cadência
- Noite/autônomo: (2) hallucination-on-trigger + (3) chemicals smoke + bateria unit.
- Com dono (manual): BARGE latency e TimeSpeak (precisa voz real sobre TTS — BARGE ao
  vivo já é pendência OC).
- Métricas em `reports/duplex-eval/<ts>.json` + última em `reports/duplex-eval/latest.json`
  (baseline versionada junto com o commit do stack medido).

## Regras
- eval NUNCA escreve em lanes do OC (só lê endpoints públicos :8092/:8097).
- Carga leve: sequencial, amostra pequena; nunca paralela contra stack live.
- Sem áudio do dono sem consentimento explícito (fixtures = Scicom/geradas).
