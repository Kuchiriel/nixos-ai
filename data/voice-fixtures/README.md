# Fixtures de voz (destino durável)

Os fixtures do bench de voz moram **aqui**, fora do `/tmp`.

## Por que este diretório existe (medido 09/11)

O bench `scripts/duplex-eval.py --trigger-bench` lia os parquets do Scicom de
`/tmp/opencode/night-microturn/kaggle-pkg/`. A limpeza do `/tmp` levou os arquivos e o
bench passou a reportar `sem fixtures` nas quatro categorias: a bateria E2E de voz ficou
em **0/10 "sem-segmento"** não por causa do ASR, mas porque o corpus foi apagado.
**Fixture de eval não vive em `/tmp`** (o `tmpfiles` limpa, e a próxima limpeza come o
bench de novo).

## O que o bench espera

Quatro parquets, com as colunas `id` e `audio.bytes` (bytes de áudio codificados):

- `silence.parquet`: silêncio (controle negativo)
- `nonspeech.parquet`: sons não-fala (ruído, respiração, tosse)
- `music.parquet`: música
- `reduplication.parquet`: áudio repetido/duplicado

Uso:

```bash
scripts/duplex-eval.py --trigger-bench --samples 10 \
  --fixtures data/voice-fixtures --log /tmp/opencode/trigger-bench.json
```

## Como os arquivos chegam aqui

Eles são **produto do pipeline do VAC** (que extrai os clips do corpus Scicom e monta
os quatro parquets), não do dataset cru. O sweep-2026-11 confirmou a origem do corpus
(Scicom é subset do Emilia, no HF e no Kaggle) e fica com a parte de baixar o bruto e
deixar em destino durável.

### O pipeline foi recuperado (09/11, coord-naming)

O script do VAC (`whisper-antihalluc-kernel.py`) **não está no repo** e não sobrou
no `/tmp` — mas estava nos **transcripts** (opencode.db). Recuperado (com os 2 edits
aplicados) e salvo em **`scripts/kaggle-scicom-antihalluc-kernel.py`**
(commit `fbb71be2`).

**O que a recuperação muda na divisão:** os quatro parquets **não são para
regenerar localmente** — são o **recorte processado** de um dataset **privado no
Kaggle** (o espelho privado do proprio dono do dataset; o HF original tem 164 GB, o pacote
pequeno é só o recorte). O caminho curto é **re-baixar esse dataset** e apontar o
bench para ele. O kernel recuperado documenta como o recorte foi feito (categorias
com alvo VAZIO no transcript, caps 500/500/400/400) e como re-fazê-lo se um dia for
preciso; ele roda **dentro do Kaggle** (`/kaggle/input`), não localmente.

Detalhe do dataset: além dos 4 gatilhos, o pacote tem `lexicon-synth-pt.parquet`
(395, **positivo** anti-overban) e `genuine-synth-pt.parquet` (124, negativo
genuíno PT) — o retreino anti-alucinação inteiro está no mesmo pacote.

Se o material vier em shards ou WAVs soltos (em vez do dataset pronto), o packer
`scripts/voice-trigger-fixtures.py` monta os quatro parquets no formato que o bench
lê (`id` + `audio.bytes` em FLAC), com `--verify` para reler como o bench lê.

## De onde vem cada categoria (medido, manifesto recuperado 09/11)

O pacote original é o **`scicom-antihalluc-pt`** (espelho privado do HF
o espelho privado do proprio dono do dataset, montado a partir de
`Scicom-intl/Whisper-Hallucination` na noite de 20/10). O manifesto
completo está em [`MANIFEST-scicom-antihalluc-pt.md`](MANIFEST-scicom-antihalluc-pt.md)
(recuperado dos transcripts; o original vivia em `/tmp` e a limpeza levou).

| arquivo | rows | classe | label | origem |
| --- | --- | --- | --- | --- |
| `silence.parquet` | 42 | gatilho | vazio | **sintetizável** (zeros) |
| `reduplication.parquet` | 1 440 | gatilho | `reference_text`/`reference_collapsed` | **sintetizável** (o mesmo segmento duas vezes) |
| `nonspeech.parquet` | 1 168 | gatilho | vazio | **FSD50K** (não-fala: ruído, respiração, tosse) — dataset pequeno, com rótulo de classe |
| `music.parquet` | 600 | gatilho | `reference_text` | música (onde nasce a alucinação clássica) |
| `lexicon-synth-pt.parquet` | 395 | **positivo** anti-overban | `phrase` = o texto real falado | TTS |

**Não precisa dos 164 GB** do `Malaysian-Chinese-Emilia`: ou se baixa o
espelho privado (que já traz os 4 parquets com FLAC embutido) ou se monta no
barato:

1. `silence` e `reduplication`: **sintetizar**, download zero;
2. `nonspeech`: FSD50K (pequeno);
3. `music`: fonte real, por último (é a categoria cara).

O script que consumiu os parquets está no repo:
`scripts/kaggle-scicom-antihalluc-kernel.py` (lê `FIX/{fname}.parquet`,
amostra por cap 500/500/400/400 e marca `arm=trigger` com target vazio).
O empacotador para material solto é `scripts/voice-trigger-fixtures.py`
(FLAC + `id`/`audio.bytes`, com `--verify`).

**Gap conhecido (do manifesto):** genuíno PT = 0 no Scicom inteiro, e
`speech_in_noise` ficou fora do pacote (vivia em `/tmp`, volátil).

### Atalho: o material está no HF público (medido 09/11, sweep-2026-11)

Não é preciso passar pelo Kaggle. O mesmo recorte (as mesmas categorias, o mesmo schema
`id` + `audio.bytes` em FLAC) está no dataset **HF `Scicom-intl/Whisper-Hallucination`**,
que é **público** (o manifesto diz "upload privado", mas a API responde `private: false`):

```text
https://huggingface.co/datasets/Scicom-intl/Whisper-Hallucination/resolve/main/data/silence/test-00000-of-00001.parquet
https://huggingface.co/datasets/Scicom-intl/Whisper-Hallucination/resolve/main/data/nonspeech/test-00000-of-00001.parquet
https://huggingface.co/datasets/Scicom-intl/Whisper-Hallucination/resolve/main/data/music/test-00000-of-00001.parquet
https://huggingface.co/datasets/Scicom-intl/Whisper-Hallucination/resolve/main/data/reduplication/test-00000-of-00001.parquet
```

Baixados direto para `~/.local/share/jarvis/voice-trigger/` (335 MB no total) e a
bateria rodou pela primeira vez com números reais:

```bash
D=~/.local/share/jarvis/voice-trigger; mkdir -p "$D"
for f in silence nonspeech music reduplication; do
  curl -sL -o "$D/$f.parquet" \
    "https://huggingface.co/datasets/Scicom-intl/Whisper-Hallucination/resolve/main/data/$f/test-00000-of-00001.parquet"
done
scripts/duplex-eval.py --trigger-bench --samples 10 --log /tmp/opencode/trigger-bench.json
```

**Primeira medição real do trigger bench (10 clips por categoria, 09/11 07:22)**:

- **silence**: alucinou 7/10 (taxa bruta 0,7), a lista mata 1, fica 0,6
- **nonspeech**: alucinou 9/10 (0,9), a lista mata 6, fica 0,3
- **music**: alucinou 10/10 (1,0), a lista mata 3, fica 0,7
- **reduplication**: alucinou 10/10 (1,0), a lista mata 7, fica 0,3
- **total**: 36/40 alucinou (0,90 bruto), a lista mata 17, fica 19/40 (0,47)

Ou seja: o ASR alucina em quase todo gatilho (o pior é música e repetição, 1,0), e **a
lista de negação sozinha não fecha** (ainda 0,47). **Este número é da lista crua** (o
proxy antigo do bench): o gate real é o que decide, e ele é melhor do que o proxy
sugere, não pior. A seção seguinte mede o gate como o asrd de fato o roda.
A comparação com o MFCC/WE speaker é outra frente (separabilidade do falante), e ela não
muda este número.

### Quanto o gate REAL mata (medido 09/11, sweep-2026-11, 120 clips)

**O número que decide é 0,200 de resíduo, e ele só existe porque o bench mediu
o gate de verdade.** Duas medições anteriores circulavam na casa e nenhuma das
duas era o gate: a de 0,925 simulava só o ramo *gated* (léxico E stats fracos),
e a da outra lane, 0,217, media as listas de texto. O gate de produção
(`scripts/duplex-asrd.py`, função `anti_halluc`) é uma pilha de ramos:

| ramo | precisa de stats fracos? |
| --- | --- |
| deny-list dura (substring, até 6 palavras) | não |
| greeting-fantasma ("e aí" seco, "e aí e aí") | não |
| repetição (hifenizada e token repetido) | não |
| "Legenda ..." no início | não |
| léxico Scicom + greetings | sim (`ns > 0.35` ou `lp < -0.45`) |
| ALL-CAPS | sim |
| gate estatístico (todos `ns > 0.6` e `lp < -0.8`) | sim |
| tokens-vs-duração (mais de 5,5 palavras/s) | não |

Medido com 30 clips por categoria (120 no total, seed 42, `/inference` com
`response_format=verbose_json`), com o gate como está no disco hoje:

| categoria | alucinou | gate REAL mata | dos quais determinísticos | proxy (listas) mataria | residual |
| --- | --- | --- | --- | --- | --- |
| silence | 22/30 (0,73) | 10 | 10 | 4 | 0,40 |
| nonspeech | 29/30 (0,97) | 26 | 23 | 19 | 0,10 |
| music | 30/30 (1,00) | 23 | 20 | 8 | 0,23 |
| reduplication | 30/30 (1,00) | 28 | 24 | 11 | 0,07 |
| **total** | **111/120 (0,925)** | **87** | **77** | **42** | **0,200** |

Ou seja: **o gate de texto derruba de 0,925 para 0,200**, e 77 das 87 mortes
são determinísticas, ou seja não dependem de stats de áudio. Isso importa
porque o stats é justamente o sinal que **não** discrimina: `no_speech_prob`
mediano 0,000 e `avg_logprob` mediano entre -0,22 e -0,30 contra limiar de
-0,45, ou seja a transcrição alucinada chega **confiante**.

**História do número:** com o gate antes da regra de repetição da lane de voz
(`scripts/voice_text_rules.py`), eram 77 mortes e residual 0,283. A regra de
repetição (que ela mediu antes: mata 3 de 3 das alucinações de repetição e 1
de 199 falas reais, com chave de desligio `JARVIS_VOICE_REPEAT_RULE=0`) levou
para 87 e residual 0,200. Esta seção é a que vale: o gate real é o do disco.

**O que sobra (24/120) e o que cada frente mata** (medido sobre as mesmas
amostras, com o gate REAL chamado offline e conferido 111/111 contra o bench):

| regra hipotética (não aplicada) | mata | residual |
| --- | --- | --- |
| prefixo "e aí" (o gate mata "e aí" seco, não "e aí E aí E aí") | 10 | 0,117 |
| repetição em formas que a regra atual não pega | 7 | 0,142 |
| lista multilingual `ban-hard` (hoje carregada e **nunca consultada**) | 0 | 0,200 |
| as duas primeiras juntas | 17 | **0,092** |

O que sobrevive às duas: 6× "Música"/"Música...", 3× "Obrigado.", "Amém.",
"Titi-titi.", "Tchau, tchau, tchau" e duas legendas (uma em inglês, uma em
espanhol). "Música" e "Obrigado" ficam de propósito fora do kill (sinal social
e fala real), então o resíduo irredutível do gate de texto é pequeno: o que
pede outra frente é a fala que **parece** real, e é aí que a wakeword entra (o
gate não pode matar "obrigado" dito de verdade).

**Como medir (e o que não medir):** o bench mede o gate REAL agora
(`scripts/voice_gate.py`, cópia verbatim da lógica do asrd, com paridade
provada por `scripts/check-voice-gate-parity.py`, que compara os dois códigos
por token stream). O proxy antigo (`text.lower() in ban`, igualdade exata em
dois TSV) fica no relatório como `lexicon_kill`, só para comparação.

```bash
# (09/11) pandas + pyarrow estão no devShell do nixos-ai; o venv do karaok
# tem numpy quebrado (precisa de libstdc++/libz no LD_LIBRARY_PATH).
nix develop --command python3 scripts/duplex-eval.py --trigger-bench \
  --samples 30 --seed 42 --out reports/duplex-eval
```

### Em qual caminho esses números foram medidos (09/11, coord-naming)

A seção acima é do **caminho cru**: o trigger bench faz `POST /inference` **direto no
whisper-server**, então ele nunca passa pelo VAD da casa, nem pela segmentação, nem
pelo gate `anti_halluc` do `duplex-asrd`. É "o que o whisper faz com o clip inteiro",
não "o que a casa responderia".

A **casa** foi medida no mesmo corpus com o probe
(`scripts/voice-pipeline-probe.py`: mesmo protocolo do `duplex-voice`, áudio em tempo
real, silêncio digital no fim para fechar o segmento, comparativo pareado do mesmo
áudio na mesma janela de 12 s, e controle positivo de fala real **9/9**):

| categoria | n | cru (whisper direto) | casa (VAD, segmento, gate) | segmentos abertos pelo VAD |
| --- | --- | --- | --- | --- |
| silence | 23 | 8 (0,35) | **0** | 0 |
| nonspeech | 30 | 26 (0,87) | **0** | 0 |
| music | 30 | 27 (0,90) | **0** | 2 |
| reduplication | 40 | 22 (0,55) | **3 (0,07)** | 33 |
| **total** | **123** | **83 (0,67)** | **3 (0,024)** | 35 |

Ou seja: **a casa corta 96 % das alucinações de gatilho**. O VAD não abre segmento
para silêncio, nonspeech e música (91 dos 123 clipes não abriram nada), o gate mata o
que passa, e o **residual são 3 clipes de repetição de sílabas** ("Ah, ah, ah.",
"Tataataataata. Uh uh uh.", "E E E E E"), com áudio confiante (`avg_logprob` −0,24 a
−0,43, acima do limiar −0,45) que o léxico não pega.

Ou seja, os dois números são verdadeiros e medem coisas diferentes: **"o gate real mata
0" vale para o clip inteiro** (o bench); **no pipeline o gate mata parte dos
segmentos** que o VAD corta (na rodada com prova por segmento: 6 segmentos abertos, 3
mortos pelo gate com áudio fraco, `avg_logprob` −0,512 e −0,4985, e 3 sobreviventes).
O wakeword continua sendo a frente que cobre o que sobrou (repetição) e a variação de
nível de uma sala real. Detalhes: `docs/auditoria/LAYA-GATE-2026-11-03.md` §5c e
`reports/voice-pipeline/*.json`.

## Regra

Qualquer artefato de avaliação (áudio, parquets, reports grandes) vai para um caminho
versionado ou para `~/Books/datasets/`, **nunca** para `/tmp`. O `/tmp` é para o que
pode ser jogado fora a qualquer momento.
