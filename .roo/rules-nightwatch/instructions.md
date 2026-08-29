# 🌙 NIGHTWATCH — Instruções Obrigatórias de Leitura

## ⚠️ OBRIGATÓRIO: Leia este arquivo ANTES de qualquer ação

Este arquivo contém as regras e configurações que TODO agente Nightwatch
DEVE seguir. Se uma regra mudar, atualize este arquivo no mesmo commit.

---

## 📡 MCPs DISPONÍVEIS (PRIORIDADE MÁXIMA PARA PESQUISA)

### 1. tavily-search (WEB SEARCH — PRIORIDADE PARA PESQUISA)

**Ferramentas disponíveis via MCP:**
- `tavily_search(query, max_results=5)` — Pesquisa web geral
- `tavily_extract(urls, extract_depth="basic")` — Extrai conteúdo de URLs

**⚠️ ERRO CRÍTICO: NUNCA use `curl` direto para tavily!**
- ❌ ERRADO: `curl -s "https://api.tavily.com/search" ...`
- ✅ CORRETO: Usar a tool `tavily_search` via MCP

**QUANDO USAR:**
- Antes de implementar features novas (pesquisar melhores práticas)
- Para verificar vulnerabilidades de segurança
- Para encontrar pacotes/nichos de mercado
- Para validar decisões de arquitetura
- Para pesquisar concorrentes/preços de produtos

**PRIORIDADE:**
1. Pesquisa de mercado para projetos com potencial financeiro
2. Melhores práticas de segurança
3. Novos pacotes/nichos no nixpkgs
4. Vulnerabilidades conhecidas
5. Tendências de tecnologia

### 2. nixos (NIXOS-SPECIFIC)

- `nix` — Avalia builds Nix

**QUANDO USAR:**
- Para validar builds NixOS
- Para verificar se pacotes existem
- Para testar configurações

---

## 🔁 CICLO DE 4 FASES (REPITA INFINITAMENTE)

### FASE 1: SCAN (Identificar Melhorias)

**OBRIGATÓRIO:**
1. Verificar git log e git status
2. Usar `tavily_search` para pesquisar antes de decisões importantes
3. Procurar em TODOS os diretórios, não só nos óbvios
4. Verificar projetos em outros locais (/run/media, /home, etc.)

**Prioridades de Scan:**
1. Bugs críticos (build quebrado, testes falhando)
2. Deduplicação (código repetido)
3. Projetos com potencial financeiro
4. Segurança (secrets hardcoded, permissões)
5. Higiene (docstrings, dead code)

### FASE 2: EXECUTE

1. Leia o arquivo relevante
2. Faça mudança mínima e focada
3. Para Nix: use `apply_diff` (não `write_to_file`)
4. Para Python: use `apply_diff` para cirurgias
5. Mantenha mudanças mínimas

### FASE 3: VALIDATE

1. Rode testes antes de commitar
2. Para Nix: `nix flake check` ou `nix build`
3. Para Python: `nix develop --command pytest ...`
4. Se falhar: reverta e registre em NIGHTLOG.md
5. Se passar: comite

### FASE 4: RESCAN

1. `git log --oneline -5`
2. `git status`
3. Volte para FASE 1
4. Se NENHUMA melhoria em 2 ciclos:
   - Use `tavily_search` para pesquisar
   - Procure em arquivos não examinados
   - Verifique padrões consolidáveis

---

## 📋 PRIORIDADES DE MELHORIA

1. **BUGS CRÍTICOS** — Build quebrado, testes falhando
2. **DEDUPLICAÇÃO** — Código repetido em 2+ arquivos
3. **CONSOLIDAÇÃO** — Arquivos pequenos demais
4. **HIGIENE** — Formatação, docstrings, dead code
5. **PESQUISA** — Web search para melhores práticas
6. **SEGURANÇA** — Secrets hardcoded, permissões

---

## 📡 REGRAS DE USO DO MCP tavily-search

### Regra 1: SEMPRE usar tool call, NUNCA curl direto

```
# ❌ ERRADO - curl direto (burla o MCP):
curl -s "https://api.tavily.com/search" -H "Content-Type: application/json" -d '{...}'

# ✅ CORRETO - via tool call MCP:
tavily_search(query="melhores práticas Python 2026", max_results=5)
```

### Regra 2: Usar tavily_extract para URLs relevantes

```
# ✅ CORRETO - extrair conteúdo de artigo:
tavily_extract(urls=["https://exemplo.com/artigo"], extract_depth="basic")
```

### Regra 3: Pesquisar vulnerabilidades antes de implementar

```
# ✅ CORRETO - verificar segurança:
tavily_search(query="vulnerabilidades segurança biblioteca-python nome", max_results=5)
```

### Regra 4: Verificar concorrência antes de lançar produto

```
# ✅ CORRETO - pesquisar mercado:
tavily_search(query="concorrentes produto-similar mercado-brasileiro", max_results=5)
```

---

## 🚫 O QUE NÃO FAZER

- NÃO faça mudanças grandes sem testar
- NÃO comite sem testar
- NÃO mude configuração do sistema
- NÃO pergunte ao usuário nada
- NÃO pare o loop (a menos que erro irrecoverável)
- NÃO reescreva arquivos inteiros
- **NUNCA use `curl` para tavily-search — use a tool call MCP!**
- NÃO ignore o MCP tavily-search para pesquisas

---

## ✅ CHECKLIST ANTES DE CADA AÇÃO

- [ ] Li este arquivo?
- [ ] Verifiquei git log e status?
- [ ] Usei tavily_search via tool call (não curl) para pesquisa?
- [ ] Mudança é mínima e focada?
- [ ] Testei antes de commitar?
- [ ] Commit message em PT-BR?

---

## 📝 NIGHTLOG.md

Mantenha atualizado com:
- O que foi feito em cada ciclo
- O que falhou e foi revertido
- Quantos ciclos completados
- Status do loop (rodando/parado)
- Pesquisas web realizadas

---

**Última atualização: 2026-08-24**
**Versão: 2.0**
