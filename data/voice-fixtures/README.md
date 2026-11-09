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
Kaggle** (`kuchiriel/scicom-antihalluc-pt`; o HF original tem 164 GB, o pacote
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
`kuchiriel/scicom-antihalluc-pt`, montado a partir de
`Scicom-intl/Whisper-Hallucination` na noite de 20/10). O manifesto
completo está em [`MANIFEST-scicom-antihalluc-pt.md`](MANIFEST-scicom-antihalluc-pt.md)
(recuperado dos transcripts; o original vivia em `/tmp` e a limpeza levou).

| arquivo | rows | classe | label | origem |
|---|---|---|---|---|
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

```
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
lista de negação sozinha não fecha** (ainda 0,47): o que fecha é o gate v6 completo, que
mora no asrd com as listas combinadas. A comparação com o MFCC/WE speaker é outra frente
(separabilidade do falante), e ela não muda este número.

### Quanto o gate de texto completo mata (medido 09/11, sweep-2026-11)

Sobre o acumulado do bench, com normalização de pontuação e caixa. Com 30 clips por
categoria (120 clips, 111 alucinações, taxa bruta 0,925, consistente com a primeira
rodada de 10 por categoria), o acumulado de todos os runs fica em **184 alucinações**
(reduplication 77, music 40, nonspeech 38, silence 29):

- `whisper-halluc-lexicon-pt` (a lista que o bench usa): mata **137/184**, sobra **0,255**
- `lexicon-pt` + `ban-pt-hard`: mata os mesmos 137, ou seja a lista dura **não acrescenta
  nada**
- `lexicon-pt` + `ban-pt-hard` + `ban-multilingual` (o v6 completo): mata **144/184**,
  sobra **0,217**
- só `ban-pt-hard`: mata 1 de 73 na amostra menor, praticamente nada
- só `ban-multilingual`: mata 39 de 73 na amostra menor

Ou seja: **o gate de texto completo (as três listas combinadas, que é o v6 do asrd) derruba
a alucinação de gatilho de 0,90 para cerca de 0,22**, e o resto precisa de outra frente: o
VAD/segmentação, o gate de falante (que não separa, medido) ou a wakeword. A lista
multilíngue é a que mais contribui depois do léxico PT; a lista dura é inócua aqui.

## Regra

Qualquer artefato de avaliação (áudio, parquets, reports grandes) vai para um caminho
versionado ou para `~/Books/datasets/`, **nunca** para `/tmp`. O `/tmp` é para o que
pode ser jogado fora a qualquer momento.
