# AUDITORIA — Gate de áudio da voz (pend. 4): o que já existe, o que falta, como medir

**Data:** 08/11/2026 · **Lane:** coord-naming · **Estado:** desenho pronto, medição
bloqueada pela bateria E2E quebrada (0/10, lane de voz).

## 1. Onde o gate de texto parou

Medido no caminho vivo (27 falas PT-BR, classificadores reais no 4B:8092,
`GATE_MODE=intent`, decisão em `modules/ai/jarvis/src/jarvis/voice_gate.py`):

| | TP | FN | FP | precision | recall | F1 |
|---|---|---|---|---|---|---|
| gate antigo (palavra "Jarvis") | 2 | 11 | 0 | 1,000 | 0,154 | 0,267 |
| **gate de texto no ar** | **12** | **1** | **2** | 0,857 | **0,923** | **0,889** |

Os 2 falsos positivos que sobram são **acústicos**, não textuais:

- `where's the one?` → fala da **TV**;
- `vamos embora` → **auto-fala**.

Nenhuma cantidad de raciocínio sobre o texto separa a TV do dono: é a mesma
frase que o dono diria.

## 2. O que a casa JÁ tem para isso (medido, não suposto)

| peça | estado | evidência |
|---|---|---|
| embedding de falante por segmento | **pronto** | `scripts/duplex-asrd.py`: WeSpeaker ResNet34 256-d, ONNX, **83 ms/segmento** CPU (`~/.wespeaker/en/model.onnx`), fallback MFCC |
| cluster em falantes anônimos | **pronto** | ids emergentes `spk1, spk2…` com cosseno > 0,80 (limiar provado no applio-lab cross-video) |
| id do falante no transcript | **pronto** | prefixo `[spk: X]` nos turnos do usuário |
| identificação contra vozes conhecidas | **pronto, sem uso** | `_identify()` casa com `SPK_PROFILES`; o loader procura `data/spk-profiles.json` e `/tmp/jarvis-spk-profiles.json` |
| **perfil enrolled do dono** | **AUSENTE** | **nenhum dos dois arquivos existe** → `SPK_PROFILES = {}` → todo segmento sai `spk=?` |
| regra de gate "só o dono fala comigo" | **ausente** | o gate de texto nunca olha o falante |

**Medido:** o log do duplex de 08/11 (`logs/duplex/2026-11-08.log`) tem
**zero** prefixos `[spk: …]` — porque não há perfil cadastrado e o cluster
emergente precisa de alguns segmentos antes de nomear alguém.

## 3. O plano (do mais barato para o mais caro)

1. **Matricular o dono** (sem modelo novo, sem flag): gravar
   `data/spk-profiles.json` com o embedding 256-d do dono, calculado a partir
   de alguns WAVs da voz dele (o código já calcula exatamente esse
   embedding). É a metade que falta de umafeature existente desde 21/10.
   O arquivo é **local da máquina** (dado biométrico): nunca entra no repo,
   nunca sai da box (o WeSpeaker roda na CPU).
2. **Regra de gate**: segmento cujo `spk` não é o dono **e** não é o falante
   do último turno atendido (a regra sticky já existe) não vira resposta. A
   voz da TV falha no passo 1 → os 2 falsos positivos somem sem mexer no
   gate de texto.
3. **Medir** no corpus que já existe (`benchmarks/voice/bench_gate.py` +
   os WAVs do duplex): recall ≥ 0,92 e FP de 2 → 0. Se não happen, a
   conclusão honesta é que **a TV e o dono não são separáveis pela voz** nesta
   sala, e o próximo passo é o **wakeword** (a pend. 4 original), não mais
   machine learning.
4. **Só se o passo 3 falhar**: Nemotron 3 Diarization (100 M, open weights,
   streaming, 8 falantes, DER 14,72 %) para um clustering anônimo mais
   confiável, ou verificação on-device no padrão Sensory/Picovoice (4
   repetições de uma frase) como decisão de produto.

## 4. Base do estado da arte (nota completa em `~/Books/papers/2026-11-08-audio-gate-state-of-the-art.md`)

- **Apple**: *Device-Directed Speech Detection* sem wake word, com
  **false-trigger mitigation** — o espelho do nosso caso.
- **arXiv:2403.14438**: o braço **multimodal** vale até **−39 % de EER**
  relativo sobre text-only (o braço que é o texto-only foi o que_medimos).
- **arXiv:2609.27037**: o LLM puro **sobre-ativa** (recall 0,993 com F1
  0,179) e **o objetivo do encoder decide**: falas > sons. Para nós: o sinal
  discriminante é **de quem é a voz**, não o volume.
- **Nemotron 3 Diarization** (100 M, open weights): #1 no Diarization-Bench.
- **Picovoice Voice ID / Sensory**: o padrão de produção é **matricular**
  (4 repetições, on device) e ativar **só para o usuário matriculado**.

## 5. Bloqueio honesto da medição

A bateria E2E de voz está em **0/10** (`reports/duplex-eval/latest.json`:
todos os cenários com `verdict: "sem-segmento"` — é o problema de
segmentação/injeção que a lane de voz está atacando). Sem ela, o passo 3
depende dos WAVs do duplex medidos direto, ou espera a bateria voltar.
