# Técnicas para SLMs Locais em Tool Calling

> Lições aprendidas no bulldozer loop com Qwen3-4B (via llama.cpp).

## O Que Funcionou

### 1. FORÇAR LEITURA ANTES DE EDIÇÃO

**Problema**: SLMs chutam o conteúdo de arquivos em vez de ler.

**Solução**: System prompt com regra explícita:
```
CRITICAL: NEVER guess file content — ALWAYS read_file FIRST
When using str_replace, the 'old' parameter must be the EXACT text from the file
Copy text character-by-character from read_file output — do not paraphrase
```

**Resultado**: Taxa de sucesso em `str_replace` subiu de ~30% para ~85%.

### 2. FUZZY MATCHING NO STR_REPLACE

**Problema**: SLMs erram whitespace/indentação mesmo lendo o arquivo.

**Solução**: 4 estratégias crescentes:
1. **Exact** — match direto (rápido)
2. **Normalized** — colapsa whitespace mas preserva novas linhas
3. **Fuzzy** — difflib com threshold 75% + janela deslizante
4. **Line-match** — último recurso, linha única

**Resultado**: ~15% das tentativas que falhariam agora passam via fuzzy.

### 3. WORKFLOW EXPLÍCITO NO PROMPT

**Problema**: SLMs pulam etapas (editam sem ler, testam sem editar).

**Solução**: Workflow numerado no system prompt:
```
CRITICAL WORKFLOW (always follow this order):
1. LIST: list_directory to see available files
2. READ: read_file to see the EXACT content
3. EDIT: str_replace with the EXACT text you just read
4. TEST: run_tests to validate changes
5. ITERATE: if tests fail, read errors, fix, re-test
```

### 4. TEMPERATURE ZERO

**Problema**: SLMs com temperature > 0 variam demais nas tool calls.

**Solução**: `temperature: 0.0` para todas as operações de tool calling.

### 5. FEW-SHOT VIA OUTPUT ANTERIOR

**Problema**: SLMs não sabem o formato esperado das tools.

**Solução**: O feedback do erro já serve como few-shot implícito:
```
🔧 str_replace({...})
→ {"ok": false, "error": "String not found", "hint": "Closest match: ..."}
🤖 (SLM lê o hint e tenta com o texto correto)
```

## O Que NÃO Funcionou

### 1. PEDIR PARA O SLM "PENSAR ANTES DE AGIR"
- SLMs pequenos ignoram instruções de raciocínio
- Melhor: forçar ação (read_file) do que pedir reflexão

### 2. MÚLTIPLOS ARQUIVOS EM UMA ÚNICA CHAMADA
- SLMs pequenos misturam o conteúdo de arquivos diferentes
- Melhor: uma tool call por arquivo, iterativamente

### 3. EDIÇÕES GRANDES (write_file COM CONTEúdo COMPLETO)
- SLMs truncam conteúdo longo ou omitem partes
- Melhor: str_replace para edições pontuais, write_file só para arquivos novos curtos

### 4. PROMPT COMPLEXO COM MUITAS REGRAS
- SLMs com < 7B parcialmente ignoram prompts longos
- Melhor: regras curtas e diretas (máx 10 linhas de workflow)

## Métricas Observadas (Qwen3-4B)

| Tarefa | Taxa de Sucesso | Tempo Médio |
|---|---|---|
| Edição de 1 linha | ~90% | ~15s |
| Criação de função | ~85% | ~20s |
| Refatoração multi-linha | ~70% | ~35s |
| Criação de arquivo | ~80% | ~15s |
| Leitura + edição iterativa | ~60% | ~45s |
| Tool calling JSON válido | ~75% | ~10s |

## Regras para Prompts de SLMs Locais

1. **Máximo 10 linhas** de workflow/instrução
2. **Sempre** incluir "read_file FIRST"
3. **Numerar** os passos (1, 2, 3...)
4. **Usar** imperativo ("Read", "Edit", "Test")
5. **Incluir** fallback ("If str_replace fails, read the file again")
6. **Limitar** tool calls por turno (max 10)
7. **Zero temperature** para tool calling
