# Catalogo item para sprite (@general subagent)

- **sessão:** `ses_eef24d7e7ffeDGSQW0DiqpIAw7`
- **quando:** 2026-10-06 10:56 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 129 (exportadas: 45)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

OBJETIVO: resolver DEFINITIVAMENTE como o client decide qual sprite mostrar para um item, e produzir um catálogo item→sprite que o agente de sprites possa usar.

PASSO 1: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/08-catalogo-item.md`.
PASSO 2: investigue. PASSO 3: reescreva com relatorio + artefatos.

## Bug que precisa ser resolvido
Um item conhecido — **gold ingot, itemId 9058** — aparece com o sprite de um TRONCO. (O dono disse que já arrumou, mas o agente de sprites PRECISA saber a regra correta para não repetir o erro em outros 100 itens.)

Fatos jáestablished que você deve VERIFICAR e depois detalhar:
- O pacote de rede **não** carrega sprite. Carrega só `u16 clientItemId` (`protocolgame.cpp:800`).
- O client resolve localmente via **`items.otbm`** (`otclient/src/client/item.cpp:286-288`).
- Id inválido no packet → id=0 → exceção (`protocolgameparse.cpp:4439-4441`).
- `canary-official/data/items/items.xml` tem **17.127 itens e NENHUM tem atributo `clientid`** (só `id`, `name`, `article`).

## O que preciso que você descubra (esta é a parte difícil)
1. Onde está o `items.otbm` que o client usa? (procure em `otclient/data/`, `otclient/modules/`, e onde `loadItems`/parser lê). Ele existe? É binário? Qual versão do protocolo?
2. **Qual é a cadeia completa**: itemId (do servidor) → o que o client faz → indice no OTB → sprite. Cada salto com `arquivo:linha`.
3. **Por que 9058 cairia em tronco?** As hipóteses a testar: (a) OTB com shift de índice; (b) o OTB tem `clientid` diferente do id do servidor; (c) o servidor envia um id que não é o mesmo do `items.xml`; (d) dup/missing entry no OTB.
4. Como VERIFICAR isso localmente sem rodar o jogo: leia o `items.otbm` (é um formato TFS conhecido — 4 bytes versão, 2 bytes uint16 count, depois ids, e opcionalmente sprites). Extraia a entrada do 9058 e diga o sprite que ela declara. **Isso é decisivo.**
5. Aponte qualquer inconsistência entre `items.xml` (17.127 itens) e o que o OTB declara (count + ids).

## Entregáveis
### A) `plans/audit-05-10/REF-ITEM-SPRITE.md`
A regra completa da cadeia, com `arquivo:linha`, e **a resposta definitiva sobre o 9058** (qual sprite ele tem e por que via tronco).

### B) `plans/audit-05-10/REF-ITEM-SPRITE.csv`
Catálogo: `item_id,nome,clientid_otb,sprite_id,group_id`
Gere para TODOS os itens do OTB (não só alguns). Este é o artefato que o agente de sprites vai consumir — precisa estar completo e correto. Faça o script ler o OTB, não adivinhar.

### C) Section no relatorio `08-catalogo-item.md`: "COMO ADICIONAR/ TROCAR UM SPRITE"
O procedimento exato, passo a passo, para o agente de sprites trocar o sprite de um item. Inclua: quais binários re-cozer, se o `appearances.dat` entra ou não, e o que fazer quando o item é novo.

REGRAS:
- Só leitura. **NÃO modifique nada. NÃO build. NÃO rode o client/server. NÃO toque em docker.**
- Extrair dados de binário é permitido (leitura). Pode escrever um script em `/home/nixos/projects/plans/audit-05-10/tools/` se precisar, mas não no repo.
- Se o `items.otbm` não existir no disco, DIGA ISSO claramente — é informação importante (implica que o client gera de outro lugar).
- Cite `arquivo:linha` e bytes/offsets quando relevante.

Mensagem final: 10 linhas — o `items.otbm` existe? qual o sprite real do 9058? e qual a regra em uma frase.

---

## · ?

I'll start by marking the file as in progress, then investigate.

---

## · ?

Passo 1 feito. Agora a investigação — primeiro localizar o `items.otbm` e o código do client.

---

## · ?

`items.otbm` não existe em lugar nenhum. Mas há `items.otb` (sem "m"). Vou investigar os dois lados.

---

## · ?

Descoberta importante: o otclient moderno **não usa `items.otbm`**. Vamos confirmar onde ele pega os item types.

---

## · ?

`loadOtb` está atrás de `#ifdef FRAMEWORK_EDITOR` — ou seja, **não é o caminho de runtime**. Vou ler o loader real.

---

## · ?

Agora tenho a cadeia real. Vou parsear o `appearances.dat` (protobuf) — é ele que tem o sprite.

---

## · ?

Vou escrever um parser protobuf puro (sem deps) em `plans/audit-05-10/tools/`.

---

## · ?

Parser funciona. Agora o veredito do9058:

---

## · ?

`9058` = **gold ingot**, sprite **201852**. Agora: qual sheet contém201852, e de onde vem o "tronco".

---

## · ?

Agora o lado servidor: como o TFS calcula o `clientId` que vai no pacote.

---

## · ?

`getViewerAwareItemId` — essa é a função-chave. Vamos ler.

---

## · ?

`getViewerAwareItemId` delega a um feature custom `ExpertPvp`. Vamos ver.

---

## · ?

O remap do ExpertPvp só afeta magic wall/wild growth — não o ingot. Vou comparar com os assets oficiais da Cipsoft e extrair o sprite real.

---

## · ?

Offset constante +7120 (assets locais rebuildados). Agora o smoking gun — comparar o9058 em **todos os backups** do `appearances.dat`:

---

## · ?

**achado**: `appearances.dat` nunca esteve errado —9058 sempre = 201852. O bug tem que estar na **sheet BMP**. Vou extrair os pixels.

---

## · ?

Sheet é 384×384, layout 0 = 32×32 → 12×12=144 slots. Vou extrair e renderizar.

---

## · ?

Extração funciona. Vou olhar os PNGs.

---

## · ?

Vou validar meu decoder: dumpar a sheet INTEIRA e o sprite vanilla oficial194732 lado a lado.

---

## · ?

Cores erradas → o canal está invertido. Vou testar as duas leituras.

---

## · ?

O decoder do client mostra: os dados descomprimidos são um **BMP com header**, não pixels crus. Vou corrigir.

---

## · ?

Confirmado: BMP com pixel data no offset **122**. Meu decode anterior estava deslocado 122 bytes. Corrigindo:

---

## · ?

Decoder correto agora: **201852 = gold ingot**, idêntico ao ref vanilla. Agora os troncos:

---

## · ?

195583 = small trunk, 195512 = thick trunk. Agora o teste decisivo: **o renumeramento local (+7120) está consistente?**

---

## · ?

`tin_207` = barra de estanho, não é tronco. Os `.bak-forno-*`/`.bak-smelt-*` são forte pista. Vou caçar o lado servidor (smelt/forno).

---

## · ?

`register_npc_type.lua:170` faz `parent:setId(clientId)` — shops podem forçar o id do item. Vou ler a semântica e auditar todas as entradas.

---

## · ?

Sem duplicatas. Agora o pipeline completo — expandindo ranges e cruzando servidor↔client.

---

## · ?

Achei um fio forte: o client tem backups até 03/10, mas o servidor tem de **04/10**. Vou casar hashes.

---

## · ?

**Achei.** O client tem o `appearances.dat` de **04/10 01:04**, mas o servidor gera um **diferente** agora. Vou comparar os9058.

---

## · ?

**Hipótese forte**: `appearances-<sha>.dat` e `catalog-content.json` são um par atômico. Se o client mistura um `appearances` antigo com sheets novas, o sprite id resolve para outra imagem. Vou provar.

---

## · ?

O modo de falha está provado (vira lixo). Agora o teste exato: **no catálogo OFICIAL 15.13, qual item possui o sprite 201852?**

---

## · ?

Confirmado: sem `Tibia.dat`/`.spr` → o client **tem** que usar o caminho protobuf. Agora o lado Lua do item:

---

## · ?

Agora vou parsear o único `items.otb` que existe no disco (o pack OTSP) — responde diretamente a pergunta 4.

---

## · ?

O OTB é formato **RME v3.55** (não TFS). Vou ler o BinaryTree e parsear direito.

---

## · ?

OTB parseado: v3.55, 2613 itens, `serverId == clientId`, **9058 ausente**. Agora: como o pipeline de assets é gerado no servidor.

---

## · ?

Vou verificar que o round-trip de repack é viável (prova que dá para re-cozer sheet).

---

## · ?

CSV gerado (42.147 itens). Agora a verificação definitiva: **comparar todos os itens contra o Cipsoft 15.13 oficial, sheet+slot.**

---

## · ?

Vou criar um verificador que valida o CSV de forma independente (render + contagem de pixels).

---

## · ?

Preciso cachear as sheets (estava decodificando42k vezes). Corrigindo:

---

## · ?

Catálogo validado end-to-end. Último detalhe para o procedimento: como o instalador decide sobrescrever.

---

## · ?

Vou confirmar os números de linha exatos que vou citar.

---

## · ?

Tenho tudo. Vou escrever os entregáveis.

---

## · ?

Agora o relatório `08-catalogo-item.md` com a seção do procedimento.

---

## · ?

Verificação final dos entregáveis e que nada foi modificado no repo.

---

## · ?

**Resposta final (10 linhas):**

1. **`items.otbm` NÃO EXISTE** — `find / -name 'items.otbm'` → vazio. A premissa do relatório original estava errada.
2. O único `items.otb` do disco é o pack de referência OTSP (`~/models/sprites/refs/ot-pack/`, RME v3.55 BinaryTree, não-TFS), tem `clientId == serverId` em 2583/2613 entradas, range 100..4361, e **9058 nem existe nele**. E `loadOtb()` é `#ifdef FRAMEWORK_EDITOR` (`thingtypemanager.cpp:630`) → o runtime nunca lê OTB.
3. **Cadeia real:** `items.xml id` → `protocolgame.cpp:800 msg.add<uint16_t>(it.id)` → `protocolgameparse.cpp:4430 getU16` → `item.cpp:267-276 setId` → `item.cpp:286-288 getThingType` → `thingtypemanager.cpp:400-406 getRawThingType` → `appearances-<sha>.dat` (protobuf) → `thingtype.cpp:112 m_spritesIndex[]` → `catalog-content.json` (faixa `firstspriteid..lastspriteid`) → `spriteappearances.cpp:280-294` (posição = `id − firstspriteid`, col = offset%12, linha = offset/12).
4. **Sprite real do 9058: `201852`** → sheet `sprites-0ed44cda…`, slot 21 (col 9, linha 1), 32×32. Extraí os pixels: **é a barra de ouro**, idêntica ao ref `gold_9058_vanilla.png`.
5. **Não reproduz "via tronco" no disco atual** — varri o `appearances.dat` instalado, o do servidor, os 21 `.bak-*` e os dois `OTServer_UPGRADE/*`: **todos** têm 9058→201852.
6. **Causa raiz real:** `appearances.dat` + `catalog-content.json` + sheets são um **par atômico**; o delta de renumeração **não é constante** (0…8355). Reproduzi: o `9058→198400` de outro build, resolvido nos sheets atuais, dá lixo — é essa a classe que produz "ingot virou tronco".
7. **Bônus acionável:** o client está **1 build atrás** do servidor (`087759b9…` vs `600c0971…`) — copie o `appearances.dat` novo para o client antes de mexer em sprite.
8. Auditoria limpa: 0 sprite órfão, 0 appearance sem sprite, 0 slot fora da grade; 4589 ids sem arte, 9191 sem item, 359 nomes divergentes (`4283` = `pile of bones` × `dead dog`).
9. Entregues `REF-ITEM-SPRITE.md`, `REF-ITEM-SPRITE.csv` (42.147 itens, validado re-derivando 4000 linhas do zero → 0 problemas) e a seção "COMO ADICIONAR/TROCAR UM SPRITE" com o procedimento e a tabela de quais binários re-cozer (`appearances.dat` sempre; `catalog-content.json`/BMPs só se criar sheet novo; nunca `items.otb`; nunca apagar `.client-assets-complete`).
10. Só leitura: nada buildado, nada rodado, nada tocado em repos/docker — scripts só em `plans/audit-05-10/tools/`, PNGs em `/tmp/opencode/`.

---

