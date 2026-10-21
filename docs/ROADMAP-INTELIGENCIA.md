# ROADMAP INTELIGÊNCIA JARVIS — Expansão Cognitiva via Memória
> Base: testes ao vivo 21/10 07:02-07:07 + 16 papers baixados + SOTA da fila

## ESTADO ATUAL (testado ao vivo — 11 testes)

### ✅ FUNCIONANDO
| Capacidade | Teste | Resultado |
|-----------|-------|-----------|
| **Tool: get_time** | "que horas são?" | TOOL chamado, hora correta, streaming |
| **Tool: remember** | "guarda que eu gosto de pizza" | Fato salvo com ID no Qdrant |
| **Raciocínio básico** | "3 maçãs como 1, quantas sobram?" | "Sobram 2" correto |
| **Piada/direto** | "me conta uma piada" | Sem tool desnecessário, humor funcional |
| **Metacognição** | Todos os testes | "META: metacognição ativa" no boot |
| **Anti-confabulação** | Tavily 432 | "busca indisponível, não sei dizer" honesto |
| **Curiosidade ativa** | "quanto tá o dólar?" | Tentou web_search (quota bloqueou, mas intenção correta) |
| **Auto-correção (RETRACT)** | Bateria module tests | react() funciona no módulo |

### ❌ PROBLEMAS ENCONTRADOS
| Problema | Teste | Causa raiz |
|----------|-------|------------|
| **Recall routing** | "o que eu gosto de comer?" → web_search | 4B não diferencia recall (interna) de web_search (externa) |
| **Nome próprio** | "qual meu nome?" → "o dono" | Tool retornou dados mas 4B não extraiu "Matheus" do resultado |
| **Auto-learn facts** | "meu nome é Matheus, trabalho como engenheiro" | Não apareceu como fact novo no Qdrant (regex pode ter falhado ou background thread silenciosa) |
| **BARGE acústico** | "CALA A BOCA" por alto-falante | Nenhuma classificação BARGE no log (VAD pode não ter fechado segmento) |
| **corr_med baixo** | feed-gate | 0.08-0.15 (eco não correlaciona — alinhamento AEC_DELAY_S ainda errado?) |

## MÉTODOS COGNITIVOS DOS PAPERS (mapear → implementar)

### 1. Memória Hierárquica (MemGPT 2310.08560)
- **Hot**: context window (8k tok) = RAM
- **Warm**: Qdrant vector DB = SSD
- **Cold**: arquivos = HDD
- **Já temos**: Hot=history 60 turns, Warm=EpisodicMemory+Qdrant, Cold=vault
- **Gap**: Hot não enxerga Warm automaticamente — recall só quando o modelo decide chamar

### 2. Memory-Native Evolution (MemT-1.0, 2610.12345)
- **Gated DeltaNet-2**: memória no forward pass (não RAG externo)
- **Mixture-of-Storage**: 128K contexto, 66× redução vs KV cache
- **Aplicação**: quando existir GGUF compatível — substitui Qdrant por memória interna
- **Status**: modelo não disponível em GGUF ainda — monitorar

### 3. Self-Evolving Agent Memory (2602.06052 — survey, 218 papers)
- **Reflexão**: agente resume experiência → lições
- **Consolidação**: comprime conversas antigas → fatos atômicos
- **Dedup**: cross-model drift prevention
- **Já temos**: consolidate_memories() na classe, remember/recall/lessons
- **Gap**: job de consolidação automática (existe método, falta cron)

### 4. Hybrid Search Orchestration (SearchGym 2601.00123)
- **Top-k Cognizance**: sequência ótima ranking+filtro depende da força do filtro
- **Compositional Config Algebra**: sintetizar configs hierárquicas
- **Já temos**: HybridSearch (dense+sparse+rerank)
- **Gap**: aplicar Top-k Cognizance para otimizar recall vs filter

### 5. Harness Engineering (2605.13357, 2605.23950)
- **Binding Constraint Thesis**: harness variação > modelo variação (7.8×)
- **Agent = Model + Harness**: 98.4% é harness
- **Aplicação**: melhorar o routing de tools (recall vs web_search) é HARNESS fix, não modelo fix

### 6. Full-Duplex SOTA (D2 2610.25394)
- **521ms latência** vs nosso 3.3s (gap 6.3×)
- **Streaming encoder @ 12.5Hz** vs nosso 1.67Hz (gap 7.5×)
- **Rota**: chunk 80ms (vs 600ms atual) + encoder streaming

### 7. DuplexPO (2607.07148)
- **RL para timing**: treinar quando falar/calar com recompensa
- **Aplicação**: melhorar classificador turn-taking (LoRA r16 atual)

### 8. Heartbeat Thinking (2610.26233)
- **Especular enquanto o dono fala**: pensar ANTES do fim da fala
- **Já temos**: Heartbeat v1 (web_search especulativo no WAIT)
- **Gap**: generalizar para qualquer tool, não só search

## PRÓXIMOS PASSOS (priorizados)

### P0: Fixes imediatos (hoje)
1. **Fix recall routing**: system prompt deve ser mais explícito — "recall = buscar na SUA memória interna (preferências, fatos sobre o dono), NUNCA web_search para isto"
2. **Fix nome**: o tool resultado de recall deve formatar como lista legível, não JSON cru
3. **Fix auto-learn**: verificar se a thread background está capturando e gravando de fato

### P1: Inteligência ativa (esta semana)
4. **Memory injection automática**: ao receber utterance, fazer recall implícito (background, sem o modelo pedir) e injetar fatos relevantes no context
5. **Cron de consolidação**: job diário 3h chamando consolidate_memories()
6. **Fix BARGE acústico**: testar com TTS mais longo, verificar se o VAD fecha durante fala sobreposta

### P2: Expansão cognitiva (próxima semana)
7. **Reflexão noturna**: job que revisa conversas do dia e extrai lições (como o dono já faz com remember/lessons)
8. **Multi-hop reasoning**: para perguntas complexas, decompor em sub-perguntas e buscar múltiplas memórias
9. **Curiosidade estruturada**: quando incerto, fazer pergunta CLARA ao dono em vez de buscar às cegas

### P3: Próxima geração (quando GGUV disponível)
10. **MemT-1.0/Nano**: substituir Qdrant por memória no forward pass
11. **D2 streaming encoder**: chunk 80ms para latência ~500ms
12. **Fine-tune duplex PO**: RL no classificador de turn-taking

## PAPERS BAIXADOS E INDEXADOS (~/Books/papers/voz-cognition/)
| Paper | ID | Relevância |
|-------|----|-----------|
| MemGPT | 2310.08560 | Memória hierárquica |
| Self-Evolving Memory | 2602.06052 | Survey 218 papers sobre memória |
| Memory in Age of AI | 2512.13564 | Panorama de memória de agente |
| MemT-1.0 | 2610.12345 | Memory-native (substitui RAG) |
| SearchGym | 2601.00123 | Hybrid search orchestration |
| D2 Full-Duplex | 2610.25394 | 521ms streaming SOTA |
| Harness Engineering | 2605.13357 | Runtime como substrate |
| Stop Comparing | 2605.23950 | HV/MV = 7.8× |
| SLM Survey | 2510.03847 | SLMs em sistemas agênticos |
| Small Agents Collab | 2601.11327 | SLM+harness > modelo grande |
| Heartbeat Thinking | 2610.26233 | Especular durante fala |
| DuplexPO | 2607.07148 | RL para timing |
| DuplexCascade | 2606.19453 | Survey state machine |
| Easy-Turn | 2509.23938 | 0.5B turn-state |
| Harness Anatomy | 2609.00006 | Anatomia coding agents |
| Model or Harness | 2607.28802 | 41 modos de falha |


## SPEAKER-ID v1→v2 (21/10, pendência do dono 09:28 — IMPLEMENTADO)
- **v1 (manhã)**: IDs emergentes spk1/spk2 no asrd (cluster cos>0.80),
  prefixo [spk: X] no prompt, SYSTEM_PT PESSOAS, SALA AGORA dinâmica,
  enroll nomeado persistente (data/spk-profiles.json), WAVs por RESPOND,
  speaker-change = fronteira semântica no merge (FIFO stash).
- **v2 (13:19)**: HB mediu — MFCC 26-d cos(dora×alex)=0.999 = merge
  garantido (c0 domina 93% da norma). Upgrade: WeSpeaker ResNet34 256-d
  (modelo LOTM ~/.wespeaker, 83ms/seg, file-based via seg-wav, fallback
  MFCC). Thresholds calibrados p/ segmentos curtos (HB 13:35: intra
  0.68-0.79, cross 0.28-0.43): emergente 0.58, enrolled/is_owner 0.62.
- **Validação**: bateria HB multi-voz sintética (dora/alex) + regressão
  classify 0.927. ECAPA-TDNN (paper 2610.15978, 86.6 B³-F1) = reserva.
- **Pós-v2**: matrícula real do dono (10s) → nome no lugar de spkN.
