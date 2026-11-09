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

## 6. A MEDIÇÃO QUE DECIDE (09/11): o gate por matrícula NÃO separa vozes hoje

`scripts/spk-separability.py` (novo) mede a separabilidade do embedding de
falante **com o backend que a produção usa de verdade**, no corpus da casa
(`~/Audio/_arquivo`: 68 takes de um falante, stems separados de um mix e
várias vozes TTS distintas):

| backend | intra-falante (mesma voz) | inter-falante (vozes diferentes) | veredito |
|---|---|---|---|
| **MFCC** (o fallback do asrd, 13 MFCC mean+std = 26-d) | n=34 · min **0,9774** · max 0,9994 · média 0,9922 | n=102 · min **0,9704** · max 0,9992 · média 0,9884 | **AMBÍGUO: as distribuições se tocam** |
| WeSpeaker 256-d | não roda hoje (ver abaixo) | — | — |

**Duas causas, ambas medidas:**

1. O runtime `wespeakerruntime` **só existe** em
   `/home/nixos/.venvs/lab/lib/python3.13/site-packages` e **não** no
   PYTHONPATH do asrd ⇒ o `import wespeakerruntime` falha lá e o `_embed()`
   cai **sempre** no fallback MFCC. O comentário do asrd fala em "WeSpeaker
   256-d, 83 ms/segmento, PROVADO no LOTM cross-video": o código está
   pronto, o runtime não está no caminho dele.
2. O venv `lab` (onde o runtime está) está com **numpy quebrado**
   (`libstdc++.so.6: cannot open shared object file`) ⇒ nem lá o backend
   WeSpeaker roda agora.

**Consequência para a decisão do dono:** com o backend que roda hoje, a
matrícula do dono **não separa a voz dele da voz da TV** (cos inter de
0,9704 contra intra de 0,9774: overlapped). Portanto:

- **O gate por matrícula, como está, não resolve os 2 falsos positivos.**
- A alternativa honesta para a pendência 4 é o **wakeword** (que é a
  pendência original), e não mais machine learning.
- Se o dono quiser revived o caminho do falante, são **duas** coisas: (a)
  colocar o runtime WeSpeaker no caminho do asrd (dependência + mudança de
  env: decisão do dono) **e** (b) reexecutar esta medição com ele — a tool
  já faz isso (`--backend wespeaker`).

**Nota de método:** o corpus aqui é de vozes de treino/TTS, ou seja, condição
de laboratório; a medição que vale é a matrícula real na sala do dono. Mas
para decidir entre "gate por falante" e "wakeword", a sobreposição medida
aqui já é um forte indício de que o caminho MFCC não serve.

Ferramentas: `scripts/spk-enroll.py` (matrícula) e `scripts/spk-separability.py`
(esta medição, com os dois backends).

## 7. A matrícula foi feita (09/11, sweep-2026-11) e o runtime foi consertado

**O bloqueio não era a voz, era o runtime.** `wespeakerruntime` importa
`torchaudio`, e ele não carregava em **nenhum** ambiente da box: o venv `lab`
tem torchaudio sem torch, e o nixpkgs tem torch sem torchaudio. Conserto:
`torchaudio` no devShell (commit `20346b3d`, branch `fix/speaker-runtime-torchaudio`)
+ o módulo do venv via `PYTHONPATH`. `onnxruntime` sozinho não bastava.

**Matrícula (sweep):** as gravações da bateria de voz (`logs/audio/`, 259
segmentos com ≥2 s e bom rms) foram agrupadas pelo próprio embedding; o
grupo coerente deu 11 amostras, 8 foram matriculadas ⇒ consistência
**mín 0,8552 / média 0,9015** (o aviso da tool pede > 0,8). `verify`:
**cos 0,9006** ⇒ owner, contra uma amostra do mesmo grupo que não entrou na
matrícula. O perfil está em `data/spk-profiles.json` (gitignored, 256-d,
biometrico não sai da box).

**Consequência:** o gate de áudio agora tem identificação de falante de
verdade (antes o log do duplex de 08/11 tinha **zero** prefixos `[spk: …]`).
A bateria E2E de voz ainda precisa voltar (0/10, `sem-segmento`) para medir
o recall do gate inteiro.

**O que falta agora (e é a medição que decide):** repetir a separabilidade
com o backend **WeSpeaker** (o que separa) e não com o fallback MFCC (o que
a produção usava até o conserto do runtime). Comando:

    nix develop --command env PYTHONPATH=<dir-com-o-wespeakerruntime> \
        python3 scripts/spk-separability.py --backend wespeaker

**Antes do conserto do runtime, a medição com MFCC deu sobreposição total**
(intra 0,9774-0,9994 contra inter 0,9704-0,9992) ⇒ com o backend antigo a
matrícula **não** separava a voz do dono da voz da TV. A pergunta agora é se
o WeSpeaker separa; é isso que decide entre "gate por falante" e "wakeword".
