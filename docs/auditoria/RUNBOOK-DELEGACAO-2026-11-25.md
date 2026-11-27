# Runbook da delegação: do veredito falado ao número que decide

(25/11/2026, coord-naming) A máquina da trilha está pronta e **provada de ponta a ponta**.
O que falta é o **dado humano** e, com ele, rodar a sequência abaixo na ordem. Este é o
único lugar onde a sequência mora; os outros docs contam o *porquê* de cada peça.

## 0. Onde a coisa está hoje (medido)

| item | estado |
|---|---|
| provadores da cadeia | **26 checks, 0 falhas** (`scripts/provar-cadeia-judgments.py`) |
| caminho real (voz até o bench) | **verde** (`scripts/provar-pratica-ate-o-dataset.py`) |
| itens de prática | **20** (`p01..p20`), 6 da classe que o gate erra |
| registro do dono | **não existe ainda** (`data/judgments/labels.jsonl`) |
| MTP local (`:8092`) | parado: a GPU está com o A/B do lab (`f27-eval.py`, 2466 MiB) |

O bloqueio é **um só**: as ~50 labels do dono. Sem elas não há o que treinar, medir nem
delegar. O resto da sequência está testado com registro sintético e com um modelo local
falso, para não gastar GPU nem a voz da casa.

## 1. Julgar (a parte humana)

```bash
# a) os 20 itens de prática, FALANDO o veredito (sem mouse, sem digitar)
python3 scripts/uhrs-practice.py --from-duplex

# b) o item REAL da tela (clipboard primeiro, OCR da janela como reserva)
python3 scripts/uhrs-capture.py --from-duplex
```

Fala: "muito relevante", "moderadamente relevante", "levemente relevante", "nao
relevante" (o bench entende também "highly", "moderately", "slightly", "not" e 3/2/1/0).
"proxima" pula o item; "de novo" repete. Quando você discorda do gabarito, diga
**"porque: ..."** (uma frase): é o campo `why_dono`, e é o que separa "ambiguidade do
rubric" de "ruído".

Para **ensaiar** sem tocar no seu registro: `--dry-run` (não grava nada) ou
`--labels /tmp/minhas.jsonl` (grava em outro arquivo). Sem essas opções, qualquer teste
da prática grava no registro real (foi um bug, corrigido em 25/11).

Dois detalhes que mudam o número:
- **julgue o mesmo item duas vezes** (uns 10). É assim que se mede a **repetibilidade do
  dono**, que é o teto real da delegação (arXiv 2510.07978: dois humanos concordam em
  0,9680). Sem isso o bench não tem como dizer onde está o seu teto.
- o contexto que vai para o modelo é **o que você viu** (consulta + página). A sua
  resposta **nunca** vai no contexto: medido, com a resposta dentro o bench dava 91,7 % e
  sem ela 58,3 %.

## 2. O held-out (o conjunto que decide, fora do treino)

```bash
python3 scripts/judgment-dataset.py --make-heldout 10
```

Ele é **estratificado** (a mesma mistura de classes do treino), **determinístico** (mesma
seed, mesmo arquivo) e sai **só das labels reais**. O que ele **não** faz, e é o ponto:
itens que você julgou duas vezes com **respostas diferentes** ficam **fora** (não há
gabarito certo para medir) e o script diz quantos saíram.

## 3. O dataset (o formato Laya, para o pipeline de treino)

```bash
python3 scripts/judgment-dataset.py
```

Sai em `data/judgments/laya/` (`train.jsonl`, `test.jsonl`, `calib.jsonl`). O
`state` leva o **raciocínio do dono** (`why_dono`), nunca o `key` do gabarito: treinar no
gabarito ensinaria o modelo a agradar o rubric (arXiv 2607.28802). Um item julgado duas
vezes com respostas diferentes **não vira alvo** (vai para o relatório de ambiguidade); um
item repetido com a mesma resposta vale **um** item, não dois.

## 4. Treinar (o pipeline do dono)

LoRA no 4B MTP (`jarvis-mtp-lora`), com os itens em `data/judgments/laya/train.jsonl`.
O MTP precisa estar de pé, e ele **não** sobe sozinho:

```bash
bash scripts/llama-swap.sh --list          # quem roda, com VRAM
bash scripts/llama-swap.sh --start-mtp lora   # perfil da voz (:8092, com LoRA)
```

**Se a GPU estiver emprestada a outro treino, espere.** Pegá-la sem coordenação derruba
a voz da casa, e o MTP é o cérebro do duplex.

## 5. Medir (o número que decide)

```bash
python3 scripts/judgment-bench.py --heldout data/judgments/heldout.jsonl
```

 Sai: concordância, **intervalo de Wilson**, **F1 por nível** (onde a regra falha) e o
**modo recomendado**:

| concordância | modo | quem decide |
|---|---|---|
| **≥ 95 %** | o modelo responde sozinho | o dono |
| **85 a 95 %** | o modelo propõe e o dono confirma | o dono |
| **< 85 %** | sem delegação (fica como apoio de leitura e triagem) | o dono |

E o limite que o bench imprime: o limiar não é 100 %, é **a repetibilidade do dono**.

Dois avisos honestos:
- **meça no canal de voz** se o modelo for servir o duplex: o número de texto é
  otimista (medido no gate: texto 29/39 contra voz 24/39, **−12,8 p.p.**).
- **sem `--heldout` o número mede memorização**, e o bench avisa com o número exato de
  ids em comum.

## 6. O que fazer com o resultado

```bash
python3 scripts/ambiguidade.py       # qual frase do rubric consertar primeiro
python3 scripts/seletor-fracas.py    # qual item julgar a seguir (fronteira)
```

O `ambiguidade.py` mede a **ambiguidade por classe** (a classe mais contestada é a frase
mais confusa do rubric), a **instabilidade do dono** (o mesmo item com duas respostas) e
ordena as **frases a consertar** por quanto custam: consertar uma frase vale para todos
os labels futuros, e o dono não tem tempo para refazer julgamento.

## 7. Antes de confiar em qualquer número desta trilha

```bash
python3 scripts/provar-cadeia-judgments.py      # 26 checks da cadeia inteira
python3 scripts/provar-pratica-ate-o-dataset.py  # do veredito falado ao bench
```

Nenhum dos dois pede GPU, nem microfone, nem rede: o registro é sintético e o modelo é
um servidor local efêmero que responde o nível certo de cada item.

## 8. O que esta sequência NÃO faz

- Não automatiza clique nem resposta em conta de terceiro.
- Não treina no gabarito.
- Não publica o `key` do gabarito no estado de treino.
- Não compara kernels no `heldout2` (contaminado: 6/24 com fala de treino, 19/24 com
  quase-duplicata).
