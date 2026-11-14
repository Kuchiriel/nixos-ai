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
- **Medida**: `scripts/judgment-bench.py --data train.jsonl --heldout heldout.jsonl`
  : concordância + intervalo de Wilson + modo recomendado.
- **Held-out escrito à mão**, sem olhar o treino (é o método do bench honesto
  da voz, `benchmarks/voice/bench_heldout2.py`): sem split aleatório, porque
  split aleatório vaza.
- **O corte do dataset é por item, não por linha** (`scripts/judgment-dataset.py`):
  quando o mesmo item é julgado duas vezes (é assim que se mede a
  repetibilidade do dono), as duas respostas ficam no **mesmo** arquivo. Se
  elas caíssem em treino e teste, o bench mediria o modelo vendo o mesmo
  item no treino.

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
