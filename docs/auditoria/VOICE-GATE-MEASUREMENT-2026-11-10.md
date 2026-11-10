# Gate de voz: o que fecha, o que custa e o que não tem jeito (10/11/2026)

Medido na casa, com um protocolo só, para a decisão do dono sobre a wakeword e para a
lane de voz decidir o que dá para implementar sem custo escondido.

## 1. O que foi medido

- **Alucinações de gatilho**: 120 clips do recorte público Scicom
  (`Scicom-intl/Whisper-Hallucination`), 30 por categoria (silence, nonspeech, music,
  reduplication), seed 42, `POST /inference` com `response_format=verbose_json`.
- **Fala real da casa**: 1817 transcrições de `logs/audio`, feitas pelo whisper-server
  da casa (mesmo caminho do bench), em cache local.
- **Gate medido**: o gate de produção (`scripts/duplex-asrd.py`, `anti_halluc`), extraído
  verbatim para `scripts/voice_gate.py`, com paridade provada por token stream em
  `scripts/check-voice-gate-parity.py` (o checker já pegou o asrd mudando por baixo).
- **Protocolo**: commit `b256a247`; estado por amostra em
  `reports/duplex-eval/trigger-samples-2026-11-09T231001.jsonl` (111 linhas).

## 2. O gate real (o número que decide)

| | alucinou | gate REAL mata | dos quais determinísticos | proxy (listas) mataria | residual |
|---|---|---|---|---|---|
| gate sozinho (sem VAD) | 111/120 (0,925) | 87 | 77 | 42 | **0,200** |
| casa (VAD → segmento → gate) | 83/123 (0,67) | — | — | — | 3/123 (0,024) |

Os dois números que circulavam antes não eram o gate: 0,925 era uma simulação que
considerava só o ramo *gated*, e 0,217 eram as listas de texto. **77 das 87 mortes do
gate não dependem de stats de áudio**, e é por isso que o gate real é muito melhor que
o proxy: o áudio da alucinação é confiante (`no_speech_prob` mediano 0,000,
`avg_logprob` mediano entre -0,22 e -0,30 contra limiar de -0,45).

Resíduo de 24/120: 10 "E aí ..." compostos, 5 "Música"/"Música...", 3 "Obrigado.",
3 repetições em formas que a regra atual não pega, "Amém." e duas legendas (uma em
inglês, uma em espanhol).

## 3. O custo em fala real das regras de texto (o que faltava medir)

Uma regra de texto no gate não é de graça. Medido nas 1817 falas reais:

| superfície | falas reais expostas | observação |
|---|---|---|
| texto **exato** no léxico Scicom | **134 (7,4 %)** | "Obrigado.", "Tchau.", "Muito bom.": são fala real, e o ramo gated existe para protegê-las |
| texto exato no greeting suspeito | 0 (0,0 %) | nenhum "e aí" isolado na fala real |
| começa com "e aí" | 34 (1,9 %) | é fala real e comum |

E o custo da regra candidata ("e aí" no início **e** o resto parecendo alucinação,
conservadora de propósito, para "E aí, tudo bom?" passar):

- **benefício**: mata **10 dos 24** sobreviventes do gate;
- **custo**: mata **1 de 1817** falas reais (0,06 %), que é
  `"E aí, o que é isso?"` (`191803_seg_1793744280.221.wav`).

## 4. A colisão: a mesma frase está nas duas classes

O custo acima não é um defeito da regra: é o **piso** de qualquer gate de texto. A
frase `"E aí, o que é isso?"` aparece **idêntica** na fala real (1 caso) e nas
alucinações (1 caso). Não existe função do texto que mate a alucinação e preserve a
fala real, porque são a mesma string. Qualquer regra que feche a alucinação paga a
mesma fala real.

Isso vale para todo o resíduo: "Obrigado." (3 alucinações) e "Obrigado." dito de
verdade (várias vezes nas 1817) são o mesmo texto. O resíduo da alucinação de gatilho
é, em boa parte, **fala real que o ASR ouviu onde não havia fala**.

## 5. O braço de áudio não é consertável com o que o whisper.cpp expõe

O gate usa `no_speech_prob` e `avg_logprob`, e os dois foram medidos inoperantes na
alucinação de gatilho (0 de 111). O servidor expõe mais, e o gate ignora:
`words[].probability` (confiança por palavra), `tokens` (compression ratio) e a duração
do segmento. `scripts/measure-voice-signals.py` mede a separação de cada sinal contra
as falas reais (300 transcritas **com segmentos** contra as 111 alucinações do bench):

| sinal | AUC | custo em fala real no limiar que mata 10 % das alucinações |
|---|---|---|
| `min_word_prob` | 0,339 (invertido) | 27 % |
| `med_word_prob` | 0,272 (invertido) | 30 % |
| `no_speech_prob` | 0,634 | 62 % |
| `avg_logprob` | 0,315 (invertido) | 34 % |
| duração | 0,628 | 94 % |
| palavras por segundo | 0,142 (invertido) | 100 % |
| compression ratio | 0,253 (invertido) | 12 % |
| tokens por palavra | 0,607 | 1 % |

Leitura: **nenhum sinal que o whisper.cpp expõe serve como braço de áudio.** O melhor
AUC é 0,63 (fraco) e todo limiar que mata 10 % das alucinações mata de 12 % a 100 %
da fala real. E o "invertido" é a mesma informação de antes: nas alucinações de
gatilho a confiança por palavra e o logprob são **mais altos** que na fala real (o
ASR alucina confiante, com sampling de temperatura alta depois de uma queda de
confiança). O único com custo baixo (tokens por palavra, 1 %) tem AUC 0,607, e é
grosso demais para servir de braço.

O que a literatura de 2026 diz (nota completa em `~/Books/papers/2026-11-10-whisper-hallucination-internals.md`):

- **arXiv 2606.23060** (Interspeech 2026): as métricas de texto degradam **sem
  transcrição de referência** (a casa não tem referência), o LLM é menos competitivo que
  o classificador de texto, e o sinal forte é o **probing dos estados internos do
  decoder**, que o whisper.cpp não expõe. Exigiria mudar o whisper.cpp e treinar um
  classificador: pesquisa cara, para uma placa de 6 GB.
- **arXiv 2609.32560** (Scicom) e **arXiv 2501.11378**: a defesa principal é o **VAD
  antes do decoder** (a casa já tem silero no `duplex-asrd`); o score de silêncio do
  Whisper não é VAD e threshold mais estrito corta fala real quieta.

## 6. Conclusão para a decisão

1. **O gate de texto já fecha bastante** (0,925 → 0,200 sozinho; 0,024 no caminho da
   casa com VAD). A deny-list e as regras determinísticas são o que funciona, e elas
   não dependem de nenhum sinal estatístico.
2. **A wakeword não é opcional**: o resíduo que sobrou é fala que **parece** real, e
   nenhuma regra de texto separa a mesma string nas duas classes (seção 4). O
   `--calibrate` do scorer da casa fecha a calibração com 5 a 10 WAVs do dono; o
   limiar não pode ser chutado (pior negativo medido 0,9073).
3. **Uma regra barata ainda compensa, se a lane de voz quiser**: a regra de prefixo
   "e aí" mata 10 dos 24 sobreviventes por 1 fala real em 1817 (0,06 %), com chave de
   desligio no mesmo padrão da regra de repetição (`JARVIS_VOICE_REPEAT_RULE=0`).
   Medida pronta em `scripts/measure-voice-rule-cost.py`.
4. **O que não compensa**: mexer no limiar de stats do gate (medido inoperante) ou
   procurar mais sinal de texto (o piso é a colisão da seção 4). O sinal forte exige
   mudar o whisper.cpp, e só se justifica se a wakeword falhar.
5. **Um achado de arrumação**: a lista multilingual `ban-hard` é carregada pelo asrd e
   **nunca consultada** pelo gate (mata 0 dos 24). Ligar ou remover é decisão da lane de
   voz; do jeito que está, é código morto.
