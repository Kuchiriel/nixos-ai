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

⇒ **a casa corta 96 % das alucinações de gatilho**, e o residual são 3 clipes de
**repetição de sílabas** ("Ah, ah, ah.", "Tataataataata.", "E E E E E") com áudio
confiante (`avg_logprob` −0,24 a −0,43) que o léxico não pega. Ou seja: o VAD fecha
silêncio/nonspeech/música, o gate fecha o resto, e **o wakeword cobre o que sobrou**
(repetição) mais a variação de nível de uma sala real. A deny-list segue útil para o
outro caso (frase alucinada sobre áudio fraco de verdade).

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

**A voz não tem watchdog (10/11, coord-naming — decisão do dono, porque é
config de host):** o `jarvis-heal.service` (o self-heal da casa) **não vigia o
cliente de voz** (nenhuma referência a `duplex-voice` em `core/heal.py`), e o
flag `/tmp/jarvis-duplex-mode.flag` que marca "modo duplex ativo" **sobrevive
à morte do processo** (foi criado em 08/11 e o cliente morreu depois). Medido
hoje: a voz estava no ar às 12:36 e às 16:07 o cliente **havia morrido sem
rastro** (sem OOM, sem journal, sem traceback ⇒ kill externo — e o próprio
`duplex-voice-run.sh` mata órfãos ao subir, com `pkill -f`, então qualquer
subida de voz derruba a anterior). ⇒ **a voz pode ficar horas muda sem ninguém
perceber**, que é a "queda silenciosa" que a casa já registrou para outros
serviços. **Proposta (precisa do dono, é unit de usuário no host):** um
`duplex-voice.service` (ou um timer que roda `duplex-voice-run.sh` quando o
processo não está) com `Restart=always` e o `LD_LIBRARY_PATH` resolvido pelo
`scripts/asrd_env.py` (que é o que impede a morte no import do numpy) — sem
isso, o restart do dono é um evento manual e a voz é frágil por construção.

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

## 4. Rebuild para o gate (dois fixes medidos, já no `main`)

A frota adotou os dois (checkpoint das 06:57), e ambos precisam de rebuild porque o gate
roda da cópia do store:

- **Disjuntor de contexto** (`932a0324`): o gate aprende o tamanho recusado por modelo e
  responde 400 local, sem reenviar. Prova: a segunda request do mesmo tamanho não chega
  ao upstream.
- **Via prioritária** (`ed560081`): pedidos de até 256 KB têm bucket próprio, com o dobro
  da taxa, e não ficam na fila dos monstros. Prova: o pedido pequeno respondeu em 0,00 s
  enquanto o grande segurava o upstream por 3 s. O fator é 2 de propósito (8 + 16 = 24
  RPM, abaixo do teto de 40 do upstream).

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
