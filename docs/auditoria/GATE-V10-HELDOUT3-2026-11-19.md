# Gate v10 (Kaggle) no heldout3, e o que o timeout do classificador mede

> **Backlog #08** (Lince) · **19/11/2026** · heldout3: **39 itens, 0
> vazamento** (o `build_heldout3.py` só grava depois de provar 0 igualdade /
> 0 containment / 0 quase-duplicata ≥ 0,55 / 0 template). O heldout2 está
> **contaminado** e não entra em nenhuma comparação.
>
> **Método:** o mesmo runner dos dois lados (`bench_heldout3.py`), o mesmo
> servidor (o MTP 4B na :8092), trocando **só** o LoRA, **3 amostras** cada.

## 1. Os números

| LoRA | acertos | acurácia | latência/item | amostras |
|---|---|---|---|---|
| **v9** (produção da voz) | **29/39** | **74,4 %** | 2.931–3.390 ms | 3 idênticas |
| **v10** (Kaggle, COMPLETE) | **12/39** | **30,8 %** | 3.076–4.740 ms | 3 idênticas |
| **v10 com timeout honesto (120 s)** | **6/39** | **15,4 %** | 3.476 ms (máx 6.448 ms) | 1 |

**Delta v10 − v9: −17 de 39 (−43,6 pontos percentuais).** O v10, treinado
no Kaggle, é **pior** que o v9 neste conjunto limpo.

### 1.1 Por rótulo (a pista do colapso)

| rótulo | v9 | v10 (timeout 8 s) |
|---|---|---|
| RESPOND | 8/10 | **10/10** |
| WAIT | 2/3 | 0/3 (todos previstos RESPOND) |
| SILENCE | **19/23** | 1/23 (22 previstos RESPOND) |
| BARGE | 0/3 | 1/3 |

O v10 acerta **RESPOND 10/10** e erra **todo o resto** como RESPOND. Isso
parece "colapso em RESPOND", não em SILENCE — mas **é o fallback**, não o
modelo (ver §2).

## 2. O defeito de instrumento: o timeout de 8 s mede transporte, não modelo

O `classify_turn` (`scripts/duplex-voice.py:669`) chama `/completion` com
**timeout de 8 s**. Medido no **v10**, o endpoint responde em **13–34 s por
item** ⇒ o timeout estoura ⇒ `classify_turn` devolve `None` ⇒ **o caller cai
no gate de regra antigo**, que responde **RESPOND**. Logo:

> **O "12/39, RESPOND 10/10" do v10 é o GATE DE REGRA, não o classificador.**
> É um veredito de transporte, e por isso é inválido.

**Prova (o texto cru do modelo, `/completion` com o prompt do classify_turn):**

| LoRA | falas testadas | resposta CRUA |
|---|---|---|
| v9 | SILENCE, SILENCE, RESPOND, WAIT | `SILENCE`, `SILENCE`, `RESPOND`, `WAIT` — **o modelo acerta** |
| v10 | SILENCE, SILENCE, RESPOND, WAIT | **`WAIT`, `WAIT`, `WAIT`, `WAIT`** — o modelo responde WAIT para tudo, em 13–33 s |

E com o timeout corrigido (120 s), o v10 dá **6/39 (15,4 %)** e **não colapsa
em SILENCE**: erra respondendo **WAIT/BARGE** onde o gabarito é SILENCE
(mordida de animal → BARGE 3/3; meningite → BARGE 3/3; inseto → BARGE 3/3).

### 2.1 A pista do `n_predict 6` (verificada: NÃO é a causa aqui)

A frota levantou que `n_predict 6` corta `SILENCE` (7 caracteres) em `SILE`.
**Medido: não é a causa do v10.** O `stop: ["<|im_end|>"]` manda o servidor
parar no fim do turno, e o **v9 devolve `SILENCE` completo** com
`n_predict 6`. O corte **acontece** com o **8B denso** (que emite `thinking`
em vez do rótulo) — e é esse caso que o doc do Codacus já mediu (0–1/39). Para
o v10, com o timeout corrigido, o rótulo chega inteiro.

## 3. A conclusão (com o que a casa já mediu)

1. **A hipótese do Codacus (35B MoE em 6 GB) está REFUTADA neste limite:**
   o especialista 4B vence em qualidade (29/39 contra 14/39 do 35B) e é
   ~15× mais rápido (4,6–5,5 s contra 72,6 s por fala). "Modelo maior" só
   ganha se o gargalo (RAM/swap/page-in dos experts) não existir.
2. **O v10 (Kaggle) não é melhor que o v9** neste conjunto limpo: −17 de 39.
   E o defeito **não é do dataset de teste**: com o timeout honesto, o v10
   erra **WAIT/BARGE** onde o gabarito é SILENCE — é o **v10 que não aprendeu
   a distinguir "fala de fundo"** (o treino do Kaggle não cobriu a fronteira
   fina), não o conjunto que está medindo errado.
3. **Corolário de instrumento (vale para toda a casa):** um timeout que corta
   o rótulo produz **veredito inválido**, e o fallback mascara isso como se
   fosse resposta do modelo. O `classify_turn` precisa de um timeout que
   distinga "demorou" de "respondeu errado", e o log precisa registrar os
   dois.

## 4. O que fica para a próxima (ação, não intenção)

- **(a)** Corrigir o `classify_turn` para medir o **modelo**: timeout
  suficiente para o classify por turno (o orçamento real da voz é
  sub-segundo, então o caminho é **classificar no merge**, não bloquear o
  tick) e **registrar `timeout` como resultado próprio**, para que um veredito
  de transporte nunca mais seja contado como resposta do modelo.
- **(b)** Rebalancear/retreinar o v10: o defeito é a fronteira **SILENCE ×
  WAIT × BARGE** (ele responde BARGE para "mordida de animal"), e o
  diagnóstico aponta **dataset de treino**, não o held-out.
- **(c)** O `n_predict` deve caber o rótulo mais longo por construção
  (`SILENCE` = 7 caracteres): o 8B denso provou que 6 corta.

## 5. Reprodução

```bash
# o comparativo (3 amostras de cada LoRA, mesmo runner, mesmo servidor)
python3 scripts/bench-v9-v10-heldout3.py
# a leitura dos numeros (fonte da verdade: a linha TOTAL do runner)
python3 scripts/bench-v9-v10-heldout3.py   # grava /tmp/opencode/v9-v10-heldout3.json
```

**Instrumento:** `scripts/bench-v9-v10-heldout3.py` (troca o LoRA, mede 3
amostras, devolve o v9) · **números crus:** `/tmp/opencode/v9-v10-heldout3.json`
· **o endpoint cru:** `/tmp/opencode/<v9|v10>-heldout3-amostra<N>.json`.
