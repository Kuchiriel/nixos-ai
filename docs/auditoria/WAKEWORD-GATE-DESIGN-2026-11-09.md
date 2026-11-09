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

## 5. O que eu faria primeiro (se o dono disser sim)

1. Rodar o openWakeWord **offline** sobre os 259 segmentos de `logs/audio/` e
   publicar a tabela: recall do wakeword nos segmentos do dono, FP nos de TV
   e ambiente, e a curva de threshold (é o mesmo método da separabilidade,
   que acabou de dar um veredito negativo honesto).
2. Só com a tabela em mãos, propor a regra exata (N, âncora, e o que fazer
   com a auto-fala) e o wiring no asrd (uma linha por segmento).

## 6. Estado da evidência

- Gate de texto no ar: `jarvis/voice_gate.py` (13 testes), medido r=0,923 /
  f1=0,889 no caminho vivo.
- Matrícula do dono existe (`data/spk-profiles.json`, gitignored, biométrico
  não sai da box) e a separação foi medida e **não fecha**.
- Ferramentas: `scripts/spk-enroll.py` (matrícula) e
  `scripts/spk-separability.py` (a medição, com os dois backends).
- **Não** toquei em `scripts/duplex-voice.py`, em flag de serviço ou no
  daemon de wakeword: o wiring é da lane que owns o duplex.
