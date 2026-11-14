# Ordem de ataque da renda (13/11/2026)

Contexto: o dono é PCD, está há cerca de 50 dias sem benefício, precisa
comer. Isso muda a ordem de ataque: primeiro o que paga **em dias**, com o
menor esforço motor possível; o modelo treinado nas labels dele e o serviço
B2B vêm em volta, e não antes.

## 1. O que paga, em ordem de velocidade (valores medidos na pesquisa)

### 1.1. Hoje, 40 minutos, sem ferramenta nenhuma

| Plataforma | Por que é a primeira | Pagamento |
|---|---|---|
| **CloudResearch Connect** | aprovação em cerca de 1 dia (a FAQ diz que o processamento da verificação leva um dia),questionários de múltipla escolha (só formulário, sem ler página complexa) | exemplos de **US$ 14 a 16,5/h**, média US$ 10/h, piso recomendado US$ 7,50/h; saque em minutos ou horas (PayPal, vale-compras, transferência) |
| **Prolific** | o pesquisador paga no mínimo US$ 8/h (recomenda US$ 12/h), pagamento em dinheiro real, 1:1 com o pesquisador | US$ 8 a 12/h; tem fila de espera e verificação de identidade: entra na fila **hoje** |
| **Microworkers, SproutGigs** | o chão: microtarefas variadas, imediatas, em dólar | baixo, mas na hora |

Dentro disso, o que rende mais por clique é o que menos exige effort motor:
Connect e Prolific (só o formulário) antes de Clickworker/UHRS (ler e julgar).

### 1.2. Hoje, 20 minutos, e destrava o melhor microtask

**Clickworker + teste de inglês do UHRS** (gratuito). A cadeia: conta, teste de
inglês, o UHRS assessment, **50 a 100 itens de qualificação** (que são as
primeiras labels dele) e as tarefas de produção a **US$ 7 a 14/h**. A
disponibilidade é por projeto: às vezes o trabalho demora **7 a 14 dias** para
aparecer, por isso 1.1 e 1.2 rodam em paralelo.

**Restrição da casa**: com o modo vpnsec/Tor ligado, o login por proxy ou VPN
**desabilita** o acesso ao UHRS : essas sessões rodam com **egress direto**.

### 1.3. Em paralelo, 30 minutos cada: os que pagam mais

Mindrift (entrada US$ 15 a 30/h; especialista US$ 60 a 100+/h), CrowdGen
(Appen; especialista até US$ 100+/h em código, finanças, direito, linguística,
medicina, pesquisa), LXT e DataAnnotation. O perfil do dono (ML, infra, voz,
dados) bate nos projetos de código e dados. Menos volume, melhor valor.

### 1.4. O lado B2B (vender o serviço)

RWS, Toloka, Appen, OneForma e LXT vendem exatamente isto: pipeline de
anotação com humano no meio, qualidade auditada, entrega. A casa tem a pilha
(voz, tela, input humanizado, modelos locais e cloud). É o que multiplica o
valor, mas o primeiro cliente leva tempo.

## 2. O que já está construído para o caminho 1.2 e 1.3

- **`scripts/uhrs-practice.py`**: treino do rubric de relevância da Microsoft
  (o mesmo do teste real, em inglês), 12 itens de prática com gabarito e
  explicação, e **cada resposta do dono vira uma label** em
  `data/judgments/labels.jsonl` (o formato do dataset do Laya). Aceita resposta
  por **teclado** ou por **voz** (`--from-duplex`: lê a transcrição do log do
  cliente de voz, ou seja, o dono **fala** o veredito e não precisa de mouse).
- **`scripts/judgment-bench.py`**: mede a concordância do modelo com as labels
  dele (held-out escrito à mão, zero leakage, intervalo de Wilson) e diz o
  modo: **≥ 95 %** o modelo responde sozinho, **85 a 95 %** propõe e o dono
  confirma, **< 85 %** sem delegação.
- **`data/judgments/SCHEMA.md`**: o formato do dataset.

## 3. A acessibilidade é o caminho, não um enfeite

Para quem é PCD, o que decide o valor por hora é o **esforço motor por
tarefa**: por isso a ordem começa pelo formulário (Connect/Prolific), e por
isso a voz do duplex é o instrumento que torna as plataformas de maior valor
viáveis (falar o veredito em vez de clicar e arrastar). O `human_input` do
Windows e o duplex no Linux são o mesmo mecanismo visto de dois lados.

## 4. O que a literatura mudou no bench de concordância (13/11, papers já no acervo)

O acervo da casa **já cobria** o desenho da delegação, e o que faltava (a métrica
de concordância) foi preenchido com um paper novo, baixado e indexado:

| paper | o que ele muda aqui |
|---|---|
| `arxiv-2510.07978` (voiceagentbench, já no acervo) | o padrão do casa: **dois humanos concordam em 0,9680** e o judge chega num nível comparável : **o limiar da delegação é a repetibilidade do dono**, não 100 % nem 95 % absoluto |
| `arxiv-2603.06865` ("Counting on Consensus", **novo**, baixado em `~/Books/papers/` e indexado) | qual métrica usar: Cohen/Fleiss kappa e Krippendorff corrigem o acaso; concordância baixa costuma apontar **instrução ambígua**, não anotador descuidado : é o mapa das fronteiras do rubric |
| `arxiv-2607.28802` (reward hacking em RL por rubric, já no acervo) | o risco do outro lado: um modelo treinado no rubric pode aprender a **agradar o rubric** em vez de reproduzir o julgamento |
| `arxiv-2605.15104` (avaliação binária por rubric, já no acervo) | o formato do prompt de julgamento: rubric + resposta curta, sem explicação |

O que mudou no código (`scripts/judgment-bench.py`):

1. **F1 por nível** (0 a 3): o overall esconde onde a regra falha. Se o modelo
   erra sempre no "moderately", o overall parece aceitável e o problema é o
   rubric naquele nível.
2. **Teto humano**: se o mesmo id foi julgado mais de uma vez com respostas
   diferentes, o bench mostra a **repetibilidade do dono** — que é o teto real
   da delegação. : **tarefa que sobra para o dono:** julgar alguns itens duas
   vezes (o `id` do item já está no schema das labels, então isso é possível).
3. O modo recomendado passou a dizer isso na cara: o limiar é a repetibilidade
   do dono, não 100 %.

## 6. A decisão do dono sobre o modelo default (14/11) e o que ela mediu

**Decisão:** o default é o **Qwen 4B MTP** (`jarvis-mtp-lora`); o **bonsai não
pode ser o default** (ele erra em pt-BR) e, quando for usado, tem que ver
**tudo em inglês**.

**O que a medição encontrou (e por que a decisão é a correção certa):** o
router `:8080` **está fora do ar** — ele sobe, tenta carregar o bonsai e falha
por VRAM:

```
E alloc_tensor_range: failed to allocate CUDA0 buffer of size 2129452672
E llama_model_load: error loading model: unable to allocate CUDA0 buffer
E srv llama_server: exiting due to model loading error
E operator(): got exception: {"error":{"code":500,"message":"model name=bonsai failed to load"}}
```

Medido na mesma hora: VRAM **5.306 MiB usados, 548 livres**; o 4B MTP do
duplex (:8092) sozinho ocupa **3.906 MiB** (2,7 GB de pesos + KV), o whisper
**932 MiB** e os embeddings **446 MiB**. O bonsai do router pede **2,03 GB de
pesos** mais o KV de 49k de contexto, então não cabe, e o router devolve 500
em toda chamada.

**O caminho que fecha os dois (decisão do dono + VRAM):**

1. o **router sobe o 4B MTP** e o servidor próprio do duplex (:8092) **sai**,
   ficando **uma instância só** (3,9 GB + 932 MB + 446 MB ≈ 5,3 GB de 6 GB);
2. o **duplex passa a usar o router** em :8080;
3. o **bonsai fica como preset sob demanda** (nunca no boot) e, quando usado,
   **só em inglês**;
4. ⇒ o router volta a responder 200 no `/v1/chat/completions` (hoje é 500).

**O que eu já fiz sem esperar o rebuild:** o bench de concordância e o screener
pararam de pedir o modelo por nome e passam a **descobrir e testar** qual
servidor responde de verdade (o 4B do duplex em :8092 antes do router em
:8080) ⇒ com isso o medidor de concordância voltou a funcionar (medição real:
**7/12 = 58,3 %** com o 4B **sem** o LoRA fino, e o F1 por nível mostrando
que ele colapsa para "3": nível 2 e nível 1 com F1 0,00 ⇒ é exatamente o que
o treino nas labels do dono vai corrigir).

**O que é decisão do dono (config de host, rebuild):** a troca do `bootModel`
no registry (`modules/ai/models.nix`, hoje `bootModel = { host = "bonsai"; ... }`)
e a retirement do servidor :8092.

## 7. O número da delegação estava inflado pelo próprio bench (14/11)

O número que decide o modo (o modelo responde sozinho, propõe e o dono
confirma, ou não delega) estava sendo medido com um **vazamento dentro do
próprio bench**. Três defeitos, todos medidos:

### 7.1. A resposta do dono ia dentro do contexto (o maior)

O `uhrs-practice.py` gravava a label assim:

```
"context": "Query: ...\nPage: ...\nAnswer by the owner: 3"
```

e o `judgment-bench.py` mandava o contexto inteiro pro modelo. O modelo
 lia a resposta no prompt. **Medido no mesmo arquivo, na mesma hora:**

| contexto | concordância |
|---|---|
| com a resposta no fim (`Answer by the owner: 3`) | **11/12 = 91,7 %** |
| com o contexto limpo | **7/12 = 58,3 %** |

⇒ o bench estava medindo **91,7 %** onde o modelo base faz **58,3 %**. Com
91,7 % a regra da casa já diria "o modelo pode responder sozinho"; com 58,3 %
ela diz "sem delegação". **A decisão estava virada pelo vazamento.**

Corrigido nos dois lados:

- a label agora grava `context` = o que o dono **viu** (query + página) e a
  resposta no campo `answer` (antes gravava o **gabarito** do item de
  prática, nunca a resposta dele — o dataset seria o gabarito, o oposto do
  desenho);
- o bench **sanitiza o contexto** antes de chamar o modelo e avisa quantos
  itens teve de limpar, para que um arquivo antigo não volte a inflar o
  número.

### 7.2. O bench chamava o modelo duas vezes por item

Uma chamada para a concordância e outra para o F1 por nível ⇒ o dobro do
tempo numa GPU de 6 GB e o F1 media uma **amostra diferente** da
concordância. Agora é **uma chamada por item** e as duas métricas usam a
mesma resposta.

### 7.3. "unparsed" era contado como erro do modelo

Quando a transcrição da voz não era entendida, a label ficou com
`answer="unparsed"`. O bench contava isso como divergência do modelo (que
nunca errou: a fala não foi entendida), afundando a concordância por um
motivo que não é do modelo. Agora essas linhas são puladas e contadas.

### 7.4. O corte do dataset era por linha, não por item

O dono foi instruído a julgar alguns itens **duas vezes** (é assim que se
mede a repetibilidade dele, que é o teto real da delegação). O corte por
linha podia colocar as duas respostas do mesmo item em arquivos diferentes
(uma no treino, outra no teste) = leakage, o defeito que o script promete
evitar. Agora o corte é por **grupo de item**: as duas respostas ficam no
mesmo arquivo, por construção. O self-test prova isso.

### 7.5. O que a medição real diz, com o bench honesto

**7/12 = 58,3 %** com o 4B **sem** o LoRA fino, e o F1 por nível aponta o
diagnóstico: nível 3 com F1 0,71 (6/6), nível 2 e nível 1 com **F1 0,00** (o
modelo nunca diz "1", colapsa para "3"). É exatamente o que o treino nas
labels do dono tem de corrigir — e o veredito do bench (sem delegação) está
certo até lá.

## 8. Mais dois defeitos do mesmo tipo, fechados depois (14/11, tarde)

### 8.1. Medir no próprio treino

Sem `--heldout`, o bench media em `args.data`, que depois do treino é o
**próprio arquivo de treino** ⇒ o número passa a medir **memorização**, não
concordância de julgamento, e o veredito ("responde sozinho") vira um falso
verde.

Agora o bench **descobre os ids de treino** (`data/judgments/laya/train*.jsonl`
e `data/judgments/train.jsonl`) e avisa com o número exato de ids em comum
(medido: "4 id(s) deste arquivo também entraram no split de TREINO"), e o
veredito final sai marcado como medição **sem held-out**.

### 8.2. O held-out não existia e não tinha caminho de criação

O `SCHEMA.md` mandava o dono "escrever à mão" o held-out: para 50 itens, isso
é convite para errar e esquecer. Agora `scripts/judgment-dataset.py
--make-heldout N` cria o arquivo:

- **só** das labels reais do dono (os itens de prática sintéticos ficam de
  fora: eles servem para treino, não para medir generalização);
- **estratificado pela classe** (round-robin), para o held-out ter a mesma
  mistura do treino — senão o F1 por nível mede uma classe que o modelo nunca
  viu;
- **determinístico** (mesma seed ⇒ mesmo arquivo);
- e o próprio `build()` **exclui esses ids do treino** ⇒ held-out honesto
  **por construção**: não existe caminho em que o arquivo medido entre no
  treino.

**Prova (com labels falsas, 42 itens):** held-out de 12 itens com 3 de cada
classe (`{'0': 3, '1': 3, '2': 3, '3': 3}`), `train=20 test=6 calib=4
heldout=12`, **vazamento entre arquivos: nenhum**, os 12 ids do held-out
ausentes do treino, e a mesma seed reproduz o mesmo arquivo.

### 8.3. O bench lia o id do item no campo errado

O dataset no formato Laya usa `_id` (o `id` original vira `_id` na
conversão), e o bench pegava só `id`. Medido: as divergências saíam com
`id=None` e o **teto humano** (repetibilidade) colapsava todos os itens em um
grupo só — imprimia "0/1 = 0,0 %" com 4 itens medidos, quando o dono não
julgara nenhum item duas vezes. Um número de teto inventado é pior do que
nenhum: ele decide o modo de delegação. Agora o id é lido nos dois formatos.
