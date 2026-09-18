# Catálogo de Modelos por API (dono 17/09) — o que é / pra que serve / pros / cons / onde usar

> **Graph:** [[ADR-004-routing-policy|/home/nixos/projects/nixos-ai/docs/architecture/ADR-004-routing-policy.md]] · [[h1_h2_h3_results|/home/nixos/projects/nixos-ai/docs/benchmarks/h1_h2_h3_results.md]] · [[../Books/memory/harness-e-fixes|/home/nixos/Books/memory/harness-e-fixes.md]]
> Pesquisa do dono (prints NVIDIA NIM + Zen/OpenRouter). Chaves via
> `/etc/litellm.env` (abstração home.nix). Invocáveis via `opencode run
> --model provider/model` e/ou fallback da cascata (`LLMClient`).
> Hábito (dono): anotar TUDO assim — modelo, código, conf, doc.

## NVIDIA NIM (infra isolada, velocidade)

### 1. GLM 5.3 Flash (NIM free)
- **O que é:** MoE multimodal nativo 320B totais (18B ativos); atenção híbrida esparsa+linear, 1M ctx.
- **Pra que serve:** classificação rápida de intenções, tool calls básicas quando Zen/OpenRouter cair.
- **Pros:** ignora maioria dos rate limits; barato em 1M ctx; visão forte.
- **Cons:** fila global massiva → **TTFT alto** (foi o que irritou e motivou a troca).
- **Onde usar no JARVIS:** fallback de classificação (não de chat interativo).

### 2. DeepSeek V4 Flash (NIM free)
- **O que é:** MoE 284B, otimizado p/ código e fluxos agênticos; v4.1 separa prefill/decode (KV cache até 8x menor), 1M ctx.
- **Pra que serve:** melhor grátis rápido p/ automações em lote (refatoração cirúrgica, massa de testes).
- **Pros:** líder de throughput em código entre "Flash"; 1M ctx.
- **Cons:** verboso; formatação de código com quirks.
- **Onde usar no JARVIS:** batch refactors, geração de testes.

### 3. Nemotron 3 Super 120B (NIM free)
- **O que é:** MoE híbrido 120B (12B/token), Mamba-2 + Transformer; 1M ctx; throughput até 7x vs densos.
- **Pra que serve:** modo architect, diagnósticos pesados (`jarvis doctor` em logs imensos).
- **Pros:** multiagente + raciocínio longo sem perder foco.
- **Cons:** chat template estrito (`enable_thinking=True`) p/ disparar reasoning.
- **Onde usar no JARVIS:** auditorias pesadas, architect.

## OpenCode Zen / OpenRouter (desenvolvimento, especialistas)

### 4. Union Alpha Free (Zen)
- **O que é:** stealth anônimo multimodal, foco agência de código; zero-retração de dados; 262K ctx.
- **Pra que serve:** tarefas agênticas pesadas com privacidade absoluta do repo.
- **Pros:** desempenho próximo a fronteira fechada; prompts não treinam modelo.
- **Cons:** disputadíssimo → quedas intermitentes.
- **Onde usar no JARVIS:** coding pesado privado.

### 5. Muse Spark 1.3 Free (Zen) — EU
- **O que é:** motor de codificação longo-horizonte da Meta, orquestração autônoma; **1M ctx**; 1.3 cortou calls repetitivas (−25% tokens em loops).
- **Pra que serve:** harness autônomo (Nightwatch) rodando horas.
- **Pros:** 1M ctx + economia em loops agênticos.
- **Cons:** prefill inicial alto p/ manter raciocínio encadeado.
- **Onde usar no JARVIS:** sessões longas autônomas, auditorias.

### 6. Ling 3.0 Flash Fin (Zen + OpenRouter)
- **O que é:** MoE 124B (~5.1B ativos), fin p/ precisão de dados/regras (finanças/lógica); 262K ctx.
- **Pra que serve:** scripts do pipeline de áudio (logs estruturados, metadados, classificação).
- **Pros:** inferência altíssima; consistência em JSON rígido.
- **Cons:** ignora nuances subjetivas em prompts longos/informais.
- **Onde usar no JARVIS:** parsing estruturado, metadados audiobook.

### 7. Nemotron 3.5 Lightning Free (Zen)
- **O que é:** destilado ultra veloz (3B ativos/token); 400+ tok/s; 1M ctx.
- **Pra que serve:** operações mecânicas de terminal, Markdown, higienização, triggers leves.
- **Pros:** throughput monstruoso.
- **Cons:** raciocínio abstrato limitado p/ arquiteturas novas.
- **Onde usar no JARVIS:** tarefas mecânicas, formatação.

### 8. Muse Spark 1.2 Free (Zen)
- **O que é:** versão anterior do 1.3; 1M ctx, comportamento conhecido.
- **Pra que serve:** fallback secundário imediato se 1.3 sofrer rate limit.
- **Pros:** estabilidade conhecida.
- **Cons:** mais verboso, mais loops redundantes de tools.
- **Onde usar no JARVIS:** fallback do 1.3.

### 9. Nemotron 3 Ultra Free (Zen)
- **O que é:** 550B totais (55B ativos), Transformer-Mamba; 1M ctx, retenção quase perfeita.
- **Pra que serve:** análise profunda de documentações imensas (vault/Obsidian).
- **Pros:** retenção em ctx gigante (Mamba-2 linear).
- **Cons:** latência inicial alta; pesado p/ conversa curta.
- **Onde usar no JARVIS:** cruzamento de docs do vault.

### 10. MiMo V2.5 Free (Zen + OpenRouter)
- **O que é:** leve, alta velocidade, interações diretas; TTFT baixo.
- **Pra que serve:** `jarvis chat` rápido (dúvidas de sintaxe/bash).
- **Pros:** latência mínima, respostas concisas.
- **Cons:** ctx menor; fraco em multiagente encadeado.
- **Onde usar no JARVIS:** chat rápido, sem gastar cota.

### 11. Ling 3.0 Flash VL (OpenRouter)
- **O que é:** variante Vision-Language do Ling 3.0.
- **Pra que serve:** `jarvis screenshot` — observar terminal/SvelteKit e sugerir layout.
- **Pros:** imagem nativa + velocidade Ling.
- **Cons:** caracteres pequenos em screenshots complexas falham.
- **Onde usar no JARVIS:** visão de UI.

### 12. Nex-N2.5-Mini (OpenRouter)
- **O que é:** compacto geral/agência leve, nex-agi; 262K ctx.
- **Pra que serve:** conversas casuais, automações curtas.
- **Pros:** rápido, baixo footprint de system tokens.
- **Cons:** matemática profunda e código abstrato limitados.
- **Onde usar no JARVIS:** CLI casual.

### 13. Nex-N2.5-Pro (OpenRouter)
- **O que é:** irmão maior do Mini, decisões lógicas; Markdown estável.
- **Pra que serve:** fallback p/ dev interativo (`jarvis dev`).
- **Pros:** segue instruções complexas com consistência.
- **Cons:** sem 1M ctx nem otimização agêntica do Spark 1.3.
- **Onde usar no JARVIS:** segundo fallback dev.

### 14. Ling 3.0 Flash Sante (OpenRouter)
- **O que é:** checkpoint Ling 3.0 tunado p/ triagem analítica (biologia/manuais).
- **Pra que serve:** RAG em manuais técnicos/livros de engenharia.
- **Pros:** throughput Flash + especialistas técnicos.
- **Cons:** escrita criativa/informal falha.
- **Onde usar no JARVIS:** RAG técnico.

## Mapeamento cascata (fallback por API)

| Camada | Modelos |
|--------|---------|
| Coding longo | Spark 1.3 → Union Alpha → Spark 1.2 |
| Dev interativo | Nex-Pro → MiMo → Mini |
| Batch código | DeepSeek V4 Flash → Ling Fin |
| Mecânico/rápido | Lightning → MiMo |
| Docs gigantes | Nemotron Ultra → Nemotron Super |
| Classificação | GLM 5.3 Flash |
| RAG técnico | Ling Sante |
| Visão | Ling VL |

## Template de anotação (hábito — tudo: modelo, código, conf, doc)

```
## <nome>
- **O que é:** ...
- **Pra que serve:** ...
- **Pros:** ...
- **Cons:** ...
- **Onde usar no JARVIS:** ...
```
