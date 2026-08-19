# Achados do legado Manjaro (inspeção 08/2026)

> Inspeção direta do snapshot montado em `/mnt/manjaro/kuchiriel/Projects/AI_SYSTEM/`
> (não só pesquisa na internet). Foco: o que o legado fazia de inteligência
> barata (fast paths, RiveScript, audiobook) e memória — e o que portar para
> o JARVIS NixOS.

---

## 1. RiveScript — fast paths determinísticos (o "extrato do mínimo")

O legado usava **RiveScript** (não regex) como camada de resposta instantânea,
sem LLM. Arquitetura:

- **`orchestrator/rivescript_router.py`** (1649 linhas) — roteador que carrega
  o "cérebro" de `.rive` em subdiretórios **por prioridade** (filters/generated
  = menor, core = maior), com cache por mtime e **macros Python**
  (`change_voice`, `system`, `math`, `time`, `audiobook`...).
- **`orchestrator/brain/core/audiobook.rive`** (192 linhas) — controle de
  audiobook com **TOPICS**: comandos globais ("leia o livro X") entram no topic
  `audiobook`, onde comandos curtos ("para", "pausa", "continua", "próximo
  capítulo") são respondidos sem LLM. `{topic=audiobook}` / `{topic=random}`
  fazem a troca de contexto.
- **`orchestrator/brain/core/fast_paths.rive`** (435 linhas) — arrays PT/EN com
  variações de acento (`! array memoria = memoria memória memòria`), troca de
  voz, info do sistema — tudo pattern-matching puro.
- **`emergency_commands.rive`** — comandos de emergência (prioridade máxima).

**Resultado medido pelo legado**: *"Fast paths: 100% hit rate (73.2ms avg)"*
(do remember.sh) — respostas instantâneas para comandos simples, LLM só quando
necessário. Exatamente a filosofia "extrair o máximo do mínimo".

### O que isso significa para nós
Nosso `jarvis ask` (roteador em cascata) **já implementa essa ideia em Python**
(doctor/nixos/rag determinísticos antes do agent/LLM). O gancho natural:
adicionar uma camada de **pattern-matching explícito** (regex ou mini-RiveScript)
para comandos de voz curtos (audiobook, mídia) — o RiveScript legado serve de
referência de sintaxe e organização (topics, prioridade de diretórios, macros).

---

## 2. Audiobook — o que existia

- **`jarvis/enhanced_audiobook.py`** — leitor com TTS (XTTS, 24kHz), SFX timing,
  preservação narrativa, `~/.jarvis/reading_state.json` (progresso), PID file.
- **`core/book_indexer.py`** — indexa livros em **ChromaDB** (RAG de livros),
  `smart_chunk` por sentenças para TTS (chunks >1500 chars divididos).
- **`core/book_extractor.py`** — extração de texto de livros + chunking.
- **`jarvis/audiobook_modules/audio_player.py`** — player de áudio.
- **Config Qdrant do nosso flake já reserva a coleção `books`** — o espaço
  para portar isso existe.

### "Audiobook header"?
Não há um arquivo chamado "header" — o que existe é o **controle por voz com
topics** (audiobook.rive) + **progresso persistido** (reading_state.json). O
"header" provavelmente se refere ao estado/cabeçalho de leitura que o sistema
mantinha entre sessões (livro atual, posição) — isso é **memória de estado de
tarefa**, não memória episódica.

---

## 3. Memória — o que o legado realmente tinha

| Mecanismo | O que era | Formato |
|---|---|---|
| **`experience_buffer.py`** | Lições de auto-correção: `add_lesson(error, fix, task)` → JSONL; `get_lessons(query)` com **keyword match simples** | `~/.jarvis/experience_buffer.jsonl` |
| **`REMEMBER.md` + `remember.sh`** | Protocolo de contexto: regras críticas ("CARDINAL SINS") lidas antes de cada sessão | Markdown |
| **`reading_state.json`** | Progresso do audiobook (estado de tarefa) | JSON |
| **RAG de código/livros** | Conhecimento (arquivos/livros indexados) | ChromaDB/NumPy → Qdrant |

**Conclusão sobre memória episódica:** o legado **não tinha** memória episódica
de verdade (sessões, fatos, preferências do usuário). Tinha:
1. **Conhecimento** (RAG) — já temos, e melhor (híbrido).
2. **Lições/experiência** (experience_buffer) — keyword match simples; é um
   começo de memória episódica, mas primitivo.
3. **Contexto manual** (REMEMBER.md) — humano-in-the-loop, não automático.

**RAG ≠ memória episódica.** São coisas diferentes:
- RAG = *conhecimento* (documentos/código, estático, consultável).
- Memória episódica = *experiência* (o que aconteceu, sessões passadas, decisões,
  preferências do usuário, erros já corrigidos).

O `experience_buffer` legado é a ponte entre os dois: guarda *experiências* num
formato que pode ser *consultado* — mas com keyword match, sem embeddings. O
nosso caminho (documentado no assessment, Fase 7): SQLite + embeddings sobre os
eventos, consultável como o RAG. Não é "já temos a solução mais elegante" —
temos a metade do conhecimento; falta a metade da experiência.

---

## 4. O que portar / o que descartar

**Portar (com adaptação):**
- Conceito de fast paths com prioridade de diretórios (→ nosso roteador, já feito
  em Python; RiveScript fica como referência de sintaxe para comandos de voz).
- `experience_buffer` (→ Fase 7: memória episódica com embeddings).
- Audiobook: `book_indexer`/`book_extractor`/`enhanced_audiobook` (→ Fase 8:
  voz/TTS; a coleção `books` já existe no nosso Config Qdrant).
- Topics do RiveScript (contexto "estou lendo X" → comandos curtos sem LLM).

**Descartar:**
- ChromaDB (→ Qdrant, já escolhido).
- Keyword match do experience_buffer (→ embeddings).
- XTTS/Coqui (→ avaliar piper/koel no host; XTTS é pesado e exige GPU).
- REMEMBER.md como protocolo manual (→ o `jarvis ask`/doctor já automatiza;
  mas a ideia de "regras críticas" vira o system prompt do agente).

---

## 4b. Segundo passe — o que ainda não tínhamos mapeado (08/2026)

Varredura completa do snapshot revelou **mais** inteligência valiosa:

### Cascade planner→critic (`agents/ai-cascade-v3`, `cascade_planner.py`, `cascade_critic.py`)
Orquestração multi-agente para tarefas de código:
1. **Planner** (Qwen 3B barato) gera plano `STEP:`/`FINAL:` com
   **"MANDATORY CONSTRAINTS (PAST LESSONS)"** injetadas do experience_buffer
   ("se uma lição passada avisa contra uma mudança, VOCÊ DEVE evitá-la").
2. **Critic** (Llama 3.3 70B) valida o plano contra as mesmas lessons
   (veredito `PASS|FAIL` + razão em <20 palavras) antes de executar.
3. Execução passo a passo com meta-routing (API/LOCAL por passo).

**Portado**: o nosso `Agent` agora injeta as `PAST LESSONS` da memória
episódica no system prompt como constraints obrigatórias antes de agir
(`_lessons_block` em `core/agent.py`), e o CLI conecta a memória ao agente
(fecha o ciclo: errar → aprender → lembrar → não repetir). Validado ao vivo:
perguntando "qual foi o erro do storage do qdrant?", o agente respondeu com a
lição real (`unknown variant on_disk` → `rm -rf storage`) — dado da memória,
não alucinação.

### STT calibrado (`jarvis/jarvis-stt-fast.py`)
faster-whisper com VAD para ambiente ruidoso: `threshold=0.5`, `beam_size=3`,
`vad_filter=True`, `min_speech_duration_ms=250`, `min_silence_duration_ms=1000`,
`speech_pad_ms=400`; GPU `int8_float16` com fallback CPU `int8`. Bate com a
nossa doc de calibração de áudio — pronto para a Fase 8.

**Validado por pesquisa 2026**: Whisper Large V3 continua o padrão multi-língua
(99+, incl. PT-BR); Turbo = 6x mais rápido (WER 7.75 vs 7.4); Distil-Whisper é
English-only (não serve). faster-whisper (CTranslate2) segue recomendado para
CPU. **Decisão do legado confirmada** — implementado em `core/voice.py`
(pacote `jarvis-voice`).

### TTS comparison (`docs/TTS_COMPARISON.md`)
Pesquisa 2025/2026 já feita: **Kokoro** (ONNX, CPU, <200MB RAM, PT-BR/EN,
real-time — mas sem emoção) vs **Chatterbox** (emoção, tags `[laugh]`/`[sigh]`,
zero-shot clone, MIT, 350M — requer Python 3.11, nota 9/10) vs Fish Speech
(multi-língua). O legado usava Kokoro; Chatterbox é a evolução emocional para
audiobooks. Referência pronta para Fase 8.

**Validado por pesquisa 2026**: Kokoro-82M é o **"eficiência king"** — lidera
a Realtime TTS Arena (Artificial Analysis), 82M params, <1GB, roda em CPU,
RTF 0.03, Apache-2.0, 54 vozes/8 línguas. Chatterbox segue para cloning
(0.5B, MIT, ~4-6GB). Novos: Qwen3-TTS (Apache, novo default do ecossistema HF)
e MOSS-TTS Nano (0.1B, CPU-only). **Kokoro do legado confirmado** — já em
nixpkgs (binary cache, declarativo de graça); `speak`/`voice` implementados.

### Benchmarks reais (`BENCHMARKS_BEFORE_AFTER.md`)
Fast paths: **19.7s → 134ms** (greetings), 19s → 122ms (math), 17.9s → 350ms
(system status) — confirma nossa cascata com números. Semantic router import
1800ms → 2.2ms (lazy import — lição: imports pesados fora do caminho quente).

### Emotional state (`jarvis/emotional_state.py`)
Detecção de emoção por keywords PT (`urgente`/`não funciona`/`obrigado`...) com
perfis de resposta (tone/speed/emoji) → conecta com TTS emocional (Fase 8).

### Self-healing (`self_healing.sh`, `agents/self-healing-jarvis.py`)
Monitor de serviços systemd com restart automático — o `jarvis doctor` + NixOS
`Restart=always` já cobrem isso de forma declarativa (o systemd reinicia
sozinho; o doctor diagnostica). Nada novo a portar, mas valida a direção.

### Accessibility (`docs/ACCESSIBILITY_SYSTEM.md`)
Alarmes com TTS + notificação gentil (dor crônica): timers systemd + scripts
TTS. Contexto do usuário — vale portar os alarmes como timers declarativos na
Fase 8.

---

## 5. Respondendo às perguntas diretas

1. **"O RAG cobre a memória, não precisamos de episódica?"** — Não. RAG é
   conhecimento; memória episódica é experiência. O legado tinha um
   experience_buffer primitivo (keyword match) que é a ponte. Fase 7 mantém-se.
2. **"Usamos RiveScript mesmo ou regex?"** — O legado usava **RiveScript**
   (motor de pattern-matching com topics/prioridade/macros), não regex puro.
   Nós usamos **regex + TF-IDF + roteador em cascata** (Python puro). A
   arquitetura de decisão é a mesma (fast path antes do LLM); a implementação
   é mais simples e testável. Se comandos de voz exigirem topics/contexto,
   o RiveScript legado é a referência.
3. **"O audiobook header existe na nossa stack?"** — Não. Não temos audiobook
   nem voice path ainda. O legado tinha: enhanced_audiobook.py (TTS XTTS),
   audiobook.rive (controle por voz com topics), book_indexer (ChromaDB),
   reading_state.json (progresso). Nossa coleção Qdrant `books` já está
   reservada para isso (Fase 8).
4. **"Insights só da internet?"** — Não; esta inspeção foi direto no snapshot
   Manjaro montado (`/mnt/manjaro`). A pesquisa da internet (ClawNix, Agentix,
   mcp-nixos, intent routing) complementou, mas a arquitetura de fast paths,
   audiobook e experiência veio do código real do legado.
