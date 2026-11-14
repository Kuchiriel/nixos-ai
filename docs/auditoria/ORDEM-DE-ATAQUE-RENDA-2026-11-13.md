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
