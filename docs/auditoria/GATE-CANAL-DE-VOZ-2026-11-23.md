# O gate no canal de voz: 24/39 (o texto dava 29/39)

(23/11/2026, coord-naming) O acervo mediu que um turno falado custa **−12
pontos de Pass@1** pelo front-end de voz (`harness-voice-bridge.md`) e que
o **PF < 10 %** para todo modelo na cadeia de ferramentas por voz
(VoiceAgentBench, arXiv 2510.07978). O `bench_heldout3.py` da casa, porém,
classifica o item como **TEXTO** — ou seja, **o gate nunca foi medido no
canal por onde ele trabalha de verdade** (o áudio do dono transcrito pelo
whisper), e é esse número que decide o modo de delegação.

## O número

Heldout3 (39 itens, **0 vazamento**), texto **sintetizado na voz real da
casa** (piper `pt_BR-faber-medium`, o mesmo do duplex) e transcrito pelo
**mesmo ASR do cliente** (whisper :8097, multipart com `file` +
`response_format=verbose_json`):

| condição | acertos | acurácia |
|---|---|---|
| **texto** (o item como escrito) | 29/39 | **74,4 %** |
| **voz** (o que o ASR devolveu) | 24/39 | **61,5 %** |

**Delta: −12,8 pontos percentuais.** ASR médio: **333 ms** por item.
Palavras do original que não sobreviveram à transcrição: **4,28 por item**.

## O diagnóstico (o que a medição mostra, e o que ela não é)

O gate no texto: `SILENCE 24 · RESPOND 14 · WAIT 1`.
O gate na voz: `SILENCE 38 · RESPOND 1`.

**O ASR não destrói o sentido.** As transcrições estão corretas: "Cachorro
mordeu mal direito. Eu que faco agora mesmo. Urgente", "Me passa a chave
Fenda Feliz que esta em cima a bancada trabalha". O que quebra é o **gate**:
no canal de voz ele **colapsa para SILENCE** (38 de 39), que é o **mesmo
colapso** que o v9 já tinha no texto (SILENCE 21 de 23), **amplificado**.

**Os 8 itens que a voz perde e o texto acerta** (todos com a transcrição
correta): a abertura que o texto lê como `WAIT` vira `SILENCE`; e
comandos, pedidos, mordida e inseto que o texto lê como `RESPOND` viram
`SILENCE`. Ou seja: **o front-end de voz não apaga a informação — o
classificador deixa de reconhecer a fala depois que ela passa pelo
transcritor.**

## Consequências (o que muda na decisão)

1. **O número de TEXTO é o limite de cima, não o número real.** Qualquer
   veredito de delegação que use o texto está otimista em **~13 pontos** —
   e a perda não é do texto, é do gate no canal.
2. **O colapso em SILENCE é do gate, não do dataset.** Com o texto, o v9
   acerta 19 de 23 SILENCE; com a voz, o gate erra quase tudo para
   SILENCE. Isso reforça a conclusão do #08: a **fronteira SILENCE ×
   WAIT × BARGE** é onde o gate falha — e o canal de voz amplia a falha.
3. **A medição do gate tem que ser feita no canal de voz** antes de
   qualquer veredito de delegação por voz. O bench novo
   (`benchmarks/voice/bench-gate-voz.py`) faz as duas colunas lado a lado.

## Limites desta medição (honestos)

- O áudio é **sintetizado** (piper), não a voz do dono: a pronúncia real
  pode distorcer mais (o duplex já mediu o whisper ouvindo "Jarvis" como
  "Jax").
- O texto de entrada é o **heldout3** (itens escritos, sem o sufixo de
  marcação como no item 32) — é o conjunto limpo, mas não é fala humana.
- O ASR é o **mesmo** do cliente, com o mesmo modelo; não mexi no áudio nem
  no pipeline de voz.

## Como reproduzir

```bash
python3 benchmarks/voice/bench-gate-voz.py --json /tmp/opencode/gate-voz.json
```

Instrumento: `benchmarks/voice/bench-gate-voz.py` (sintetiza, transcreve,
classifica nas duas condições e mede a perda de palavras).
