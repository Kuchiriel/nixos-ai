# scicom-antihalluc-pt — material do retreino anti-alucinação (PT-BR duplex JARVIS)

> **RECONSTRUÍDO (09/11, coord-naming)**: este manifesto vivia em
> `/tmp/opencode/night-microturn/kaggle-pkg/` e foi com a limpeza do `/tmp`
> (a mesma que levou os fixtures de eval e o runtime de clone de voz).
> Recuperado dos transcripts da sessão e trazido para o repo, porque é a
> **fonte da verdade** do dataset (quais arquivos, quantas linhas, de onde
> veio cada classe) e o Sweep precisa dele para reconstruir os parquets.
> O script que o consume está em `scripts/kaggle-scicom-antihalluc-kernel.py`
> (também recuperado).

# scicom-antihalluc-pt — material do retreino anti-hallucination (PT-BR duplex JARVIS)

Fonte: HF `Scicom-intl/Whisper-Hallucination` (20/10). Montado pelo AGENTE-HB na noite
20/10 (missão microturn) p/ o retreino do whisper large-v3-turbo :8097 — decisões de
treino/lane: AGENTE-OC + dono. Upload PRIVADO, sem custo de quota (treino NÃO lançado).

## Arquivos e semântica de classe

| arquivo | rows | classe | label (target) |
|---|---|---|---|
| `lexicon-synth-pt.parquet` | 395 | POSITIVO anti-overban | `phrase` = o texto REAL falado (TTS multilingual-expressive das frases que o whisper alucina em PT) — ensina que "Obrigada, Sra" etc. são fala legítima QUANDO ditas |
| `silence.parquet` | 42 | GATILHO | `reference_text` (vazio) — ensina a ficar calado |
| `nonspeech.parquet` | 1168 | GATILHO | `reference_text` (vazio) — fsd50k não-fala |
| `music.parquet` | 600 | GATILHO | `reference_text` — música (onde nasce alucinação clássica) |
| `reduplication.parquet` | 1440 | GATILHO | `reference_text`/`reference_collapsed` — padrões repetitivos (loop de alucinação) |

Áudio: FLAC embutido na coluna `audio` (bytes) de cada parquet.

## Gaps conhecidos (decisão de manhã)

1. **Genuíno PT = 0** no Scicom inteiro (genuine + speech_in_noise são ms/outros).
   Material PT realista p/ negativo: corpus ufal do duplex, fixtures karaok, ou gravações
   do dono. Sem isso o retreino fica enviesado p/ "calado".
2. `speech_in_noise` (não-PT) ficou DE FORA do pacote — se valer como regularizador
   multilíngue, está em /tmp/opencode/night-microturn/scicom/ (volátil! reboot apaga).
3. Wild/librispeech/malaysian: não baixados (15 shards wild).

## Feeds de gate já em git (não fazem parte do dataset de áudio)

- `nixos-ai/data/whisper-halluc-lexicon-pt.tsv` (84 frases, count desc)
- `nixos-ai/data/whisper-halluc-bancandidates-pt-full.tsv` (84, verdict+reason — 74 weak_evidence/10 safe)
- `nixos-ai/data/whisper-halluc-ban-pt-hard.tsv` (10 safe_candidate = hard-ban tier 2)
- Gate live: asrd v6 (nixos-ai 1b9ee62) consome o léxico GATED com stats de áudio.

## Receita sugerida (rascunho p/ discutir — não é contrato)

Fine-tune do turbo com: sintéticos-PT (label=phrase) + gatilhos (label=vazio) +
genuíno-PT externo (label=texto real). Objetivo: matar alucinação no silêncio/música
sem matar fala legítima (o gated-lexicon cobre o runtime até lá).
