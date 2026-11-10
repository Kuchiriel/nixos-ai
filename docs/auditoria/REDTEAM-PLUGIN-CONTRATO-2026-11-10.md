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
