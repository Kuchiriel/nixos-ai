# ChatGPT Shared Conversation — 2026-08-27

**Source:** https://chatgpt.com/share/6a903d31-1084-83e9-a268-5ccf07c703f2
**Extracted:** 2026-08-27 via Playwright
**Messages:** 11
**Characters:** 45,184

---

## Context

This conversation contains the original setup instructions and architectural decisions for the nixos-ai project, including:

1. Migration from Manjaro → NixOS with declarative infrastructure
2. Legacy system preservation (trigger words, fast paths, RiveScript, Whisper)
3. Architecture: RAG (Qdrant), Memory (Qdrant), Fast Paths (RiveScript), llama.cpp local inference
4. Harness requirements: 20 fundamental rules for the agent system
5. Roo Dev integration instructions
6. Evaluation harness requirements
7. Context engineering requirements

## Key Instructions (from ChatGPT)

### First Phase — DO NOT IMPLEMENT
> "Sua primeira resposta após ler a conversa e o repositório deve ser SOMENTE uma auditoria."

### Task Completion Criteria
> "Uma tarefa só vira VERIFIED quando a evidência corresponde ao comportamento que a tarefa realmente exige."

### Anti-Pattern to Avoid
> "Não quero 'unit tests passaram' sendo usado como evidência suficiente para declarar uma tarefa concluída."

### Recovery Strategy
> "O retry deve alterar alguma condição: contexto, estratégia, ferramenta, comando, prompt, orçamento, diagnóstico."

---

*Full text saved in /tmp/chatgpt_result.json*
