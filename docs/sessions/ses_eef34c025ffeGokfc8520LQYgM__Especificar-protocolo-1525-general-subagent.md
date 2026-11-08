# Especificar protocolo 1525 (@general subagent)

- **sessão:** `ses_eef34c025ffeGokfc8520LQYgM`
- **quando:** 2026-10-06 10:38 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 158 (exportadas: 9)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

OBJETIVO: produzir uma ESPECIFICAÇÃO AUTORITATIVA do protocolo de rede do client↔server (OTClient 1525 / TFS 13.x) que outro agente possa consultar sem ler código.

PASSO 1: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/07-protocolo.md`.
PASSO 2: investigue (leitura/grep). PASSO 3: reescreva com relatorio + artefato.

## Escopo da investigação
Duas pontas:
- Server: `/home/nixos/projects/canary-official/src/server/network/protocol/` (protocolgame.cpp, protocolgameteleport.cpp) e `src/game/server/*.cpp|hpp` (as tabelas de opcode ficam em `server.cpp`/`definitions.hpp`)
- Client: `/home/nixos/projects/otclient/src/client/protocolgame.cpp` (envio) e `src/client/protocolgameparse.cpp` (parse, `parseOpcodes`)

## Entregáveis (este é o ponto — o artefato importa)

### A) `plans/audit-05-10/REF-PROTOCOLO-1525.md`
Tabela de **TODOS** os opcodes server→client e client→server que você conseguir mapear:
| opcode | nome | quem envia | onde é gerado/parseado (`arquivo:linha`) | bytes de payload |

Para os ~20 mais importantes, detalhe o **layout byte a byte** (tipo e ordem dos campos, endianness).，重点:
- `GameServerLogin`/`GameServerLoginChallenge` — o handshake RSA+XTEA
- `GameServerInventory`/`AddInventoryItem` — COMO O ITEM CHEGA (o looktype/sprite é enviado aqui? isso responde um bug de sprite)
- `GameServerOutfit`/`GameServerChangeOutfit`
- `GameServerCreatureOutfit`
- Onde exatamente entra o bloco customizado **0xA1** (GameSandboxSkills) e qual a fórmula de tamanho (a doc do outro agente diz: `u8 total`, por skill `u8 nameLen + nome + u16 level + u16 base + u8 percent`)

### B) `plans/audit-05-10/REF-PROTOCOLO-1525.json`
O mesmo em JSON parseável:
```json
{ "opcodes": { "0x65": {"nome":"GameServerX","dir":"s2c","payload":"layout em texto"} } }
```

### C) `plans/audit-05-10/REF-PROTOCOLO-REGRA.md`
**As regras que evitam dessincronização** — esta é a parte que mais vai poupar tempo de outro agente:
1. Como o tamanho de um login packet é codificado (`writeHeaderSize`, a fórmula `(size-4)/8`, e por que isso importa)
2. Onde o parser pode desalinhar se um campo opcional faltar, e como detectar
3. **Ordem obrigatória dos campos** no login packet e onde o bloco customizado pode ser inserido sem quebrar
4. Regras de versionamento: o que acontece se o server enviar um campo que o client não espera, ou vice-versa
5. Um checklist de depuração de dessync: que logs comparar lado a lado (client vs server) para achar o ponto exato

REGRAS DURAS:
- **NAO modifique nada. Só leitura/grep. NÃO build. NÃO rode o client/server. NÃO toque em docker.**
- Só documente o que **ler no código**. Se um opcode você não conseguiu confirmar lendo, marque `NAO-CONFIRMADO` — não invente layout. Um payload errado neste documento é PIOR que um ausente, porque outro agente vai confiar.
- Cite `arquivo:linha` em toda afirmação.
- Se um opcode tiver layout ambíguo (ex.: o tamanho depende de dado variável), DOCumente a fórmula, não um número fixo.

Mensagem final: 10 linhas — quantos opcodes mapeou, e diga explicitamente quais layouts você NÃO conseguiu confirmar.

---

## · ?

I'll start by marking the file as in progress, then investigate the protocol code.

---

## · ?

Investigation complete. Now generating the merged opcode table.

---

## · ?

Now writing the deliverables.

---

## · ?

Now the JSON artifact.

---

## · ?

Now the rules document — the highest-value artifact.

---

## · ?

Now updating the main reference doc with the corrected `0x43` finding.

---

## · ?

Now the final report (07-protocolo.md), replacing the EM_ANDAMENTO placeholder.

---

## · ?

Mapeei **333 opcodes** (197 server→client + 136 client→server) e fechei **21 layouts byte-a-byte**; os outros **211** ficaram marcados `NAO-CONFIRMADO` em vez de inventados.

**Correção de premissa:** "TFS 13.x" não existe aqui — o servidor é Canary com `CLIENT_VERSION = 1525` (`canary-official/src/core.hpp:18`), **sem enum de opcodes** (literais hex inline), sem `src/game/server/`, sem `protocolgameteleport.cpp` (teleport é `case 0x73` inline).

**Layouts que NÃO consegui confirmar** (não use para gerar código):
- 211/333 opcodes no total — majoritariamente market/store/imbuement/cyclopedia/bestiary/tracker/VIP/forge/prey.
- `0x75 GameServerTakeScreenshot`: a feature `GameEventPayload` confirma que existe um **byte seletor**, mas não li o corpo do handler.
- `0x6E GameServerOpenContainer`: li até `hasParent`; **a lista de itens do container ficou por ler**.
- `0xDA CyclopediaCharacterInfo`: 16 emissores multiplexados; não li o seletor nem nenhum.
- Perfis legados 1100/860: existem com layouts totalmente diferentes; **não documentei nenhum**.
- Ordem exata checksum/length no header do challenge (não rodei nada; o cliente consome 6 bytes fixos, então não importa).
- `0x0B GameServerGMActions`: handler não lido, emissor não achado.
- Emissor real de `0xFE`: a única ocorrência de `addByte(0xFE)` é um **dado** em `AddItem`, não o opcode.

**Achado que muda prioridade do outro agente:** o gate `0x43`/`GameFeature_t::SandboxSkills=137` **nunca é exercitado** — `sendFeatures()` exige `otclientV8 > 0` e o cliente não implementa `getLoginExtendedData`; `sendOTCRFeatures()` exige OS ≥ 10 e `modules/gamelib/game.lua:46` manda `setCustomOs(2)`. Hoje a invariante "servidor escreve o bloco 0xA1 ⟺ cliente lê" depende de **duas edições não coordenadas** (`protocolgame.cpp:10096-10157` e `features.lua:35`). Detalhe em `REF-PROTOCOLO-REGRA.md` §3.4/§5.4.

**Sprite:** o pacote **não** carrega sprite — só `u16 clientItemId` (`protocolgame.cpp:800`); o cliente resolve localmente via `items.otbm` (`item.cpp:286-288`), e id inválido → `id=0` → exceção (`protocolgameparse.cpp:4439-4441`). Sprite errado é sempre id errado ou OTB errado, nunca protocolo.

---

