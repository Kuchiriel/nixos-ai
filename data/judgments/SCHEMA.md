# Dataset de judgments do dono (formato)

Para que o modelo responda **por procuração do dono**, ele precisa ser
treinado com as **decisões do próprio dono** no mesmo tipo de tarefa. Este
arquivo define o formato para que as labels sejam coletadas desde o **primeiro
item de qualificação** (o trabalho que ele já tem que fazer), sem custo extra.

## Formato (JSONL, uma linha por item)

```json
{"id": "q-0001", "context": "Tarefa: a página sobre X é relevante para a busca \"Y\"?\nDocumento: ...", "answer": "Não", "source": "uhrs-qualification", "ts": "2026-11-13T14:03:00Z"}
```

| campo | obrigatório | o que é |
|---|---|---|
| `id` | sim | identificador do item (único) |
| `context` | sim | **a pergunta como o dono a viu**, mais o documento avaliado — **sem a resposta do dono** |
| `answer` | sim | a resposta **curta** do dono: `Sim`, `Não`, ou um rótulo curto (`irrelevante`, `spam`, ...) |
| `why_dono` | não | **a razão do dono, em uma frase**: por que ele respondeu isso (é o que torna a divergência com o gabarito diagnosticável) |
| `source` | não | de onde veio (`uhrs-qualification`, `clickworker-micro`, `mindrift-eval`, ...) |
| `ts` | não | quando o dono respondeu |

**Regra do `context`**: tem que ser o contexto **real** da tarefa (a pergunta,
o documento/resultado avaliado), não uma paráfrase. Se o texto mudar na
plataforma, o modelo treina num_distribution diferente do de produção.

**A resposta NÃO vai dentro do `context`** (medido em 14/11): com a resposta
embutida no fim do contexto, o bench mediu **91,7 %** de concordância
(11/12) — o modelo lia a resposta no prompt. Com o contexto limpo, a mesma
medição deu **58,3 %** (7/12). A resposta vive só no campo `answer`. O bench
agora limpa o contexto sozinho e avisa quantos itens teve de limpar, para
que um arquivo antigo não volte a inflar o número.

## Como coletar (do mais simples ao mais preciso)

1. **Qualificação do UHRS**: o dono responde os 50 a 100 itens de teste que a
   plataforma já exige. Cada item vira uma linha do dataset, com o `context`
   copiado da tela (o `observe_screen` ajuda a ler e formatar) e a `answer` que
   o dono escolheu. É o caminho mais rápido porque **o dado já era obrigatório**.
2. **Export da conta**: Clickworker e UHRS têm histórico de conta; quando
   houver exportação, um script converte para este JSONL.
3. **Microtarefas comuns**: as que pagam pouco servem para volume, não para
   treinar (o `answer` de uma rotulagem trivial não ensina nada).

## Como treinar e medir

- **Treino**: LoRA no 4B do router (`jarvis-mtp-lora` / Laya), com os itens
  em `data/judgments/train.jsonl`.
- **Medida**: `scripts/judgment-bench.py --heldout data/judgments/heldout.jsonl`
  : concordância + intervalo de Wilson + modo recomendado.
- **Held-out criado pela ferramenta**, sem olhar o treino (é o método do bench honesto
  da voz, `benchmarks/voice/bench_heldout2.py`): sem split aleatório, porque
  split aleatório vaza. `scripts/judgment-dataset.py --make-heldout N` faz isso
  (estratificado e determinístico) e **deixa fora o item que o dono julgou duas vezes
  com respostas diferentes**: sem gabarito certo, medir contra ele é jogar uma moeda.
- **O corte do dataset é por item, não por linha** (`scripts/judgment-dataset.py`):
  quando o mesmo item é julgado duas vezes (é assim que se mede a
  repetibilidade do dono), as duas respostas ficam no **mesmo** arquivo. Se
  elas caíssem em treino e teste, o bench mediria o modelo vendo o mesmo
  item no treino.

## Por que o dono discordou (`why_dono`)

O `why_dono` é **opcional**, mas é o campo que dá sentido à divergência:

- **Concordância baixa não é evidência de dado ruim** (arXiv 2603.06865): é
  ambiguidade de instrução. O mesmo número ("concordância 50 % na classe
  2") tem duas causas opostas — o rubric está mal escrito, ou a casa está
  medindo o rótulo errado — e **só o texto dos dois lados diz qual**.
- **Treinar só no gabarito ensinaria o modelo a agradar o rubric**
  (arXiv 2607.28802). O que o dono precisa é um modelo que responda **como
  ele** — e isso se ensina com o julgamento dele, não com a resposta da
  casa.
- Na prática: quando o dono discorda do gabarito, o `uhrs-practice.py`
  pergunta **"por quê? (uma frase)"** (no teclado) ou aceita
  **"porque: ..."** na voz. Uma frase basta (o dono é PCD).
- No `judgment-bench.py`, as divergências saem **lado a lado**: o porque da
  casa e o porque do dono, e quando falta o do dono o bench diz que o item
  **ainda precisa de diagnóstico**.

## Limites (o que este dataset não resolve)

- O modelo concordance com o dono **não** o torna aprovado na plataforma: a
  aprovação e a consistência de QA são da conta, e a decisão de responder
  sozinho é do dono.
- O dataset do dono **não** é o mesmo que o dataset de conteúdo da Microsoft:
  serve para delegar a decisão dele, não para publicar rotulagem nova.
- Nada aqui automatiza clique em conta de terceiro.
- **O limite é a repetibilidade do dono**, não 100 %: se ele só concorda
  consigo mesmo em X %, o modelo não pode passar de X % (base arXiv
  2510.07978, e arXiv 2603.06865 para a escolha da métrica).
