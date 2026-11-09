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
pareado, controle positivo 5/5):

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
outro caso (frase alucinada sobre áudio fraco de verdade). Detalhe: o gate de texto
só mata quando o áudio está fraco (`ns>0,35` ou `lp<-0,45`), que é o caso raro na
alucinação de gatilho — por isso o "0,22" e o "0,925" medidos antes são do caminho
cru, não da casa.

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

E a **bateria E2E ainda precisa do restart do stack de voz**: o processo do ASRD
(pid 2807337) e o `duplex-voice` (pid 2806473) são de **08/11 11:02** (código antigo),
mesmo com o fix do ASRD já no `main` — por isso a bateria continua em 0/10
"sem-segmento" enquanto o ASRD novo responde em 395,6 ms.

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
