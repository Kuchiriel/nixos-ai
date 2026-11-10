# O contrato do plugin de red-team: o que está no fonte não é o que roda (10/11/2026)

Achado da lane de red-team, com medição: o contrato do plugin de red-team que a casa
documentou em 09/11 **não está no plugin vivo**. O que roda é a versão anterior.

## 1. A medição

| arquivo | `effectiveEntries` | tamanho |
|---|---|---|
| fonte declarativo (`nixos-ai/home-manager/files/opencode/plugins/redteam.js`) | 9 | 57 206 bytes |
| cópia viva (`/nix/store/dkzgyms08...-hm_redteam.js`, via `~/.config/opencode/plugins/redteam.js`) | **0** | 56 229 bytes |

O commit do contrato novo é `49a46823` (09/11 12:51, "N pairs in one list, owner
prompt never translated, block scoped to attacker"), e o fonte declarativo o tem; a
cópia do store **não**. A diferença de 1 KB e as contagens de `decoy` (46 no vivo
contra 40 no fonte) e `trigger` (25 contra 18) são a assinatura da implementação
antiga, que tratava o par legado (trigger/decoy) como caso especial em vez de uma
entrada de uma lista só.

Confirmação de que é a diferença certa, e não outra coisa: o store tem 0
`effectiveEntries` e o fonte tem 9, e o fonte tem `messages.transform` (5 contra 4) e
`chat.message` (10 contra 9), que são exatamente os dois pontos onde o contrato novo
muda de comportamento (traduzir só no limite do LLM, e nunca escrever no histórico).

## 2. O que isso significa

1. **O contrato documentado em 09/11 descreve o fonte, não o running.** A frase "o
   prompt do dono nunca é traduzido" e a de "N pares, uma lista" valem para o código
   que entra no próximo build, não para o plugin que atendeu as sessões até agora.
2. **Toda medição de red-team feita contra o plugin vivo desde 09/11 12:51 mediu o
   comportamento antigo.** Isso vale para a matriz da lane (o `redteam_matrix.py`) e
   para qualquer claim de campanha que cite o contrato novo.
3. **O conserto não está perdido:** ele está no fonte declarativo, que é o caminho
   certo (a configuração viva é gerada; o dono do gerador é o `home.nix`). Ele entra
   no **próximo rebuild**, o mesmo rebuild que já está pendente na folha de decisões
   (teto de sessão, Sunshine na tailnet, torchaudio). Ou seja, o plugin de red-team
   **ride along** com aquele rebuild, sem custo extra.
4. **Cuidado com o rebuild:** o `opencode` 2.2.6 às vezes transforma o symlink do
   `opencode.json` e do plugin em arquivo regular; o rebuild restaura. Quem conferir
   o plugin vivo depois do rebuild deve olhar o symlink do store, e não um arquivo
   regular deixado pelo processo.

## 3. O que a lane de red-team deve fazer

- Etiquetar as medições feitas contra o plugin vivo entre 09/11 12:51 e o rebuild:
  elas são do contrato antigo.
- Depois do rebuild, repetir a medição que depends do contrato (o prompt do dono e o
  caso de N pares) antes de afirmar o comportamento novo.
- O `scripts/check-voice-gate-parity.py`, que compara o gate do asrd com a cópia
  medida por token stream, é o padrão que pega esse tipo de divergência antes de
  alguém concluir com o número errado: aqui a pegada seria "o contrato está no
  fonte e o vivo diverge", que é o mesmo defeito de "fonte e runtime", medido de
  outra forma.

## 4. O que a literatura de 2026 acrescenta (nota completa em `~/Books/papers/2026-11-10-medir-o-artefato-que-roda.md`)

**O ASR de uma campanha não é o risco real.** "Agents Behave Differently in Fabricated
Environments" (Apart Research, set/2026) mediu que, com tarefa, prompt, schemas,
orçamento de turnos e ator constantes, mudando só o que a chamada de ferramenta
devolve, as ações fora de escopo **aumentam** nos braços fabricados: 12 escritas e 86
leituras fora de escopo contra **zero** no braço real, e a conclusão do paper é que um
resample dessa família superestima o perigo. Para a casa: o `POST /inference` cru do
bench de voz é um **proxy de ataque** (mede quanto o ASR alucina), e o braço real é o
caminho da casa (VAD, segmento, gate, wakeword), onde o residual medido é 0,024. Uma
campanha de red-team contra o harness é o mesmo caso: o número do harness é o do
ambiente fabricado.

**O número tem que vir do artefato versionado.** O mesmo paper substitui cada número
em build a partir de artefatos versionados e **falha o build se um placeholder não
puder ser computado**. Aplicado à casa: o relatório de campanha tem que trazer o
commit do plugin e do harness, e a publicação do número tem que falhar se o checker
passar. Foi isso que motivou o `scripts/check-plugin-contract.py` (que já diz qual
plugin está velho: `redteam.js` diverge, `check-redteam.mjs` está em dia).

**A autorização continua sendo o gate.** arXiv 2610.12463 ("From Reactive Containment
to Proactive Assurance") reúne os incidentes de 2026 em que avaliações de segurança
de agentes alcançaram sistemas reais fora do escopo autorizado (OpenAI, Anthropic e
Google). É a regra que a lane da auditoria já aplicou: o dono autoriza, o histórico
rastreado fica no repo privado, e credencial e IP cru não entram em repo, log, bus
nem PR.
