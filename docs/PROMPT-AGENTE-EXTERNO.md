# Prompt para outro agente trabalhar neste repo (cole e cole)

> Motivo deste arquivo: um agente apagou a coleção de produção `code_index`
> (1263 pontos) enquanto portava funções. As proteções já existem no
> código — este texto só aponta para elas. Nenhuma das regras aqui é
> opinião nova: são as que a validação do build já cobra.

---

## Prompt

Você vai trabalhar neste repositório NixOS (`~/projects/nixos-ai`). Leia
`AGENTS.md` antes de tocar em qualquer coisa. Além disso:

**1. NUNCA apague dado. Nunca.**

Não use `rm`, `delete_collection`, `drop_collection`, nem um script que
faça isso, em nada que não tenha sido criado por você nos últimos minutos.
Se uma tarefa parecer exigir remoção, **pare e reporte** — não improvise.

Existe uma ferramenta feita exatamente para isso, com verificação:

```python
from jarvis.core.safe_archive import archive_then_delete
from jarvis.providers.vector_store import QdrantStore

store = QdrantStore(Config())
r = archive_then_delete(
    store, "memories", "memories_backup_2026-09-25", [123, 456],
    dry_run=True,                                  # SEMPRE comece assim
    provenance={"_archived_at": "2026-09-25", "_motivo": "motivo"},
)
print(r.as_dict())   # so remova se r["safe"] for True
```

A ordem é obrigatória e não negociável: **copiar → ler de volta →
conferir contagem e hash → só então remover.** Já aconteceu de o Qdrant
aceitar a escrita (HTTP 200) e não gravar nada; quem confiou no status
perdeu 6 pontos. `safe` só é `True` com `verified` **e** `removed ==
requested`.

**2. Coleções de produção — não escreva, não leia para deletar, não renomeie:**

`code_index`, `memories`, `books`, `vault`, e as por espaço:
`pessoal_code`, `pessoal_memories`, `moe_code`, `moe_memories`,
`qwen4b_code`, `qwen4b_memories`.

Elas são o **estado do usuário**. `memories` é a memória do agente;
`code_index` é o índice de código; `pessoal_*` e `moe_*` são protegidos
(cifrados) e insubstituíveis.

**3. Testes só tocam em `jarvis_test_*`.**

Config de teste tem que ser **derivada**, nunca literal:

```python
cfg = dataclasses.replace(Config(), qdrant_collection_code="jarvis_test_algo")
```

O guard `modules/ai/jarvis/tests/test_test_isolation.py` reprova o build
se um arquivo de teste mencionar `qdrant_collection_code` sem `replace(`
ou com literal de produção. Ele existe porque alguém apagou 1263 pontos
de `code_index` rodando teste. Não burle o guard: se ele reprovar, o
código está errado, não o guard.

**4. Antes de commitar:** `nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -q --tb=short`
e `git add -A` + conferir `git ls-files` (o flake só enxerga arquivo
versionado). A validação do `./rebuild-host.sh` roda os testes e
reprova o build se algo quebrar — então um teste que passa local e
falha no rebuild é problema seu, não do build.

**5. Não faça rebuild** (`./rebuild-host.sh`) sem o dono pedir: ele ativa
a configuração e reinicia serviços. O dono autoriza caso a caso.

**6. Se a tarefa for ambígua quanto a dados:** reporte o que você
encontrou e pare. Perder 1263 pontos custa mais que atrasar um port.

---

## Contexto do port que estava sendo feito

O dono pediu para portar funções do "pi coding agent". Ao portar:
- mantenha a API pública (assinaturas) — quem chama não deve quebrar;
- **escreva teste junto**, com fixture `jarvis_test_*`;
- rode a suíte antes de commitar;
- se a funçãoported toca em memória/RAG/vault, use `safe_archive` para
  qualquer limpeza — nunca delete direto.
