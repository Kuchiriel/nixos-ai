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

## Regra

Qualquer artefato de avaliação (áudio, parquets, reports grandes) vai para um caminho
versionado ou para `~/Books/datasets/`, **nunca** para `/tmp`. O `/tmp` é para o que
pode ser jogado fora a qualquer momento.
