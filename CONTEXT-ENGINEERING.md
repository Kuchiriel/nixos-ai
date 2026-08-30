# Context Engineering — Como Buffy mantém o mapa do projeto

> Baseado em: Anthropic context engineering, OpenDev paper (arxiv 2603.05344),
> Claude Code memory docs, Packmind ContextOps guide.

## O PROBLEMA

Buffy precisa do mapa do projeto a CADA prompt, não só no início da sessão.
Mas o projeto tem 62 módulos Python, 87 arquivos Nix, 100+ .md.
É impossível manter tudo no contexto de uma vez.

## A SOLUÇÃO: Three-Layer Context Architecture

```
Layer 1: Lightweight Index (sempre no contexto)
  → HANDOFF.md (< 200 linhas)
  → Buffalo.md (regras permanentes)
  → Árvore de diretórios ( find -type f | head -50 )

Layer 2: On-Demand Loading (RAG search por prompt)
  → jarvis rag "o que modified recentemente"
  → jarvis recall "o que fiz na última sessão"
  → jarvis lessons "erros comuns neste módulo"

Layer 3: Deep Dive (quando RAG não basta)
  → read_files() do módulo específico
  → git log/diff do diretório afetado
  → nix eval da expressão afetada
```

## REGRAS POR PROMPT

### Antes de CADA resposta:
1. RAG search: `jarvis rag " contexto do prompt "`
2. Memory recall: `jarvis recall "últimas alterações"`
3. Se módulo específico → ler HANDOFF.md para paths

### Depois de CADA alteração:
1. `jarvis remember "alterei X em Y por causa de Z"`
2. Atualizar HANDOFF.md se status mudou
3. `jarvis vault summarize` se mudança significativa

### A cada 5 prompts:
1. Verificar git status
2. RAG index se código mudou muito
3. Reavaliar prioridades

## O QUE NÃO FAZER

- NÃO ler todos os .py no início
- NÃO copiar tudo pro contexto
- NÃO recriar HANDOFF.md do zero
- NÃO inventar módulos sem RAG search primeiro

## COMO FUNCIONA NA PRÁTICA

Prompt: "arruma o watchdog"
→ RAG search: "watchdog" → encontra watchdog.py, jarvis-watchdog.nix
→ Memory recall: "watchdog" → "última vez: TTS com subprocess, corrigido para direto"
→ HANDOFF.md: "watchdog é serviço systemd, intervalo 60s"
→ read_files: watchdog.py (só o que precisa)
→ Altera → remember → HANDOFF.md update
