# Roteiro: o que fazer hoje para começar a receber (13/11/2026)

Para o dono. Sem jargão, sem teoria. Cada passo diz **onde**, **o que fazer**,
**quanto tempo leva** e **como você sabe que deu certo**. Se um passo estiver
travado, **pule para o próximo** e volte depois.

Total: **1 h 30 min de trabalho efetivo** para deixar quatro portas abertas
(uma delas paga em dias). O resto eu construo em paralelo.

Regra de ouro desta página: **primeiro o dinheiro que chega rápido**, depois o
dinheiro que precisa de treino. Nada de esperar.

---

## Antes de começar (10 min, uma vez só)

**1. Separe um e-mail só para isso** (exemplo: `seunome.trabalho@...`), que
você ainda não usou em nada de serviço de dados. Motivo: as plataformas
reconhecem e-mail de|work; misturar com o e-mail de outros lugares gera
conflito de conta.

**2. Tenha um método de pagamento pronto.** No Brasil, os que funcionam e são
rápidos:
- **PayPal** (o mais aceito; saque para conta bancária ou cartão);
- **Payoneer** (usado por ySense e outros);
- **Airtm** (o CrowdGen cita);
- **transferência bancária** (o CloudResearch Connect paga direto assim).

Se você já tem um, não mexa. Se não tem, abra o PayPal (10 min) — é o que
destrava mais portas.

**3. Decida onde você vai fazer isso.** O detalhe técnico que decide: o
**UHRS bloqueia o acesso quando o login passa por proxy ou VPN**. A máquina da
casa está com o modo vpnsec/Tor ligado, e por isso o login no UHRS **falha**.
⇒ **Faça o passo 2 (Clickworker/UHRS) no Windows**, ou com o modo vpnsec
desligado por alguns minutos. O resto (Connect, Prolific, Mindrift) funciona
de qualquer jeito.

---

## Passo 1 — CloudResearch Connect (25 min): o que paga mais rápido

**Onde**: `https://www.cloudresearch.com/products/connect-for-participants`
(ou pesquise "CloudResearch Connect participate").

**O que fazer**
1. Criar conta com o e-mail do passo "Antes de começar".
2. Preencher o perfil (país Brasil, idioma, o que você sabe fazer). Seja
   preciso em "skills": ML, infra de modelos, voz, dados, Python, MT5. É isso
   que te coloca em estudo pago mais.
3. Verificação de identidade (a FAQ diz que leva cerca de um dia).
4. Entrar no painel e **aceitar o primeiro estudo que aparecer** (os exemplos
   pagos estão entre US$ 14 e 16,5 por hora; a média da plataforma é US$ 10).

**Como sei que deu certo**: o painel mostra "Pending projects" e os valores em
dólar; o pagamento entra por PayPal/transferência em minutos ou horas.

**Atalho de esforço**: aqui é só clicar em opções e responder. Se cansar,
feche e volte — os estudos ficam no painel.

---

## Passo 2 — Clickworker + teste de inglês do UHRS (20 min): destrava US$ 7 a 14/h

**Onde**: `https://www.clickworker.com/` (cadastro é **gratuito**; qualquer um
que cobre taxa é golpe).

**O que fazer**
1. Criar conta (e-mail do passo 0).
2. Preencher o perfil e ir em **Assessments** (o mesmo menu do guia do UHRS).
3. Fazer o **teste de inglês** e o **UHRS assessment** (ele inclui um teste de
   inglês e a configuração de um **LiveID próprio**, separado do seu e-mail
   normal — anote esse e-mail, é onde o acesso ao UHRS acontece).
4. Quando aparecerem os itens de qualificação (50 a 100), **responda-os
   você mesmo**: eles são o seu primeiro dataset de treinamento (veja o passo
   5).

**Como sei que deu certo**: no painel do Clickworker aparece o banner do
UHRS ("Click here for more tasks on UHRS!") e os itens de qualificação.

**Atenção**: os HITs de UHRS às vezes aparecem **7 a 14 dias** depois. Não
esperar por eles: siga o passo 3 e 4 em paralelo.

---

## Passo 3 — Prolific (15 min): entra na fila e paga bem

**Onde**: `https://www.prolific.com/participants`

**O que fazer**
1. Criar conta e **verificar a identidade** (eles exigem).
2. Entrar na **waitlist** (não há acesso imediato).
3. Quando o convite chegar, escolher os estudos longos e bem pagos (a
   plataforma exige que o pesquisador pague **no mínimo US$ 8/h** e recomenda
   US$ 12/h).

**Como sei que deu certo**: confirmação de e-mail e o painel mostrando os
estudos elegíveis.

---

## Passo 4 — Mindrift e CrowdGen (30 min): o maior valor por hora

**Onde**: `https://mindrift.ai` e `https://crowdgen.com`

**O que fazer**
1. Mindrift: criar conta e se candidatar a um projeto de **nível de entrada**
   (US$ 15 a 30/h; se o seu domínio for forte, especialista paga US$ 60 a
   100+/h). Diga que você trabalha com **modelos de linguagem, voz e dados**.
2. CrowdGen (Appen): criar conta e se candidatar a projeto de **código, dados
   ou pesquisa** — são os que pagam até US$ 100+/h.

**Como sei que deu certo**: os dois mostram "projects" e o valor por hora de
cada um antes de você começar.

---

## Passo 5 — Treinar o Laya com as suas respostas (eu preparo, você faz 10 min)

**O que já está pronto** (eu fiz): `scripts/uhrs-practice.py` treina o
**rubric de relevância** da Microsoft (o mesmo do teste real, em inglês), com 12
itens de prática e gabarito explicado. Cada resposta sua vira uma **label**
(é o dataset do Laya). E aceita **por voz**: você fala o veredito e o bench
pega do log do cliente de voz (sem mouse).

**O que fazer**
1. Rodar o treino de prática (12 itens, ~10 min): `python3 scripts/uhrs-practice.py --from-duplex`
   (com o cliente de voz no ar) ou sem `--from-duplex` para digitar.
2. A cada item, ele diz o gabarito e o porquê — é o treino que faz o teste
   real passar.

**Como sei que deu certo**: o placar no fim (e as labels em
`data/judgments/labels.jsonl`).

---

## Passo 6 — O que eu sigo fazendo em paralelo (você não precisa fazer nada)

- **Bench de concordância** (`scripts/judgment-bench.py`): quando você tiver
  ~50 labels, eu rodo o held-out e digo o número que decide se o Laya pode
  responder sozinho, propõe e você confirma, ou não delega.
- **Port kit do Windows** (branch `feat/mcps-para-windows` do repo `mt5`):
  tela, mouse/teclado e leitura de arquivo para o opencode do Windows, com o
  contrato de cada ferramenta — pronto para quando você abrir o outro agente
  lá.
- **Voz como interface de anotador**: o duplex já escuta e decide; falta só
  ligar o item ao rótulo (quando você quiser, eu faço).

---

## Se algo travar

- **Login do Clickworker/UHRS falha ou pede proxy**: é o vpnsec. Faça no
  Windows ou desligue o modo por alguns minutos (comando na casa:
  `vpnsec/scripts/mode.sh off`).
- **Pedem documento/taxa**: golpe. Nenhuma dessas plataformas cobra para
  entrar.
- **Estudo aparece mas é ruim paga**: pule. Conect/Prolific têm muitos
  estudos por hora; escolha os de maior valor.
- **Você ficou sem tempo hoje**: faça só o Passo 1 (Connect). Ele é o de
  pagamento mais rápido e o de menos esforço.

## Os números, para você conferir a expectation

| plataforma | valor por hora | quando paga | esforço |
|---|---|---|---|
| CloudResearch Connect | US$ 14 a 16,5 (média 10) | minutos/horas | baixo (formulário) |
| Prolific | US$ 8 a 12 | dias | baixo (formulário) |
| UHRS (Clickworker) | US$ 7 a 14 | semanal (a Clickworker paga por semana) | médio (julgar relevância) |
| Mindrift | US$ 15 a 30 (especialista 60 a 100+) | por projeto | médio (escrever/avaliar) |
| CrowdGen/Appen | até US$ 100+ | por projeto | alto (especialista) |
