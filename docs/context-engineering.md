# Context Engineering — nixos-ai

> Guias práticos de gestão de contexto para agentes locais com 32K tokens.
> Baseado em pesquisa: Anthropic, Martin Fowler, AkitaOnRails, Roo Code docs.

## Princípios Fundamentais

### 1. Contexto é Recurso Escasso

Com 32K tokens:
- System prompt: ~15-20K (Roo Dev)
- Sobram: ~12-17K para conversa + tools
- Cada tool output consome contexto
- **Context rot**: quanto mais tokens, menor a recall do modelo

### 2. Just-in-Time Context

Não carregue tudo de uma vez. Use referências leves e carregue sob demanda:

```
ERRADO: cat arquivo.py inteiro (500 linhas = ~2K tokens)
CORRETO: grep -n 'func' arquivo.py | head -5 → sed -n '120,140p' arquivo.py
```

### 3. Disposable Context

Tool outputs que podem ser descartados após uso:
- `find` results → resuma em bullets
- `git diff` → extraia só o que importa
- `ls -la` → resuma em "X arquivos, Y MB"
- `grep` results → use apenas os matches relevantes

### 4. Context Offloading

Mova informação para armazenamento externo quando não está imediatamente necessária:

| Tipo | Offload para | Exemplo |
|------|-------------|---------|
| Estado da tarefa | NIGHTLOG.md | "Ciclo 5: corrigido bug X" |
| Decisões de arquitetura | docs/ADR.md | "Escolhemos Y porque Z" |
| Resultados de testes | docs/benchmarks/ | "32.9 tok/s com ncmoe=35" |
| Memória episódica | jarvis remember | "Sessão 2026-08-28:..." |
| Conhecimento do projeto | AGENTS.md | Regras universais |

## Regras de Output por Tool

### SEMPRE limitar

| Tool | Limite | Comando |
|------|--------|---------|
| `find` | máx 30 | `find . -maxdepth 2 \| head -30` |
| `ls` | sem recursivo | `ls dir/` (nunca `ls -R`) |
| `git log` | máx 10 | `git log --oneline -10` |
| `cat` | PROIBIDO | `head -n 50` ou `sed -n '10,30p'` |
| `grep` | máx 20 | `grep -m 20 'termo'` |
| `wc -l` | ok (1 linha) | `wc -l < arquivo` |
| `nix eval` | ok (1 linha) | `nix eval .#attr` |

### Regra de ouro

> Se o output tem >50 linhas, RESUMA em 5 bullet points antes de continuar.

## MCP Tools — Quando Usar

### jarvis_execute
- Comandos de sistema que as built-in tools não cobrem
- `find`, `du`, `file`, `stat`, `nix` commands

### jarvis_read_file
- Ler arquivos com offset/limit preciso
- Mais eficiente que `sed` para ranges grandes

### jarvis_observe_screen
- Capturar e analisar tela com vision
- Útil para debug de GUI, verificar estado visual

### tavily_search
- Pesquisa web para documentação, bugs, soluções
- Usar quando a documentação local não é suficiente

### context7
- Documentação de bibliotecas em tempo real
- Útil para APIs que mudam frequentemente

### nix (nixos-mcp)
- Pesquisar packages e options do nixpkgs
- Anti-hallucination: retorna dados reais

## Gestão de Sessão Longa

### Para nightwatch/organizer

1. **Checkpoint periódico**: atualize NIGHTLOG.md a cada 3 ciclos
2. **Leia antes de agir**: NIGHTLOG.md → AGENTS.md → último estado
3. **Não re-leia arquivos inteiros**: use `head`/`tail`/`grep`
4. **Condensing é esperado**: quando acontecer, continue o loop

### Para code/architect

1. **Edits cirúrgicos**: str_replace > reescrita
2. **Um arquivo por vez**: não edite 3 arquivos na mesma resposta
3. **Teste antes de commitar**: `nix flake check` ou `pytest`
4. **Commit atômico**: uma mudança = um commit

## Anti-Padrões

| Anti-Padrão | Por quê | Alternativa |
|-------------|---------|-------------|
| `cat arquivo.py` | Consome ~2K tokens | `head -50` ou `grep` |
| `ls -R` | Lista tudo recursivamente | `ls dir/` |
| `find . \| wc -l` | Conta mas não mostra | `find . -maxdepth 2 \| head -30` |
| Ler AGENTS.md inteiro | ~1K tokens | Já está no contexto automaticamente |
| Re-ler HANDOFF.md | ~3K tokens | Use `grep` para buscar seção específica |
| `git diff` sem limitação | Pode ser enorme | `git diff --stat` ou `git diff HEAD~1` |

## Referências

- [Anthropic: Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Martin Fowler: Context Engineering for Coding Agents](https://martinfowler.com/articles/exploring-gen-ai/context-engineering-coding-agents.html)
- [Roo Code: Intelligent Context Condensing](https://roocodeinc.github.io/Roo-Code/features/intelligent-context-condensing/)
- [AkitaOnRails: O Akita abriu as pernas pra IA](https://www.akitaonrails.com/2026/02/24/rant-o-akita-abriu-as-pernas-pra-ia/)
