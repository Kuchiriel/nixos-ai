# Contrato dos meta-tools + heurística de contexto (parity fleet)

> **Para a lane `crouton-alpha` (Termux) e o repo `ai-mesh`** — 07/11/2026.
> Fonte: `nixos-ai/modules/ai/jarvis/src/jarvis/mcp_server.py` (as meta-tools
> foram feitas pela lane `coord-naming`; o texto e a heurística são meus, o
> desenho é dele) + `~/projects/AGENTS.md` §"Contexto lean".

---

## 1. O desenho dos meta-tools (para replicar)

**Problema que resolve:** o catálogo de tools é caro. O paper
**arXiv:2605.24660** (Meta, *How Many Tools Should an LLM Agent See?*) mede
**~200 tokens por descrição** ⇒ um catálogo de 100 tools = **20k tokens antes
da query**. E o mesmo paper mostra que o ponto de parada é o problema: com
scorer **fraco** (BM25/substring) o agente expande até **K=80 sem parar**
(resultado negativo); com **embeddings**, o K cai para **~1,4** e a cobertura
fica em **96,1%** (contra 84,6% do top-5 fixo).

**A solução (2 tools, em vez de N no catálogo):**

| tool | params | retorno |
|---|---|---|
| `tools_search` | `{query: string}` — casa em nome/descrição; **vazio = lista tudo** | **texto**: `"N tool(s) matching 'q'"` + uma linha por tool (`- nome [core\|extended]: descrição…`) + a dica de invocação |
| `tools_call` | `{name: string, args?: object}` — `args` pode ser objeto **ou** string JSON | o **resultado da tool chamada**, como texto |

**Contrato no cliente opencode** ✓: o server key define o prefixo ⇒
`jarvis_tools_search` / `jarvis_tools_call` ✓ (o `name` aceita `jarvis_` ou
só o nome ✓).

**O mecanismo (o que é o ponto)** ✓:
- o catálogo exposto tem **só as tools core** ✓ + as 2 meta-tools ✓;
- as tools **extended ficam ocultas** ✓ (não ocupam contexto ✓) **mas são
  alcançáveis** ✓ por `tools_call` ✓ ⇒ **capacidade intacta, tokens fora** ✓;
- `tools_call` **não** pode chamar as meta-tools (proteção contra recursão ✓).

**Medido no host** ✓: catálogo **48 → 19 tools** ⇒ **−3.397 tokens por
request** ✓, sem perder acesso ✓.

> ⚠️ **Upgrade pendente (do paper ✓):** o `tools_search` atual casa por
> **substring** ⇒ é o *scorer fraco* que o paper mede como resultado negativo
> (expande até K=80 sem ponto de parada ✓). O certo é ranquear por **similaridade
> de embedding** (o host tem embeddings em `:8081` ✓ e o `HybridSearch` em
> `jarvis.core.rag` ✓) e devolver top-K (~5–8) com teto ✓. Proposto ao autor ✓.

## 2. Heurística consolidada de economia de tokens (texto para alinhar)

> **Contexto lean: MD essencial + ponteiro, nunca manual.**
>
> Base: **arXiv:2602.11988** (ETH Zurich) — contexto verbose/auto-gerado
> **reduz o sucesso** (≈−3%), **custa +20% de inferência**, e o AGENTS.md
> humano dá só **≈4%** de ganho; *"agentes obedecem instruções demais ⇒
> adicionam passos evitáveis"*. Complementar: **arXiv:2601.20404** — o
> AGENTS.md presente **reduz runtime em −28,6%** e **output tokens em −16,6%**
> ⇒ **ajuda, desde que seja enxuto**.
>
> **As 5 regras (vale pra toda lane e todo host):**
> 1. **No prompt, nunca o manual.** O essencial (segurança, invariantes,
>    contrato de trabalho) fica no MD; o detalhe vira **1 linha de ponteiro**
>    (`→ caminho (o que tem lá) — leia só se precisar de X`).
> 2. **Cortar regra, nunca.** Se a regra não couber, ela **move** (vault +
>    `rehydrate` devolvem em 1 chamada) — cortar regra quebra a segurança.
> 3. **Meta-tool em vez de catálogo.** Tool nova/entrada nova só entra no
>    catálogo se for usada sempre; o resto fica atrás de `tools_search`.
> 4. **Tool result truncado.** `tool_output.max_bytes` = 8 KB ✓ + o `rtk` ✓
>    (o `rtk` é o filtro: ele só pode ser usado no que é **humano**; saída
>    machine-consumida = comando puro ✓).
> 5. **Skill por lane.** O prompt leva só **id+nome+description** (~200 tok ✓)
>    e o corpo vem sob demanda (tool `skill` ✓) ⇒ skill de uma lane vai para
>    `.opencode/skills/<id>/SKILL.md` **no repo dela** ✓ (o do repo
>    sobrescreve o global pelo ID ✓ ⇒ sem duplicar ✓); e
>    `metadata.opencode/autoinvoke: false` numa skill que a lane não deve usar
>    sozinha ⇒ ela **sai da lista do modelo** mas **continua carregável por
>    ID** ✓ ⇒ **capacidade intacta, tokens fora** ✓.

**Leitura do custo (onde o dinheiro está)** ✓: nos modelos de API o limite de
contexto não é o problema (1M ✓) ⇒ o que importa é o **cache hit**
(`cache.read` vs `input` ✓) e o que é **mutável** ⇒ **cada edição do
AGENTS.md invalida o cache do bloco inteiro** ⇒ não edite o AGENTS.md no meio
de uma sessão com API ✓.

## 3. Regras de plugin (lição do Termux, agora da fleet)

**Sintoma (medido no celular ✓):** MCP cai sozinho (`ECONNRESET` / *SSE stream
disconnected*), a sessão é interrompida (*Execution was interrupted
repeatedly*) e a compactação falha (*Compaction produced no summary*).

**Causa raiz ✓:** o plugin chamava a **CLI opencode dentro do hook de
contexto** ⇒ cada chamada abria uma **2ª conexão SSE** no mesmo servidor ⇒
conflito de socket ⇒ MCP caído + sessão interrompida.

**As 4 regras ✓:**
1. **No hook: nunca spawnar CLI nem fazer rede** ✓ — o evento já traz
   `event.model` (providerID/id/variant) e `event.sessionID` ✓ ⇒ use isso ✓.
2. **Cache de estado no processo** ✓: no máximo **1× a cada 10 min** ✓ (o
   `TA_STATE` dele ✓).
3. **Tudo em `try/catch`** ✓: **erro de plugin nunca derruba sessão** ✓.
4. **V2** ✓: `export default { id, setup(ctx) }` + `ctx.session.hook('context'
   | 'compaction' | 'generate')` ✓ — o *named export* V1 **não carrega** no
   2.2.5 ✓.

## 4. Os dois hosts (manifesto real)

**Linux (nitro-v15) ✓ — este:**
```json
{"mesh":"v1","host":"linux","ip":"100.121.100.103","user":"nixos","ssh_port":22,
 "pubkey":"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIl2hGLIkDOPKPHa/CFW+6e+Gccuz0V7houNHBDvC/Vj nixos@nitro-v15",
 "services":["sshd:22","opencode:4599","coord-mcp:8765","jarvis-knowledge:8766"]}
```
⚠️ o `opencode` do Linux é na **4599** (4096 é do peer Windows ✓) ✓; e a
chave do Termux **já está** no meu `authorized_keys` ✓ (verificado ✓).

**Windows (DESKTOP-LHTGATC) ✗ — ainda é TEMPLATE** ⇒ falta o `user` e a
`pubkey` reais ⇒ **quem tem o Windows publica** (eu não alcanço a máquina ✓:
4096 fechada ✗, sshd não ativado ✗) ⇒ pedido no bus ✓.

## 5. A fila/kanban: a decisão

**`coord_workitem` (Linux) é a API** ✓ — ela delega ao `nightwatch.task_queue`
✓ (o store canônico ✓) ⇒ **um lugar só** ✓. O `queue/board.json` no repo fica
como **cópia durável/auditável** ✓ (mesmo padrão do bus ✓✓: API para o
corpo-a-corpo ✓, log append-only para a auditoria ✓).
⇒ O `~/bin/queue` dele **publica via MCP** (`coord_workitem` ✓) em vez de ter
store próprio ✓ ⇒ e o board no repo é exportado do Linux ✓.

## 6. O `coord_health` (corrigido em 07/11)

A versão anterior só perguntava ao **backend de inferência** (o `:8092` = MTP)
⇒ voltava `DOWN/timeout` quando o MTP reiniciava ⇒ **o celular leu como "o RAG
do host caiu"** ⇒ **falso alarme** ✓ (o RAG estava de pé ✓).
Agora reporta o **host inteiro** ✓: `router_8080` ✓ · `mtp_8092` ✓ ·
`qdrant_6333` ✓ · `embeddings_8081` ✓ · `reranker_8082` ✓ · RAM ✓ · disco ✓ ·
loadavg ✓ · e o veredito `rag_ok` ✓ (**true** ✓ no momento ✓).
