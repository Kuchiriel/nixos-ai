# Desenho do gate de wakeword (a resposta honesta da pendência 4)

**Data:** 09/11/2026 · **Lane:** coord-naming · **Estado:** desenho pronto, nada
aplicado (não mexi em flag, em serviço nem no `duplex-voice.py`).

## 1. Por que chegamos aqui (medido)

O gate de **texto** está no ar e medido: recall **0,923**, F1 **0,889**
(`modules/ai/jarvis/src/jarvis/voice_gate.py`, 13 testes). Restam **2 falsos
positivos**, ambos acústicos: a **TV** ("where's the one?") e a **auto-fala**
("vamos embora").

A via barata era **identificação de falante** (o asrd já embute embedding
WeSpeaker e a matrícula do dono existe). **Medido que ela não segura**:

| backend | intra-falante | inter-falante | veredito |
|---|---|---|---|
| MFCC (o que a produção usava) | 0,9774–0,9994 | 0,9704–0,9992 | sobreposição total |
| **WeSpeaker** (runtime consertado em 09/11) | média 0,3526, p95 0,6435 | média 0,3196, p95 0,5751, max 0,8379 | **se tocam** |

O detalhe que fecha a conta: o limiar do asrd é **0,82**, e o intra p95 do
corpus é 0,6435 ⇒ **o gate rejeitaria a própria voz do dono** em take com
ruído; e o inter tem max 0,8379 (acima do limiar) ⇒ falso positivo
possível. A matrícula do dono (0,855 de consistência, `verify` 0,9006) foi
feita em takes limpos, o que não é o caso real da TV.

⇒ **O wakeword é o sinal que separa a TV do dono com confiança**: é um padrão
acústico específico que a TV não produz, e independe de falante.

## 2. O que a casa já tem (para não duplicar)

- **Modelo de wakeword já declarado**: `modules/ai/models.nix` tem
  `openwakeword` com `hey_jarvis_v0.1.onnx` + `embedding_model.onnx` +
  `melspectrogram.onnx` (pins sha256 ✓). Não é preciso baixar nada.
- **Daemon de wakeword** (`home-manager/modules/services/jarvis-wakeword.nix`):
  é **de desktop** (`After = graphical-session.target`, DISPLAY/WAYLAND) e
  serve a hotkey do PC (toca o som e chama `jarvis voice <wav>`) ⇒ **não
  serve o pipeline da voz** (que roda no celular/serviço, sem display).
- **O asrd já tem o lugar certo para o sinal**: ele já devolve `spk`,
  `voices` e `wav` por segmento; o wakeword entra como **mais um campo**,
  sem mexer no resto do caminho.

## 3. O desenho (3 passos, sem modelo novo)

1. **Wakeword no caminho do áudio** (não no desktop): rodar o openWakeWord
   sobre o **fluxo do microfone** (ou por segmento, se o custo de streaming
   pesar) e produzir um **estado de "acordado"**: timestamp do último wake +
   confiança. O estado é anexado a cada segmento pelo asrd, como o `spk` hoje.
2. **Regra no módulo do gate** (`jarvis/voice_gate.py`, que já é a decisão
   única e testada):
   - um segmento é **candidato** a resposta se: o texto contém "Jarvis"
     **ou** houve wake nos últimos N segundos **ou** o falante sticky é o
     último endereçado (a regra que já existe);
   - com o **LoRA** como âncora de precisão (medido: recall 0,923 com 2 FP);
   - **sem** wake e sem sticky, o segmento é ignorado ⇒ a TV não entra.
3. **Medir no corpus real** antes de conectar: o gate de texto já dá 0,923;
   o que falta é medir (a) recall do wakeword nos segmentos do dono (259
   segmentos em `logs/audio/`) e (b) FP do wakeword nos segmentos de TV e
   ambiente, mais o **end-to-end** (a bateria E2E, hoje 0/10 por
   "sem-segmento" — a lane de voz).

## 4. O custo honesto (decisão do dono)

Com o wakeword como âncora, **o dono passa a dizer "hey jarvis"** (ou a usar a
janela de "acordado" após um wake). Hoje o pedido em voz pura funciona sem
wakeword (recall 0,923), ao preço de 2 falsos positivos. A escolha é:

| opção | recall do dono | FP | custo de UX |
|---|---|---|---|
| texto (hoje) | 0,923 | 2 (TV + auto-fala) | nenhum |
| wakeword como âncora | depende do N e do corpus | ~0 se o wake for fiable | dizer "hey jarvis" |
| matrícula por falante | **não fecha** (medido) | — | — |

A alternativa que fica de pé e é mais barata: **manter o gate de texto e
usar o wakeword só como filtro negativo da TV** (se o wake não disparou e o
sticky não aponta para o dono, a TV é descartada) — que é exatamente o passo
2 acima sem mudar o UX do dono nos take limpos.

## 4b. O BLOQUEIO DA MEDIÇÃO (medido 09/11)

A medição do passo 5.1 **não roda hoje**, e o motivo é o mesmo do
WeSpeaker: **o runtime não está empacotado onde o medidor o encontra**.

- Os **modelos estão lá** ✓ (`~/.local/share/openwakeword/` → 3 symlinks
  para o store: `hey_jarvis_v0.1.onnx`, `embedding_model.onnx`,
  `melspectrogram.onnx`, com sha256 pinado em `models.nix`).
- O **pacote python** do openWakeWord é construído **dentro** do módulo do
  daemon (`home-manager/modules/services/jarvis-wakeword.nix`, um
  `buildPythonPackage` inline) ⇒ não existe como output do flake, e como o
  daemon está **desabilitado** o pacote nunca foi construído (não há
  `openwakeword` no store).
- `pip install openwakeword` não serve: o pacote pede `tflite-runtime`, que
  não tem wheel para o python 3.13 da box ⇒ é exatamente por isso que o Nix
  empacota à mão.

⇒ **A receita é a mesma do torchaudio**: uma linha no devShell (ou um output
do flake) com o pacote openWakeWord, e a medição roda com
`OWW_MODELS=~/.local/share/openwakeword` + os 1 817 WAVs de
`logs/audio/`. A alternativa é o dono habilitar o daemon (que é de desktop e
**não** serve o pipeline da voz, mas já traz o pacote no store).

## 5. O que eu faria primeiro (se o dono disser sim)

1. Rodar o openWakeWord **offline** sobre os 259 segmentos de `logs/audio/` e
   publicar a tabela: recall do wakeword nos segmentos do dono, FP nos de TV
   e ambiente, e a curva de threshold (é o mesmo método da separabilidade,
   que acabou de dar um veredito negativo honesto).
2. Só com a tabela em mãos, propor a regra exata (N, âncora, e o que fazer
   com a auto-fala) e o wiring no asrd (uma linha por segmento).

## 5b. PRIMEIRA MEDIÇÃO DO WAKEWORD (09/11, feita)

O scorer da casa (`modules/ai/ww_scorer.py`: mel + embedding + classifier
direto dos 3 ONNX pinados) medido sobre `logs/audio/` — **sem pacote novo e
sem tocar em serviço** (a tool `scripts/wakeword-eval.py` só executa o scorer
em lote e resume).

Primeira passada, 60 segmentos:

| métrica | valor |
|---|---|
| score mínimo | 0,0001 |
| score p50 | 0,0016 |
| score p90 | 0,014 |
| score máximo | **0,9301** |
| disparam acima de 0,3 / 0,5 / 0,7 / 0,9 | **1 / 1 / 1 / 1** |

O único segmento que dispara é o que o log do duplex marca como `respond`
(`083148_seg_1793014307.363.wav`) ⇒ é o wake verdadeiro. Todos os outros
(ambiente, TV, auto-fala) ficam **três ordens de grandeza** abaixo do
limiar ⇒ **o wakeword é preciso neste corpus** (o oposto do embedding de
falante, que não separa).

**Corpus inteiro (1 817 segmentos de `logs/audio/`):**

| limiar | segmentos que disparam | taxa |
|---|---|---|
| 0,3 | 20 | 1,10 % |
| **0,5** | **6** | **0,33 %** |
| 0,7 | 6 | 0,33 % |
| 0,9 | 6 | 0,33 % |

Distribuição: mínimo 0,0 · p50 0,0008 · p90 0,0267 · máximo 0,9938.

Leitura: a banda útil é **estreita e limpa** — 6 segmentos acima de 0,5
(0,33 % do corpus) e mais 14 numa banda intermediária 0,3–0,5. Com o
limiar em **0,5**, o wakeword é **sensível e preciso neste corpus**, ao
contrário do embedding de falante (que não separa). Os 6 que disparam são
os momentos de wake (o wakeword é o que o dono diz para acordar o JARVIS).

A tool também expõe o modo de calibração do próprio scorer
(`--positive-dir` / `--negative-dir` / `--target-fpr`) para escolher o limiar
em pastas rotuladas — é o passo seguinte quando houver negativo e positivo
rotulados (hoje: os 6 de wake sao os positivos; os 1 811 restantes, o
negativo).

### 5c. ROTULAGEM REAL (09/11): o corpus não tem **positivos**, e há um falso alto

Casando cada WAV de `logs/audio/` com o transcript do log do duplex (a fala
que precede a linha `respond wav: X.wav`): **66 segmentos rotulados**, e
**nenhum deles contém "hey jarvis"** — ou seja, o corpus de voz da casa é
falas do dono (e da sala) **sem** o wakeword.

| conjunto | n | maior score |
|---|---|---|
| com "hey jarvis" (positivo) | **0** | — |
| sem "hey jarvis" (negativo) | 66 | **0,9073** |

⇒ **O limiar não pode ser chutado.** Com 0,5, **um segmento que não é
wakeword marca 0,9073** (passaria como wake ⇒ o assistente acordaria com o
som errado). E sem positivos **não dá para medir o recall do wakeword**: os
6 disparos da corrida completa (0,5+) estão nos segmentos que não consegui
rotular, e podem ser wakes verdadeiros **ou** falsos positivos da sala.

**O input que falta (uma coisa só, e é do dono):** alguns WAVs do dono
**dizendo a frase de wake** ("hey jarvis", 5 a 10 amostras no microfone de
uso). Com os positivos + os 1 811 negativos já medidos, o modo de
calibração do scorer (`--positive-dir` / `--negative-dir` / `--target-fpr`)
entrega a curva de threshold **com número**, e a pendência 4 fecha por
medição, não por palpite.

**O que ainda falta para fechar a pendência 4:** (a) o número do corpus
inteiro, (b) rotular dono x TV casando o WAV com o log, (c) o wiring do wake
state por segmento no asrd (lane do duplex) e (d) a bateria E2E de voz de pé
(o fix do env do ASRD, do sweep, destrava o "sem-segmento").

## 6. Estado da evidência

- Gate de texto no ar: `jarvis/voice_gate.py` (13 testes), medido r=0,923 /
  f1=0,889 no caminho vivo.
- Matrícula do dono existe (`data/spk-profiles.json`, gitignored, biométrico
  não sai da box) e a separação foi medida e **não fecha**.
- Ferramentas: `scripts/spk-enroll.py` (matrícula) e
  `scripts/spk-separability.py` (a medição, com os dois backends).
- **Não** toquei em `scripts/duplex-voice.py`, em flag de serviço ou no
  daemon de wakeword: o wiring é da lane que owns o duplex.
