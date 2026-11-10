# Decisões pendentes do dono (2026-11-09, uma página)

Tudo o que ficou esperando você na noite, junto, com o número que decide e o comando que
aplica. Nada aqui mexe em produção sem sua palavra.

## 1. Teto de sessão no free tier (o mais urgente)

**Problema medido**: em 6 h o upstream recusou **91** requests por `context_length`, todos
acima de 1 MB (média 5,4 MB), respondendo `limit 1048576 / actual 1541675`. As sessões
mandam prompts **493 mil tokens acima do teto da API**. Cada reenvio queima o bucket de
8 RPM, e a fila resultante (14 esperas de até 21 s) mata os clientes de timeout curto
(coord-mcp, 25 s).

**Proposta**: branch `feat/free-tier-input-cap-262144`, 5 arquivos, 71 linhas, aplica
limpo sobre o `main` atual. Medido no branch:

```
maior limit.input de sessão ..........    262.144  (era 1.028.576)
contexto exigido p/ compactar .......    314.144
contexto do modelo de compactação ....  1.048.576
folga real ...........................    734.432  (era 3.616)
```

A API continua declarando 1.048.576: o que desce é o **limiar de compactação** do
opencode, ou seja uma sessão runaway queima a cota compartilhada por um quarto do tempo.
Com a folga de 734 mil tokens, a compactação cabe com folga em vez de caber por 3.616.

**Quanto o teto evita, medido no gate vivo (10/11):** das 54 requisições que o gate
avisou em 6 h, **37 (69 %) estão acima de 1,05 MB**, que é o teto de 262144 tokens.
Desses, 35 são as de 5,4 MB (as que o upstream recusa por `context_length`) e as demais
são as de ~1,0 MB que estão tomando **504** do upstream. O p50 do tamanho avisado é
5,46 MB, ou seja ~1,37 M tokens: o teto de 262144 não é garantia teórica, cobre 69 %
do que o gate registra como problema.

**E o guard continua disparando (contador ao vivo, lido pelo endpoint `GET
/__gate/health`, 10/11 13:15):** `ctx_short_circuit` foi de **142 para 197**
(+55) e os `upstream_504` de 60 para **92** (+32) desde a mesma leitura de
ontem à noite; `requests` 1.942 para **3.002**, `retries` 180 para **214**,
`queued_seconds` 2.028 para **2.248**. Ou seja: **≈14 curtas locais por hora**
e o upstream segue degradado (504 e I/O) — o guard segura o estrago, mas cada
requisição dessas ainda ocupa o bucket de 8 RPM e força retry.

**E o custo de não ter teto, medido em uma janela só (10/11, spiritvale-pivot):** uma
janela mandou **7 requisições de 5.461.393 bytes (~1,35 M tokens) em 40 minutos**,
todas cortadas pelo context guard. Ou seja, **9,4 milhões de tokens de prompt** que
não entraram em nada, vindos de uma única janela que ficou aberta dias. O guard evita
que isso chegue ao upstream, mas não evita que a requisição ocupe o bucket de 8 RPM e
force o retry: o teto é o que corta o pedido na origem. E a contagem de 504 do gate é
confirmada de forma independente pela outra lane (69 504 e 191 retries na janela
dela, contra 73 e 195 nas minhas 6 h).

**E um fato novo que muda a conta do rebuild:** os dois fixes do provider (disjuntor
de contexto, `932a0324`, e via prioritária, `ed560081`) **já estão vivos**. O processo
do gate subiu em 09/11 06:41:53, depois dos dois commits, e a cópia do store tem os
dois (`small_bucket` e `ctx_short_circuit`). O disjuntor já cortou **176** requisições
localmente. Ou seja: o rebuild pendente **não** inclui esses dois.

```bash
cd ~/projects/nixos-ai && git merge feat/free-tier-input-cap-262144 && ./rebuild-host.sh
```

## 2. Sunshine/Moonlight só na tailnet

**Problema medido**: o firewall liberava 47984 a 48010 (TCP) e 47998 a 48010 (UDP) em
**todas** as interfaces, e o Sunshine escuta em 0.0.0.0 quando sobe (achado do Crouton
Alpha, com CVE-2026-111044).

**Proposta**: branch `fix/sunshine-somente-na-tailnet`, 1 arquivo, 9 linhas, aplica limpo.
As portas vão para a regra do `tailscale0`, o mesmo destino do opencode serve (:4599): o
streaming do celular continua pelo tailnet e a exposição some da LAN e da internet.

```bash
cd ~/projects/nixos-ai && git merge fix/sunshine-somente-na-tailnet && ./rebuild-host.sh
```

## 3. Gate de voz: wakeword (decisão já com medição)

**Medido com o backend WeSpeaker de fato carregando** (o runtime estava quebrado, isso
também foi consertado): intra-falante n=34, média 0,3526, p95 0,6435; inter-falante
n=102, média 0,3196, p95 0,5751. As distribuições **se tocam**, o limiar do gate é 0,82 e o
inter-falante tem máximo 0,8379. Logo o gate por matrícula **não segura** nesta sala e a
resposta honesta é a **wakeword**.

A matrícula do dono ficou pronta (8 takes coerentes, consistência interna 0,8552, verify
0,9006, perfil gitignored e local) e o perfil **está ativo no ASRD**. Ela não vira gate
de produção por causa da separabilidade, não por falta de dado.

**E o gatilho, medido nos DOIS caminhos (09/11, coord-naming — corrige o número de
baixo):** a bateria de trigger deu **111 de 120 alucinações (0,925)**, mas esse número
é do **whisper-server**: o bench faz `POST /inference` direto e **nunca passa pelo VAD,
nem pela segmentação, nem pelo gate do asrd**. Medi o **pipeline da casa** com o probe
novo (`scripts/voice-pipeline-probe.py`, mesmo áudio, mesma janela, comparativo
pareado, controle positivo 9/9):

| categoria | n | cru (whisper direto) | casa (VAD→segmento→gate) |
|---|---|---|---|
| silence | 23 | 8 (0,35) | **0** |
| nonspeech | 30 | 26 (0,87) | **0** |
| music | 30 | 27 (0,90) | **0** |
| reduplication | 40 | 22 (0,55) | **3 (0,07)** |
| **total** | **123** | **83 (0,67)** | **3 (0,024)** |

**E com o código de hoje (10/11, 16:13, a pilha de voz reiniciada às 16:10 com a
regra composta de "e aí" dentro), o mesmo probe com 20 clips por categoria:**

| categoria | n | cru (whisper direto) | casa (VAD→segmento→gate) |
|---|---|---|---|
| silence | 20 | 8 (0,40) | **0** |
| nonspeech | 20 | 18 (0,90) | **0** |
| music | 20 | 20 (1,00) | **0** |
| reduplication | 20 | 20 (1,00) | **1 (0,05)** |
| **total** | **80** | **66 (0,83)** | **1 (0,0125)** |

O único sobrevivente é **"Hahahaha"**: uma **risada**, que a deny-list deixa passar de
propósito (é sinal social, e a direção do dono é o agente usar risada). O controle de
fala real passou 3/3, ou seja, o caminho da casa não mata fala de verdade.

**Isso fecha a discussão da wakeword com o número mais limpo possível:** o que sobra do
caminho da casa é a fala que **parece** fala, e o caso é uma risada. Nenhuma regra de
texto pode matar essa risada sem matar a risada real de quem está falando, que é
exatamente o que a wakeword resolve (e é por isso que ela não é opcional, e por isso
que o limiar dela não pode ser chutado). Relatório: `reports/voice-pipeline/2026-11-10T161352.json`.

### E a última decisão de produto que sobrou: a risada

A lane de voz implementou uma **regra de repetição concatenada** (sem separador: a
sílaba repetida 3+ vezes) e mediu o custo dela nas 1817 transcrições reais da casa.
**Conferi rodando a ferramenta dela no meu próprio corpus (10/11):**

| regra | mata na fala real (1817) | pega o "Hahahaha"? |
|---|---|---|
| repetição **concatenada** (a nova) | **0 (0,00 %)** | **sim** |
| repetição **com separador** (a de hoje, no asrd) | 15 (0,83 %) | não |

**O número do 0 % precisa de uma ressalva, e ela é o ponto da decisão:** o corpus das
1817 falas **não contém nenhuma risada** (0 amostras de "haha", "hehe", "kkk"). Então
o "0/1817" é verdade e **não mede o custo que importa**: quando **você** ri, a regra
concatena mata a sua risada, por construção, uma vez por riso. O custo real da regra
nova é 0 no corpus medido **e 1 em cada riso seu**, e a casa mantém sinal social de
propósito (`SOCIAL_KEEP`: risada, aplauso, música, "direção do dono: o agente usa").

Ou seja, a escolha é:

- **(a) fechar mecanicamente**: a regra concatenada entra, o gatilho da risada morre e
  o caminho da casa vai de 1 caso em 80 para **0**; em troca, **você deixa de ser
  reconhecido quando ri** (e a regra não tem como distinguir a sua risada da
  alucinada).
- **(b) manter a risada**: nada muda no código, e o gatilho de uma risada alucinada
  continua passando (o assistente pode reagir a um riso que não aconteceu).

Aconselho **(b)**: o custo de (a) é uma perda recorrente de um sinal que você pediu
para usar, e o custo de (b) é uma reação espúria ocasional, que o VAD e o gate já
reduziram a uma em oitenta. Mas é decisão sua de produto, e a escolha está aqui
medida, não estimada.

**E uma correção de número da lane de voz (10/11):** o custo da regra de hoje foi
publicado como "1 fala real em 199 (0,5 %)", e a amostra era pequena demais; no
corpus inteiro são **15 em 1817 (0,83 %)**, com casos como "Não, não, não." e "sim
sim sim não foi antes não". A direção da decisão não muda, mas o número menor que
circulou não era o número.

⇒ **a casa corta 98 % das alucinações de gatilho**, e o residual é uma risada.
Ou seja: o VAD fecha silêncio/nonspeech/música, o gate fecha o resto, e **o wakeword
cobre o que sobrou** (a fala que parece real) mais a variação de nível de uma sala
real. A deny-list segue útil para o outro caso (frase alucinada sobre áudio fraco de
verdade).

**Correção de detalhe (10/11, sweep-2026-11, medição nova):** a frase "o gate de
texto só mata quando o áudio está fraco" vale só para o ramo do **léxico**. O gate
tem 9 ramos e **87 das 97 mortes não dependem de stats**. Medindo o **gate sozinho**,
sem o VAD (120 clips, seed 42, `response_format=verbose_json`, gate real extraído
verbatim para `scripts/voice_gate.py` com paridade provada por
`scripts/check-voice-gate-parity.py`):

| | alucinou | gate REAL mata | dos quais determinísticos | proxy (listas) mataria | residual |
|---|---|---|---|---|---|
| **gate sozinho** (sem VAD) | 111/120 (0,925) | 97 | 87 | 42 | **0,117** |
| **casa** (VAD → segmento → gate) | 83/123 (0,67) | — | — | — | 3/123 (0,024) |

O residual do gate sozinho são **14/120**, e é a classe que a wakeword precisa
cobrir: 5× "Música"/"Música...", 3× "Obrigado.", "Amém.", "O que é o que é o que
é...", 2 legendas (uma em inglês, uma em espanhol), "Titi-titi." e "Tchau, tchau,
tchau". **Oito dos 14 parecem fala real** (fala de verdade e sinal social, que é
justamente o que a deny-list deixa passar). Detalhe do número: o gate caiu de 0,200
para 0,117 quando a lane de voz entrou com a regra composta de "e aí" (o custo foi
medido antes de implementar, com a minha ferramenta: 1 fala real em 1817), e o ramo
`ban-hard` da lista multilingual foi **removido** por ser código morto (mata 0 dos
24). A medição completa, com o custo por regra e o que a literatura de 2026 diz
(arXiv 2606.23060: o sinal forte é probing do decoder, que o whisper.cpp não expõe;
VAD antes do decoder é a defesa principal, e a casa já tem), está em
`docs/auditoria/VOICE-GATE-MEASUREMENT-2026-11-10.md`. Os números e a receita
estão em `data/voice-fixtures/README.md`.

**O residual medido foi fechado com uma regra de texto, e ela tem custo (09/11,
coord-naming — decisão do dono, com desligar):** os 3 clipes que sobreviviam
eram **repetição de sílabas** ("Ah, ah, ah.", "Tataataataata. Uh uh uh.", "E E
E E E") e a regra de repetição que o asrd tinha só pegava a forma hifenizada
("A-a-a-a"). Medi o custo **antes** de implementar, em 199 transcrições reais
de `logs/audio`: a regra de token repetido mata **3/3** dessas alucinações e
**1/199** falas reais (0,5 %) — o caso real é "Não, não, não, não.". No mesmo
slice de 10 clipes, com a regra ligada a casa entrega **0/10** e desligada
**3/10**. A regra vive em `scripts/voice_text_rules.py` (com teste) e **se
desliga pelo ambiente** (`JARVIS_VOICE_REPEAT_RULE=0`), sem mexer em código.
⇒ Se o dono preferir não perder o "Não, não, não, não." real, é uma variável
de ambiente; o default é ligado porque o gatilho falso custa mais que 0,5 % de
fala real.

**Existe um sinal barato dentro do whisper que separe alucinação de fala real?
Medido: NÃO (10/11, sweep-2026-11, `scripts/measure-voice-signals.py`).** O gate
ignora o que o `verbose_json` expõe além de `no_speech_prob`/`avg_logprob`
(confiança por palavra, id dos tokens, duração). Medido em 111 alucinações de
gatilho contra 300 falas reais:

| sinal | AUC (maior = mais real) | custo em fala real no limiar que mata 10 % das alucinações |
|---|---|---|
| `no_speech_prob` | 0,634 | 185/300 (**61,7 %**) |
| `duration` | 0,628 | 281/300 (93,7 %) |
| `tokens_per_word` | 0,607 | 3/300 (**1,0 %**) |
| `avg_logprob` | 0,315 | 103/300 (34,3 %) |
| `min_word_prob` | 0,339 | 81/300 (27,0 %) |
| `med_word_prob` | 0,272 | 90/300 (30,0 %) |
| `cr` (compression ratio) | 0,253 | 37/300 (12,3 %) |
| `words_per_s` | 0,142 | 300/300 (100 %) |

⇒ **Os que separam (AUC 0,61-0,63) custam de 62 % a 94 % da fala real**; o único
barato (`tokens_per_word`, 1 %) tem AUC 0,607, fraco demais para virar gate. Os
sinais com AUC abaixo de 0,5 são o caso invertido (a alucina pontua **mais**),
mas no limiar que a ferramenta mede o custo é o mesmo ou pior. Base: arXiv
2606.23060 ("From Text Metrics to Model Internals") — as heurísticas internas do
Whisper deveriam marcar a alucinação e não marcam.

**Consequência para esta decisão:** o braço de áudio **dentro** do whisper não
serve ⇒ a frente que separa tem de ser **acústica** (a wakeword), e é por isso
que os **5–10 WAVs da voz real** são o insumo que falta. Sem eles, a calibração
não fecha (o limiar 0,5 não pode ser chutado).

**E o texto está no seu piso (10/11, sweep, `VOICE-GATE-MEASUREMENT-2026-11-10.md`
§4):** a mesma string aparece **idêntica** na fala real e nas alucinações
("E aí, o que é isso?" — 1 caso em cada classe) ⇒ **não existe função do texto
que mate a alucinação e preserve a fala real**: qualquer regra que feche a
alucinação paga a mesma fala real. O custo de 0,5 % da regra de repetição é o
piso, não defeito dela. O que resta é acústico (wakeword) ou interno do modelo
(probing, que exige mudar o whisper.cpp — só se a wakeword falhar).

**A segunda regra de texto, implementada com o custo medido antes (10/11,
coord-naming):** a regra de "e aí" **composto** ("e aí" no início **e** o resto
também parecer alucinação; "E aí, tudo bom?" passa). O sweep mediu o custo nas
1 817 transcrições reais: mata **1 fala real (0,06 %)** — "E aí, o que é isso?" —
e mata **10 dos 24 sobreviventes** do gate ⇒ o residual do gate sozinho cai de
0,216 para **0,126**. Implementada em `scripts/voice_text_rules.py` com teste e
**chave de desligio** (`JARVIS_VOICE_GREETING_RULE=0`), com **paridade provada**
(111/111 vereditos iguais com a regra que foi medida). Se o dono preferir não
perder o "E aí, o que é isso?" real, é uma variável de ambiente.

**CUIDADO: eu propus um watchdog para a voz e a proposta estava ERRADA (10/11,
coord-naming — corrigida aqui):** eu vi o cliente de voz ausente e concluí "morreu
sem rastro". Não era isso: o cliente **dorme de propósito** quando fica ocioso
e o log diz isso ("dormindo: LoRA off, wakeword de volta, flag removida" —
17:27:36). O desenho é: quando o cliente dorme, ele **entrega o turno ao daemon
do wakeword**, que é quem acorda a voz quando o dono fala. Um
`Restart=always` brigaria com esse desenho de dormir/acordar, então **a proposta
de watchdog está cancelada**.

**O buraco real, medido:** a entrega do turno **falhava em silêncio** — o
`systemctl --user start jarvis-wakeword.service` era feito com
`capture_output=True` e sem checar, e o cliente registrava "wakeword de volta"
**como se tivesse dado certo**. Nesta máquina a unit **não está instalada**
(existe no repo: `home-manager/modules/services/jarvis-wakeword.nix`) ⇒ o start
falha, o daemon não sobe e **a voz fica surda para sempre** enquanto o cliente
dorme. Agora o log diz a verdade (verifica `is-active` e avisa se a unit
faltar). **O que o dono precisa decidir:** (a) instalar a unit do wakeword
(config de host), (b) **calibrar o limiar do wakeword** (os 5–10 WAVs da voz
real — que é o que faz o daemon acordar a voz *no ponto certo*), e (c) decidir se
o `jarvis-heal` deve vigiar o daemon do wakeword (hoje ele reporta
`overall=degraded restarts=0` e não reinicia nada).

**O ÚLTIMO caso que sobra é uma RISADA — e a decisão é de produto (10/11,
coord-naming):** a remediação com o código de hoje (80 clipes: cru 66, casa
**1**) deixou só **"Hahahaha"**. A regra de repetição com separador (a que
está no asrd) não pega "Hahahaha", e a concatenada do sweep também não. Medi
nas **1 817 transcrições reais** (nova ferramenta
`scripts/measure-repeat-rule-cost.py`): a regra **concatenada** pega o caso
com custo **0/1817 (0,00 %)** — mas ela também **mata a risada real do dono
quando ele ri**, e a casa mantém sinal social de propósito (`SOCIAL_KEEP`:
risada/aplauso/música, "direção do dono: o agente usa"). **Escolha do dono:**
(a) fechar mecanicamente e perder o reconhecimento da risada, ou (b) manter a
risada e aceitar o gatilho dela. **Correção de um número meu:** o custo da
regra de hoje é **15/1817 (0,83 %)**, não os "1/199 (0,5 %)" que publiquei
(amostra pequena demais).

**O que ainda falta para o wakeword (09/11):** o limiar **não pode ser chutado**. No
corpus de 1 817 segmentos da casa o wakeword dispara em 6 acima de 0,5 (0,33 %), mas ao
rotular pelo transcript do log (**66 segmentos**) **nenhum é positivo** (o corpus é fala
sem a frase de wake) e o **pior negativo marca 0,9073** ⇒ com 0,5 o assistente acordaria
com o som errado. Positivo sintético **não serve**: 8 amostras de "hey jarvis" pelo
Kokoro pontuam no mesmo nível dos negativos (o limiar calibrado desce ao piso, 0,0001) —
o openWakeWord foi treinado em fala real. ⇒ **O único input que falta é do dono: 5–10
WAVs da voz real dele dizendo a frase de wake.** Com isso a calibração fecha em um
comando (o `--calibrate` do scorer da casa, que **nunca rodava**, corrigido em
`979ffbb5`):

```bash
cd ~/projects/nixos-ai && nix develop --command python3 modules/ai/ww_scorer.py \
  --models ~/.local/share/openwakeword --wav <qualquer.wav> \
  --calibrate --positive-dir <dir-com-a-frase> --negative-dir <dir-sem> \
  --target-fpr 0.01
```

**A bateria E2E: o restart era o último item, e o stack estava CAÍDO (10/11,
coord-naming):** o cliente e o ASRD morriam no import do numpy do venv karaok
sem `libstdc++.so.6` no `LD_LIBRARY_PATH` (o resolver antigo pedia
`nixpkgs#gcc.lib`, que não existe nesta nixpkgs, e a falha era engolida).
Corrigido em `scripts/asrd_env.py` (verificado no soname) e no
`duplex-voice-run.sh`; **a voz está no ar de novo**. Além disso, o ASRD
**perdia todo segmento curto** (`seg_to_text` devolvia string onde o caller
desempacota tupla ⇒ `ValueError` engolido ⇒ segmento sumia): era a causa do
0/10 "sem-segmento". Agora a injeção isolada transcreve inteira ("Qual a
previsão do tempo de amanhã?", "Liga a luz da sala."). **O que ainda não
fecha:** a bateria em série segue 0/10 porque o primeiro cenário cai em
"no-response" (o whisper erra "Jarvis" para "Serviço") e os seguintes são
injetados com o cliente ainda respondendo ⇒ falta a bateria **esperar o
cliente ficar ocioso** entre cenários. O item do dono agora é: **rodar a
bateria com o stack novo** (já está no ar) e decidir o ritmo do teste.

**O restart ficou seguro (09/11, coord-naming, commit `99ae9c63`):** o ambiente do
processo ASRD era resolvido com `nixpkgs#gcc.lib`, que **não existe** nesta nixpkgs
(o atributo é `gcc.cc.lib`), e a falha era engolida — o ASRD só vivia porque o ambiente
herdado já trazia o path de `libstdc++`. Num restart em ambiente limpo ele morre no
import do numpy (o sintoma 0/10 "sem-segmento"). Agora `scripts/asrd_env.py` resolve
os atributos que existem, **verifica o soname** no resultado, tem fallback no store e
reporta o que falta; e o ASRD imprime um erro JSON em vez de morrer calado.

### E o caminho de acordar a voz (o que a lane de voz mediu em 10/11)

O cliente de voz **dorme de propósito** quando fica ocioso (o log diz "dormindo: LoRA
off, wakeword de volta, flag removida") e a entrega do turno ao daemon do wakeword é o
desenho de acordar. O que a lane achou: **essa entrega falha em silêncio**, porque o
`systemctl --user start jarvis-wakeword.service` rodava sem conferir e o cliente
registrava "wakeword de volta" como se tivesse dado certo.

**E aqui tem uma premissa que precisa ser corrigida antes de virar proposta:** a unit
`jarvis-wakeword` **não está instalada por decisão sua**, e não por esquecimento. Em
`home-manager/home.nix:904` está `services.jarvis-wakeword.enable = false`, com o
comentário de 21/10: o duplex de voz contínua substituiu o wakeword, porque o address
gate no classificador cumpre a mesma função sem o daemon openWakeWord competindo pelo
microfone. E o substituto está implementado e vivo: `scripts/duplex-voice.py` tem
`_addressed` (408), `_gate_accepts` (500) com `GATE_MODE = "intent"` (endereço OU
intenção) e o descarte com `DROP why=gate_not_addressed` (3242).

Ou seja, instalar a unit do wakeword **desfaria uma decisão sua de 21/10**. A decisão
que sobra, com o que cada lado custa:

- **(a) manter o address gate** (o desenho de 21/10) e corrigir o handoff silencioso do
  cliente, que passa a avisar em vez de fingir que acordou. O `jarvis-heal` passa a
  vigiar o **address gate** do duplex, que é o que efetivamente acorda a voz, em vez de
  um daemon que não existe.
- **(b) reverter a decisão de 21/10** e religar o daemon do wakeword, com a calibração
  dos **5 a 10 WAVs da sua voz** (é o que faz o daemon acordar no ponto certo) e a
  proteção contra o daemon competir pelo microfone.

## 4. Rebuild para o gate (os dois fixes já estão vivos)

A frota adotou os dois (checkpoint das 06:57):

- **Disjuntor de contexto** (`932a0324`): o gate aprende o tamanho recusado por modelo e
  responde 400 local, sem reenviar. Prova: a segunda request do mesmo tamanho não chega
  ao upstream.
- **Via prioritária** (`ed560081`): pedidos de até 256 KB têm bucket próprio, com o dobro
  da taxa, e não ficam na fila dos monstros. Prova: o pedido pequeno respondeu em 0,00 s
  enquanto o grande segurava o upstream por 3 s. O fator é 2 de propósito (8 + 16 = 24
  RPM, abaixo do teto de 40 do upstream).

**Medido em 10/11: os dois já estão vivos**, apesar de o gate rodar a cópia do store. O
processo subiu em 09/11 06:41:53, depois dos dois commits (06:04 e 06:12), e a cópia
do store tem `small_bucket` e `ctx_short_circuit`. O disjuntor já cortou **176**
requisições localmente. Ou seja: **este rebuild não é para os dois fixes do gate**, e
sim para os outros itens (teto de sessão, Sunshine na tailnet, torchaudio).

```bash
cd ~/projects/nixos-ai && ./rebuild-host.sh
```

**E uma decisão de capacidade que é sua:** o gate roda a **8 RPM** (o teto efetivo
medido da chave, não os 40 nominais) e a fila de 10 a 21 s é a consequência. Os dois
fixes acima resolvem os sintomas (não há mais reenvio inútil, e as entregas da frota
não ficam na fila), mas **a vazão em si** só sobe com **mais chaves** ou com um
**relay dedicado**. Aumentar o bucket não resolve: os 40 nominais da chave não se
sustentam, e forçar o bucket só empurra o 429 para o upstream. É a mesma conta que a
opção de relay da auditoria spiritvale (o Mullvad local ou a onion hospedada).

**Aviso sobre o rebuild e a voz:** o `whisper-server` é unit systemd ✓ e reinicia com
o rebuild, mas o `duplex-voice` e o `duplex-asrd` são **processos avulsos**, de 08/11
11:02, e **não são units**: o rebuild não os reinicia. Para a bateria E2E de voz rodar com
o código novo (e com o runtime do speaker-ID no path do asrd), quem reinicia essa pilha
é a lane de voz, não o rebuild.

## 5. Já está no main, sem decisão pendente

- Runtime do speaker-ID (`torchaudio` no devShell, VAD do cache local, env do ASRD
  resolvido pelo nix): o ASRD morria no start e a bateria E2E ficava em 0/10
  "sem-segmento". Agora ele responde, com 395,6 ms de latência de endpoint.
- Bug do harness (`observed` lido fora do loop) e pandas/pyarrow no devShell: o trigger
  bench agora roda e gera relatório.
- Destino durável dos fixtures (`data/voice-fixtures/README.md`): fixture de eval não
  vive em `/tmp`.
- Relay da auditoria spiritvale: **não há VPS**, o Mullvad roda como serviço NixOS na
  sua máquina (`services.mullvad-vpn`), com a conta expirando hoje.

## 6. Pendente com a peer, não com você

Os fixtures do trigger bench: a coord-naming **recuperou o kernel do Kaggle** que os
produzia (commit `fbb71be2`) e o `--fixtures` do bench já aponta por default para o
caminho durável (`~/.local/share/jarvis/voice-trigger/`), então a bateria E2E tem base de
novo. A fonte do corpus que eu procurava está no HF e no Kaggle como
`Scicom-intl/Malaysian-Chinese-Emilia` (164 GB de storage, com os zips de áudio
part_01 a part_10), e a alternativa barata que propus continua valendo: silence e
reduplication são sintetizáveis sem download, e só nonspeech e music precisam de fonte
pequena.

**O manifesto do pacote foi recuperado dos transcripts** (09/11, `data/voice-fixtures/
MANIFEST-scicom-antihalluc-pt.md`) e diz a origem de cada categoria: `silence` 42 linhas
(zeros, download zero) · `reduplication` 1 440 (o mesmo segmento duas vezes) ·
`nonspeech` 1 168 (**FSD50K** não-fala: ruído, respiração, tosse — pequeno, com rótulo) ·
`music` 600 (fonte real) · `lexicon-synth-pt` 395 (braço positivo). O pacote inteiro
também existe pronto como espelho privado do HF (o mesmo pacote, no espelho do
proprio dono do dataset,
montado do `Scicom-intl/Whisper-Hallucination`) ⇒ **os 164 GB do
`Malaysian-Chinese-Emilia` não são necessários** para nada disso.
