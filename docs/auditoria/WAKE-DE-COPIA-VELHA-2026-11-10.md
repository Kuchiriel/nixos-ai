# Wake de cópia velha: o estado que a frota recebe não é o estado real (10/11/2026)

Diagnóstico medido, com o fim do loop provado. O sintoma era o watcher acordar as
sessões com um prefixo `[WATCHER hh:mm]` e um estado que não existe na máquina que
recebe, e as agents repetirem conclusões de ontem.

## 1. O sintoma

O watcher acordava a sessão com um motivo que citava a fila ou o vault:

```
[WATCHER 10:15] mudou: vault-handoff HANDOFF-2026-11-09-dedupe-na-entrega.md
```

E a fila real, na mesma hora, tinha no topo a era do dia. O resumo curto da fila era
cortado no meio da palavra (`"Resultado: NENHU..."`), o que piorava a leitura.

## 2. A medição

| pergunta | como foi respondida | resposta |
|---|---|---|
| é o watcher local? | journal do `agents-watcher.service` | **não**: os mesmos eventos de fila aparecem no journal com o horário certo (09:06:08, 09:14:24) e **sem** o prefixo `[WATCHER hh:mm]` |
| o relógio local está errado? | `date` contra `timedatectl` | não: `America/Sao_Paulo (-03)`, o prefixo das mensagens diz 10:00 a 10:15 enquanto o local diz 09:38, uns 50 min de desvio na origem |
| o estado é velho? | o hook local contra a fila real | sim: o hook local aponta a era de hoje; um dos wakes trouxe a era de 09/11 10:10 |
| de onde vem? | roster da frota contra o bus | a única lane que não está no roster local e que posta no bus é `crouton-alpha` (lane `termux/vpnsec`) |

**A cópia velha aponta justamente a era errada.** O wake que citava
`dedupe-na-entrega` (09/11 10:10) era a era que carrega a **correção antiga** do
número do gate (0,925). A lane que recebeu esses wakes repetiu esse número por
horas depois de o gate ter sido medido de verdade (0,200): não era teimosia, era
reidratação com o estado de ontem.

## 3. O que já está corrigido nesta máquina

| correção | commit | o que resolve |
|---|---|---|
| ponteiro do handoff pela **data do nome**, não pelo `mtime` | `d2e9435` (repo raiz) | uma nota reconstruída ou ressincronizada tinha `mtime` de hoje e nome de ontem, e o ponteiro apontava para o dia errado |
| evento da fila com o **commit do git** junto | `a0660b8` (repo raiz) | dá para ver de qual cópia o estado veio (`queue-top ... [git 3301d66]`) |
| read back da nota do vault, com saída 1 se ela não persistiu | `053d458b` | a fila (passo 1) aponta para a nota do vault (passo 4): agora a escrita é conferida |
| corte do resumo curto em **limite de frase** | `053d458b` | o topo da fila terminava em `"NENHU..."`, ou seja, a conclusão da era ilegível no artefato mais lido da casa |
| escrita da fila **sem perder nota** de outra lane | `7af46dde` | `flock` e verificação de hash, e o modo do arquivo preservado (`mktemp` deixava a fila em 600) |
| checker dos ponteiros da fila | `scripts/check-queue-handoff.py` | 0 quebrados hoje (eram 4) |
| dedupe por **similaridade** na entrega | `444a6f87`, `45ed1ee4`, `944b494e` | a nota repetida nem entra na fila da sessão |

## 4. O fim do loop, provado

O dedupe por similaridade (já no `main`) **pega** os wakes velhos repetidos: medido
entre os textos reais recebidos, a similaridade fica entre **0,77 e 0,87**, acima do
limiar de 0,72, e o caso "mesmo texto, hash da fila diferente" fica em 0,87. Então,
assim que a máquina que acorda **sincronizar o clone**, a repetição deixa de ser
entregue, mesmo antes de o relógio ser corrigido.

A ação foi publicada no bus (issue 12, `sweep-2026-11`): `git pull` do monorepo
(a fila e o vault são versionados) e corrigir o relógio com chrony ou NTP.

## 5. Proposta para o próximo rebuild (decisão do dono)

Um wake cujo prefixo traz um horário **mais adiantado que o relógio local** vem de
uma máquina com o relógio quebrado, e o estado que ele traz é suspeito. Um filtro no
plugin (`home-manager/files/opencode/plugins/memory.js`) que descartasse apenas as
mensagens com o prefixo `[WATCHER hh:mm]` e um horário mais de 10 minutos à frente
do relógio local economizaria o turno sem tocar em nenhum outro sinal.

Não foi implementado: o plugin vivo só muda com rebuild, e rebuild é decisão do dono.
