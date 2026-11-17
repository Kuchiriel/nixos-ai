# House offline: dependências locais e teste sem rede, num entrypoint único

(17/11/2026, coord-naming — fila da frota **ID:coord-1794921621223615**)

## O que faltava

A casa já tinha um corpus offline (N.O.M.A.D / Kiwix / FM 4-25.11 / NHS:
**18.943 docs** em FTS5, em `data/offline/corpus.db`) e o `jarvis_web_search`
**cai** nele quando a busca online falha. Mas "offline funciona" era uma
**afirmação**: ninguém checava as dependências locais, e não havia **um
comando** que provasse a operação sem rede.

## O entrypoint

`scripts/house-offline.sh` — três coisas, um comando:

```bash
scripts/house-offline.sh                    # checa + testa (o padrão)
scripts/house-offline.sh check              # só as dependências
scripts/house-offline.sh test               # só o teste sem rede
scripts/house-offline.sh query "picada de cobra"   # uma busca offline
scripts/house-offline.sh --self-test        # prova a lógica do próprio script
```

## 1. As dependências locais checadas (medido em 17/11)

| dependência | estado | o que é |
|---|---|---|
| `data/offline/corpus.db` | **ok** — 18.943 docs (24 MB) | o índice FTS5 |
| FTS5 (tabela `docs`) | **ok** | a busca por texto responde |
| `data/offline/glossary-pt-en.json` | **ok** — 205 pares | a ponte PT→EN |
| `modules/ai/jarvis/jarvis-env.sh` | **ok** | o env que o MCP e a CLI compartilham |
| embedder `:8081` | **ok** | só o fallback híbrido precisa |
| Qdrant `:6333` | **ok** | só o fallback híbrido precisa |
| chave Tavily | presente | a busca online; a **ausência** não impede o offline |

**Três checks meus estavam errados** (e o primeiro "FTS5 indisponível" era
o check, não o corpus): a tabela FTS5 é a `docs` — o `docs_idx` é o índice
interno e não aceita `MATCH` direto; o `jarvis-env.sh` fica em
`modules/ai/jarvis/`, não em `src/jarvis/`; e o glossário tem os pares em
`entries`. Corrigidos e re-medidos.

## 2. O teste sem rede é **de verdade**

O teste não é "sem usar a internet": é **sem rede**. O `unshare -n` cria um
**namespace de rede sem rota** — o processo não vê interface, não resolve
nome e não conecta em nada. Se o offline ainda responde ali, então ele
**não depende** da internet (medido, não suposto).

**Medido:** sem rede, a busca offline respondeu em **0,07–0,13 s**, com a
fonte local e a licença (`us-army-fm4-25-11-ch6.md p.5 · FM 4-25.11 ·
domínio público`).

## 3. O **fallback** (o que o dono queria provado)

Com a rede cortada, a busca online **falha de verdade** e cai no corpus
local:

```
[fonte: corpus offline N.O.M.A.D — a busca online falhou (falha de rede:
 HTTPSConnectionPool(host='api.tavily.com'...
Source: offline survival corpus (works without internet).
[28.38] us-army-fm4-25-11-ch6.md p.5 · FM 4-25.11 · dominio publico
```

Ou seja: o ramo de sobrevivência **não depende do Tavily, nem da internet,
nem de LLM** — é o que a casa precisa quando o mundo acaba.

> **Armadilha medida:** sem o `jarvis-env.sh`, o `web_search` falha com
> *"requests não instalado"* — e parece falta de rede quando é falta de
> `PYTHONPATH`. O teste do fallback usa o env canônico por isso.

## 4. O contrato do offline (o que `core/offline.py` já garante)

- **nunca inventa**: sem resultado, devolve `NO OFFLINE SOURCE` e o agente
  tem de dizer que não tem fonte local;
- todo resultado traz a **fonte** (arquivo, tipo e licença);
- funciona **sem internet e sem LLM**.

O self-test do script prova os três (inclusive o `NO OFFLINE SOURCE`).

## O que este script **não** faz

Não mexe em repo alheio, não mexe no webui, não instala nada, não altera
chave, não chama API do dono. O único efeito é **ler** o corpus local e
escrever um arquivo de saída quando o dono pede.

## Estado medido

`scripts/house-offline.sh` → **10 checagens ok, 2 testes sem rede, 0 falha**.
`--self-test` → **5/5 ok**.
