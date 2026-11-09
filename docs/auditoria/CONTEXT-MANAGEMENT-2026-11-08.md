# Gerenciamento de contexto de sessão longa: o que a casa precisa (2026-11-08)

Documento operacional. A nota de pesquisa (papers, com os números): `~/Books/papers/2026-11-08-context-management-sessao-longa.md`.

## 1. O incidente que motivou isto (medido 08/11)

Uma sessão da frota chegou a um pedido de **662341 tokens**. A compactação dela não
rodou, porque caiu num servidor **local de 20480 de contexto**:

```
request (662341 tokens) exceeds the available context size (20480 tokens)
```

Ou seja: o modelo encarregado de compactar era **menor que a sessão que ele deveria
compactar**. Não é escolha de política: é impossibilidade aritmética. O turno morre
(`outcome: failed`), a cota do free tier (uma chave compartilhada por todos os agentes)
é queimada enquanto a sessão cresce, e a entrega da frota para.

Outros dois fatos medidos no mesmo dia:

- O upstream do minimax **aceita prompt de ~700k tokens** (HTTP 200 medido pelo gate), e
  o `limit.input` do config está em 1.048.576. Então o limite **não** é o problema
  imediato.
- A compactação existe no opencode 2.x como rota (`POST /api/session/{id}/compact`) e
  funciona (usada com sucesso em 08/11 numa sessão que estava em `failed`; depois dela o
  `outcome` foi `succeeded` e o turno seguinte rodou). O que falta é a garantia de que o
  modelo da compactação dá conta do tamanho.

## 2. As três regras (verificadas contra os papers)

### Regra 1: contexto do modelo da compactação maior que o `limit.input` da sessão

O agente de compactação tem que ler o histórico inteiro que vai resumir. Se ele roda
num servidor com 20480 de contexto e a sessão tem 662341 tokens, a operação é
impossível, não apenas ruim. A regra é verificável em config:

```
contexto(modelo_de_compactacao) > limit.input(modelo_da_sessao)
```

No caso de hoje, a sessão usava um modelo de 1M de contexto e a compactação caiu num
servidor local de 20k. Não há ajuste de `limit` que conserte: ou o modelo da
compactação acompanha, ou a sessão longa não se recupera.

### Regra 2: a compactação é uma projeção **reversível** sobre o que já está persistido

A literatura recente (DTOC, arXiv 2609.26121) é explícita: a saída original da
ferramenta fica em **memória externa**, o contexto ativo leva **placeholder**, e a
reconstrução é sob demanda. A ablação do paper mostra que a **reversibilidade é o que
carrega o ganho**: a variante "só desabilita" degrada a acurácia, a reversível
recupera a base com custo de contexto menor.

Na casa, o substrato já existe: RAG (Qdrant: `code_index`, `books`, `memories`), vault em
git, notas em `~/Books/papers`, handoff e fila. E a frase do acervo (arXiv 2609.00006)
é o diagnóstico: **"persistent memory has replaced compaction as the frontier of context
engineering"**, com Pi e Mini-SWE-Agent **não persistindo nada além do substrato da
sessão**. Ou seja: a casa já está do lado bom da curva; o que falta é a compactação
**apontar para o artefato** em vez de parafraseá-lo.

### Regra 3: compactação sobreposta à inferência, e custo estimado antes de fixar limite

O LAM (arXiv 2609.32256) traz três coisas que a gente não tem:

1. **memory manager que preserva o prefixo cacheado e sobrepõe a compactação com a
   inferência** (a compactação não pode ser o gargalo do turno);
2. **modelo de performance que estima o custo da compactação antes de deployar**;
3. o número que serve para a decisão pendente: remover registros **antes** do prefill,
   em vez de deletá-los de um contexto já preenchido, vale **71,4x a 91,6x** de speedup
   ponta a ponta no conjunto fixo de deleção. E o ganho vem do **agendamento**, não da
   regra de deleção.

Para a decisão do dono sobre o `limit.input` dos modelos do free tier: com a cota
compartilhada, uma sessão runaway de 662k tokens queima a cota de todo mundo por
minutos. O limite de 262144 encurta essa janela sem mexer no que cabe numa sessão
normal. O `limit.input` de 1M (o valor atual) só faz sentido se a Regra 1 estiver
garantida: senão, o limite alto só compra uma sessão que não consegue se recuperar.

## 3. Como aplicar na casa

**A Regra 1 virou gate** (09/11): o check `opencode-compaction-model` (flake) lê o
`free-providers.json`, calcula o `limit.input` de cada modelo pela mesma fórmula do
headroom e **falha o build** se o contexto do `small_model` (o modelo da compactação)
não for maior que o maior `input` de sessão. Estado medido: o `small_model` é o minimax
de nuvem (contexto 1.048.576) contra o maior input de sessão de 1.028.576, margem de
20 mil tokens. Mutation check feito: apontar o `small_model` para um modelo menor faz
o check falhar com os dois números, e o revertido volta a passar. Ou seja: se alguém
declarar um modelo com input maior que o contexto do modelo de compactação, o build
quebra em vez de a compactação quebrar em produção sem ninguém ver.

- **Config**: o modelo que o opencode usa para compactar tem que ter contexto maior que
  o `limit.input` do modelo da sessão. No nosso caso, a compactação está caindo em
  servidor local porque o tier local (20k) foi escolhido para a tarefa.
- **Degradação**: se a compactação não puder rodar (modelo pequeno, cota, timeout), o
  caminho seguro é **podar o histórico na origem** (o que LAM mede como a alavanca
  grande), não tentar resumir às cegas.
- **Instrumentação**: o log precisa dizer, por turno, `tokens_before`, `tokens_after` e
  `compaction_model` com o contexto dele. Sem isso, o incidente de hoje só aparece pelo
  lado do erro ("exceeds the available context size"), sem dizer quem podia resolver.

## 4. Fontes

- arXiv:2609.32256 (LAM) · 2609.26121 (DTOC, Discovery Science 2026) · 2608.28476
  (ContextPilot, EMNLP 2026) · 2609.40118 (Persistent Context Graphs) · 2607.08032
  (rate-distortion) · 2609.00006.
- Medido na casa: log do opencode de 08/11 (14 stream errors no minimax; a sessão de
  662341 tokens; `/props` do upstream; gate com `--rpm 8 --burst 2`).
- Nota de pesquisa: `~/Books/papers/2026-11-08-context-management-sessao-longa.md`.
