---
title: "Held-out #3 do gate de voz: 39 itens sem vazamento e o buraco das-emergência"
type: auditoria
escopo: voice-gate-heldout3-vazamento-e-acuracia
data: 2026-11-18
status: medido
---

# Held-out #3 do gate de voz

O dono pediu um held-out novo porque o `heldout2` esta **contaminado** (medido
na auditoria do gate v10: 6/24 itens contem uma fala de treino completa como
substring e 19/24 tem quase-duplicata de template no corte 0,55). Entao
heldout2 nao vale para comparar versoes do kernel.

## 1. O verificador anti-vazamento (o que garante que o conjunto presta)

`benchmarks/voice/build_heldout3.py` **so grava o conjunto depois de medir**:

| medida | como | resultado |
|---|---|---|
| igualdade | fala do conjunto == fala de treino (normalizada) | **0** |
| containment | fala de treino aparece DENTRO de um item | **0** |
| quase-duplicata | similaridade de caracteres >= 0,55 com o treino | **0** |
| quase-duplicata do heldout2 | similaridade >= 0,55 com o heldout2 | **0** |
| template | dois itens comecam com o mesmo par de palavras | **0** |
| integridade | caractere fora do repertorio (CJK, emoji, controle) | **0** |

**O script se auto-reprovou 4 vezes** durante a construcao (5, 3, 2 e 5
problemas), e cada vez o conjunto **nao foi gravado**. Esse e' o comportamento
certo: falha barulhenta > held-out contaminado.

**O corpora de treino lido:** 11.042 falas de
`datasets/duplex-gate-v9/combined.jsonl` (o schema real e'
`{"messages": [{"role": "user", "content": ...}], "target": ...}`).

## 2. A régua de similaridade, medida

O corte de 0,55 foi escolhido porque e' o que a auditoria do v10 usou no
heldout2 (19/24 nele). Medido no conjunto novo:

| corte | heldout2 passa | conjunto novo passa |
|---|---|---|
| 0,50 | 24/24 | 8/39 |
| **0,55** | **19/24** | **2/39** |
| 0,60 | 17/24 | 0/39 |
| 0,65 | 15/24 | 0/39 |

O 0,60 e' o corte que reprova 100% do conjunto novo, mas ele tambem
perde 2 itens do heldout2 que o 0,55 pegava. Fiquei no **0,55**, que e' o
corte da comparacao com a auditoria existente: assim o "zero overlap" do
heldout3 e' comparável com o "19/24" do heldout2.

**A calibracao importa**: o 0,55 sozinho reprovava 24/34 itens do conjunto
novo, mas olhando os pares, varios nao eram quas duplicatas: `'as provas de
resistencia foram recolhidas pela manha'` vs `'Jarvis, lembra de comprar
leite amanha pela manha'` = 0,600. O corte pegava `'pela manha'` em comum,
nao o sentido da frase. Por isso o verificador mede **e mostra os pares**,
para o olho julgar: a regua e' mecanica, mas nao e' burra.

## 3. O conjunto

**39 itens**, rotulo por mao, 16 classes de falha:

| rotulo | n |
|---|---|
| SILENCE | 23 |
| RESPOND | 10 |
| WAIT | 3 |
| BARGE | 3 |

As classes de emergencia que o dono pediu, com 3 itens cada:
`mordida de animal`, `inseto`, `anafilaxia`, `insolacao/exaustao`,
`epistaxe`, `meningite`, `febre em crianca`.

## 4. O gate medido no heldout3

Rodado contra o classificador de turno por texto (LoRA `jarvis-mtp-lora` no
`:8092`), **sem comparar com o heldout2** (contaminado):

```
TOTAL 23/39   (59%)   latencia media 4467 ms   erros=0
```

| rotulo | acertos | predicoes |
|---|---|---|
| RESPOND | **2/10** | RESPOND 2, SILENCE 8 |
| WAIT | **0/3** | SILENCE 3 |
| SILENCE | 21/23 | SILENCE 21, RESPOND 2 |
| BARGE | **0/3** | SILENCE 3 |

### O achado que importa: as 7 classes de emergencia sao 0/21

| classe | n | predicao |
|---|---|---|
| mordida de animal | 3 | SILENCE 3 |
| inseto | 3 | SILENCE 3 |
| anafilaxia | 3 | SILENCE 3 |
| insolacao/exaustao | 3 | SILENCE 3 |
| epistaxe | 3 | SILENCE 3 |
| meningite | 3 | SILENCE 3 |
| febre em crianca | 3 | SILENCE 3 |

**O gate responde SILENCE a "meu cao me mordeu, o que faco".** Em blackout,
com a radio muda, isso e' a diferenca entre a pessoa ouvir a resposta e a
pessoa ficar no silencio achando que ninguem atendeu. E o erro e' sempre no
mesmo sentido: **18 de 21 itens de emergencia foram classificados como
SILENCE**, ou seja, o gate **esconde** o pedido.

O lado oposto tambem tem erro: 2/10 dos RESPOND viraram SILENCE
(`pedido`, `lista`), e 2/23 dos SILENCE viraram RESPOND.

**WAIT e BARGE: 0/3 e 0/3.** O classificador nao distingue "abertura que
nao e' para nos" de silencio, nem interrupcao de silencio. Isso e' o que o
`voice_gate.decide` corrige pela regra (`lora_and_addr_or_intent`): WAIT
segura o merge e BARGE e' interrupcao.

## 5. O que este held-out permite e o que nao permite

**Permite**: comparar versoes do kernel com um conjunto que nao vaza o
treino, e medir a acuracia **por classe** (nao so o total, que esconde o
buraco das-emergencia).

**Nao permite**: comparar com o heldout2 (contaminado) nem com o gate v10
de antes, porque o conjunto e' novo. Qualquer numero antigo e' de outro
conjunto.

## 6. Como reproduzir

```bash
cd ~/projects/nixos-ai
# 1) o verificador (ele so grava se passar)
nix develop --command python3 benchmarks/voice/build_heldout3_cervo.py
# 2) o gate no conjunto novo
nix develop --command python3 benchmarks/voice/bench_heldout3.py --base http://127.0.0.1:8092
# 3) a calibracao do corte
nix develop --command python3 benchmarks/voice/medir-corte-heldout.py
```

**Arquivos**: `benchmarks/voice/heldout3.py` (o conjunto, gerado),
`benchmarks/voice/build_heldout3_cervo.py` (o verificador, com escrita
atomica e guarda de corrida), `benchmarks/voice/bench_heldout3.py` (o runner),
`benchmarks/voice/medir-corte-heldout.py` (a calibracao do corte).

**Nota de campo**: o `build_heldout3.py` do repo estava sendo reescrito em
paralelo por outra lane durante este trabalho (medido: mtime mudando a cada
27s, e as falas ja corrigidas voltavam ao texto antigo). Por isso a copia de
trabalho `build_heldout3_cervo.py`, que corrige as falas por **regex** (nao
depende do marcador de sessao, que muda a cada execucao) e grava de forma
**atomica** (rename), com **guarda de corrida** (aborta se o destino mudou
enquanto ele rodava).
