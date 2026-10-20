# CONTRATO: Tool-calling duplex p/ o próximo modelo (CN3/System-1)

> Prospect watcher 11:11 — "elo fraco atual". Medido na prática 18-20/10
> com o 4B-MTP (chat+tools) e o 35B-Aggressive (que NÃO chamava tools).

## O que existe hoje (4B-MTP + meta-tool `do`)

- 1 schema `do(action, input)` (~30 tok vs ~300 de 8 tools) — manter
- Execução client-side: get_time, recall, remember, web_search, status,
  shell, register_voice, guest
- Heartbeat: resultados especulativos servidos por cache fuzzy (o modelo
  nem sabe — ele chama, o executor devolve instantâneo)

## Elos fracos medidos (o que o CN3 deve CONSERTAR por treino)

1. **Tool-first não é garantido**: "que horas são?" às vezes responde
   hora inventada SEM chamar o tool (sintoma da manhã: 'Boa noite.'
   mangle → 'hora 08:15' alucinada). Prompt/few-shot ajuda; TREINO
   resolve. Regra: pergunta com dado externo → SEMPRE tool, nunca cita
   dado que não veio de tool.
2. **Markup vaza como texto**: `<function=do>` às vezes emite no
   content (o TTS filtra, mas sinal de disciplina fraca). O CN3 deve
   emitir o call NATIVO (json tool_call), zero prose envolvente.
3. **Erro de tool → estimativa**: o modelo quer "ajudar" e inventa
   quando a tool falha (Tavily 432 → "estimativa baseada em...").
   Regra treinada: tool ERRO → reporta o erro, NUNCA estima.
4. **Interrupção**: barge no meio de um tool-call pendente → o modelo
   recebe resultado parcial/abortado e deve recomeçar o raciocínio do
   turno novo, não colar o antigo.

## Contrato de emissão (formato)

- Call: `{"action": "<nome>", "input": "<arg>"}` — 1 call por turno de
  fala; múltiplos calls só se DEPENDENTES (chama 2, usa 1 resultado).
- Sem call → resposta direta ≤2 frases faladas.
- Pós-tool: resposta com o RESULTADO, sem repetir a pergunta, sem
  recitar schema.
- Entrada de contexto: resultados especulados aparecem como tool
  results completos — consumir sem re-chamar.

## Latência (orçamento do duplex)

- Classificador de turno (LoRA): ≤250ms (hoje 247ms ✓)
- 1º token pós-decisão: ≤300ms (o CN3 é MoE menor → viável)
- Tool round: dominado pelo EXECUTOR (web_search 2-3s; get_time ~ms)
  — o modelo nunca deve ser o gargalo entre call e uso.

## Treino (pipeline provado — replicável)

QLoRA r16 (Kaggle T4, dataset ~4-8k exemplos): (a) tool-first p/
perguntas de dado, (b) erro→honestidade, (c) 4-class turn-taking
(RESPOND/WAIT/SILENCE/BARGE — já existe: microturn-4b), (d) respostas
≤2 frases PT-BR faladas. Conversão GGUF local (convert_lora_to_gguf
--base config local) — pipeline do microturn-4b-lora.
