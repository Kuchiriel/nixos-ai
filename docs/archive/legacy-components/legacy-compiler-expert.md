# Compiler Expert do legado — arquitetura e o que portar

> Inspeção direta de `/mnt/manjaro/kuchiriel/Projects/AI_SYSTEM/tools/`
> (`compiler_expert.py` 397 linhas + `compiler_expert_polyglot.py` 636 linhas).
> O que o legado fazia para tornar SLMs úteis em engenharia reversa de
> codebases grandes, com o mínimo de modelo e o máximo de código.

---

## 1. O problema que resolvia

Gerar/consertar código (C++/protobuf do protocolo Tibia 15.20) com SLMs
(deepseek-r1:1.5b + qwen2.5-coder:3b via Ollama), contra um codebase grande
(canary OTServer). SLMs alucinam símbolos; codebases grandes estouram contexto.
A solução: **código faz o trabalho pesado; o LLM só raciocina sobre fatos
verificados.**

## 2. Arquitetura (o "verification loop" — o coração)

```
┌─ generate ─┐   ┌─ extract (CleanRoom) ─┐   ┌─ validate ──┐   ┌─ compile ─┐
│  LLM (3b)  │ → │ regex + block select  │ → │  símbolos   │ → │ g++ -fsyntax │
└────────────┘   └───────────────────────┘   └─────────────┘   └────────────┘
      ↑                                          │  falhou           │  falhou
      └──────────── refinement prompt ◄──────────┴───────────────────┘
        (erros reais do compilador alimentam o próximo turno, max 3 iterações)
```

Componentes:

1. **`CleanRoomExtractor`** — extrai o bloco de código da resposta do LLM
   (regex + seleção de bloco), sanitiza, ignora markdown/prosa.
2. **`ForensicSchemaDiscovery`** — descobre símbolos reais do codebase SEM LLM:
   - `_parse_cpp_file` (regex: classes, métodos, chamadas)
   - `_parse_protobuf` (mensagens, campos, e os prefixos `set_/has_/clear_/mutable_/add_`)
   - `_discover_from_rag` (chama `rag_query.py` com termos da task e parseia os arquivos retornados)
   - `_discover_working_examples` (trechos reais de `OutputMessage.*send/write`)
   - monta uma **whitelist de símbolos válidos** (descobertos + stdlib)
3. **`ForensicSymbolValidator`** — anti-alucinação: extrai todo identificador
   do código gerado e acusa qualquer símbolo fora da whitelist.
4. **`ForensicASTValidator`** — compila o código gerado com `g++ -fsyntax-only`
   (com stubs de headers + include paths do projeto) e devolve erros reais.
5. **`ForensicVerificationLoop`** — itera até 3×: o LLM regenera com um prompt
   de refinamento contendo os erros REAIS do compilador + os símbolos
   alucinados + o código anterior. Só aceita quando compila e não alucina.

**Resultado**: o LLM de 3B "conversa" com o compilador — o g++ é o ground
truth, não o modelo. Isso é o **self-correction por feedback real**, que
economiza tokens (iterações curtas) e elimina alucinação de símbolos.

## 3. Polyglot (compiler_expert_polyglot.py — a versão multi-linguagem)

Estende para N linguagens com:

- **`LanguageDetector`** — detecta linguagem por extensão + conteúdo (cpp,
  python, js, rust, go, java, csharp, php, ruby, generic).
- **`Grammarian`** — extração de **fatos** por linguagem (`DEFINES_FUNC`,
  `DEFINES_CLASS`, `IMPORTS`, `DECLARES_VAR`, `CALLS_FUNC`) com regex por
  linguagem (linha a linha).
- **`FunctionTargetor`** — extrai funções-alvo da task + o corpo da função
  (balanceamento de chaves; indentation-based p/ Python/Ruby).
- **`TwoStageRetrieval`** — **RAG em 2 estágios**:
  1. `stage1_candidate_retrieval` (recupera candidatos do contexto bruto)
  2. `stage2_rerank` (re-ranqueia por alvo/termos da task)
  3. `build_context` (monta contexto limitado a ~35k chars — caber no SLM)
- **`HybridRAG.extract_multi_source`** — fatos de múltiplas fontes.

## 4. O que é reaproveitável no JARVIS NixOS

| Ideia | Estava no legado | Port para nós |
|---|---|---|
| **Verification loop com compilador como ground truth** | g++ -fsyntax-only + refinement | `jarvis verify`/agente: gerar código → compilar (gcc/g++/cargo/go) → realimentar erros → iterar (max N). **O compilador substitui o LLM como juiz.** |
| **Whitelist de símbolos** (anti-alucinação) | SchemaDiscovery + SymbolValidator | Com nosso RAG híbrido no Qdrant, a descoberta de símbolos reais melhora (sparse BM25 acha símbolos exatos). |
| **Two-stage retrieval + contexto limitado** | stage1+rerank, ~35k chars | Nosso RAG já é híbrido; o *limit de contexto para caber no modelo* é a lição (rich_content_chars já faz isso). |
| **Fatos por linguagem** | Grammarian | Nosso `extract_facts` do V4.0.5 já porta regex por extensão — mesmo conceito. |
| **SLM barato + código caro** | r1:1.5b + qwen 3b | Filosofia central: nosso roteador + doctor/nixos/rag determinísticos já seguem. |

## 5. O que descartar

- **Ollama** (→ llama.cpp, já feito).
- **Regex de extração de corpo de função** (→ no host, se precisar, usar
  tree-sitter ou `ast`/`pycparser` — o legado limitava a 100 linhas e falhava
  em aninhamento; nosso RAG por símbolo cobre melhor).
- **Ground truth hardcoded do protocolo 15.20** (contexto específico do Tibia —
  não portar; mas a *técnica* de injetar ground truth imutável no prompt é
  válida: vira o "system prompt de domínio" do agente).

## 6. Conclusão

O compiler expert é a prova de que a filosofia "extrair o máximo do mínimo"
funciona em engenharia reversa: **SLM de 3B + RAG de símbolos + compilador
como juiz** gerava código de protocolo correto. Para o JARVIS NixOS, a peça
portável de maior valor é o **verification loop com o compilador como
ground truth** — vira uma ferramenta do agente (ex: `jarvis fix <file>` que
itera até compilar). Registrar na Fase 10 (RAG SOTA) como sub-item.
