# 📝 ROOMODES — Notas de Correção e Configuração

## ⚠️ ERRO CRÍTICO NO FORMATO DO .roomodes

### Problema Identificado
Ao tentar adicionar tools MCP ao `.roomodes`, o Roo Code retornou erro:
```
Invalid mode: customModes.0.groups.3: Invalid input
```

### Causa
O formato do `.roomodes` **NÃO aceita** grupos arbitrários como `browser` ou `execute`.
A sintaxe `tools:` com nomes de tools MCP **não é suportada** pelo parser do Roo Code.

### Solução Correta
O `.roomodes` usa `groups:` para definir permissões básicas. **APENAS estes grupos são válidos:**
- `read` — leitura de arquivos
- `edit` — edição de arquivos
- `command` — execução de comandos

**NUNCA use:** `browser`, `execute`, `tools`, etc.

### Configuração Correta do .roomodes
```yaml
groups:
  - read
  - edit
  - command
```

### Como Usar MCP Corretamente
1. **NUNCA use `curl` direto para tavily** — use a tool `tavily_search` via MCP
2. As tools MCP são expostas automaticamente pelo Roo Code quando configuradas no `mcp_settings.json`
3. O `alwaysAllow` no `mcp_settings.json` permite que as tools sejam usadas sem confirmação
4. **NÃO tente** expor tools MCP via `.roomodes` — use a configuração global

---

## 📡 MCPs DISPONÍVEIS

### 1. tavily-search
- **Ferramentas**: `tavily_search`, `tavily_extract`
- **Configuração**: Global no `mcp_settings.json`
- **Uso**: Sempre via tool call, NUNCA curl direto

### 2. nixos
- **Ferramenta**: `nix`
- **Configuração**: Global no `mcp_settings.json`
- **Uso**: Para validar builds NixOS

---

## 📋 Yampi — Informações Corretas (2026)

### O que é Yampi?
- **Plataforma de e-commerce + checkout transparente** brasileiro
- Foco em conversão e experiência de compra
- Mais de 1.000 lojistas (2024)
- Integrado com múltiplos gateways de pagamento

### Gateways Integrados
- Mercado Pago ✅ (já integrado no seu projeto)
- PagBrasil
- Pagar.me
- Cielo
- BS2
- Pagaleve
- Iugu
- GetNet
- PagBank
- Appmax

### Produtos Yampi
1. **Loja Virtual** — Plataforma e-commerce completa
2. **Checkout Transparente** — Para usar em landing pages/outras lojas
3. **Dropshipping** — Solução para dropshipping
4. **Venda Física** — Para lojas presenciais

### Pricing Yampi
- Não encontrado pricing público detalhado
- Provavelmente modelo freemium ou comissão por venda

### Recomendação para Guia Renamer Pro
- **Yampi** é excelente para vender software digital
- Checkout transparente pode ser usado em landing page
- Integração com Mercado Pago já configurada ✅
- Pode usar tanto Loja Virtual quanto apenas Checkout

---

## 📊 Mercado Brasileiro de Software Médico (2026)

### Tamanho do Mercado
- **R$ 4,2 bilhões** em sistemas de informação hospitalar (ANAHP, 2025)
- **53,5%** do mercado: MV (Soul MV) e Tasy (Philips Healthcare)
- **Restante**: RD Saúde, Pixeon, Wareline, etc.

### Padrões Regulatórios
- **TISS v3.05** — Padrão obrigatório para troca de informações em saúde suplementar
- **RNDS** — Rede Nacional de Dados em Saúde (obrigatória para estabelecimentos habilitados)
- **LGPD** — Proteção de dados de saúde
- **ANS** — Agência Nacional de Saúde Suplementar

### Principais Players
1. **MV (Soul MV)** — 35% de participação em hospitais
2. **Tasy (Philips Healthcare)** — 20% de participação
3. **RD Saúde** — Clínicas menores
4. **Pixeon** — Gestão hospitalar
5. **Wareline** — Clínicas multiprofissionais
6. **App Health** — Software moderno com IA
7. **Klinity** — Software médico com IA
8. **ProDoctor** — Híbrido (local + nuvem)
9. **HiDoctor** — IA própria para transcrição

### Tendências 2026
1. **Inteligência Artificial** — Transcrição de consultas, assistente clínico
2. **Automação WhatsApp** — Confirmação de consultas (reduz 40% faltas)
3. **Telemedicina Nativa** — Prescrição digital ICP-Brasil
4. **Faturamento TISS/TUSS sem Glosas** — Geração automática de guias
5. **Conformidade LGPD/CFM** — Criptografia, backups, logs de auditoria

### Oportunidade para Guia Renamer Pro
- **Nicho não atendido**: Automação de guias médicas TISS
- **Dor real**: Glosas por inconsistências de dados (perda de receita)
- **Público-alvo**: Clínicas, hospitais, laboratórios que processam guias TISS
- **Diferencial**: OCR inteligente + renomeação automática + validação de qualidade
- **Modelo de negócio**: SaaS B2B (R$197-397/mês ou licença vitalícia)

### Concorrentes Diretos
- **Nenhum** software focado em renomeação de guias TISS com OCR
- Softwares existentes focam em: prontuário, faturamento, agenda
- **Guia Renamer Pro** é único em automação de documentos TISS

---

## 🚀 Estratégia Comercial para Guia Renamer Pro

### Fase 1: Validação (1-3 meses)
- Lançar trial de 10 guias grátis
- Coletar feedback de clínicas piloto
- Validar qualidade do OCR com PDFs reais

### Fase 2: Comercialização (3-6 meses)
- Configurar Yampi para venda de licenças
- Integrar checkout transparente na landing page
- Marketing direto para clínicas/hospitais

### Fase 3: Escala (6-12 meses)
- Versão SaaS com heartbeat automático
- Integração com sistemas existentes (MV, Tasy, RD Saúde)
- Módulo de validação TISS (previne glosas)

### Fase 4: Expansão (12+ meses)
- Módulo de faturamento TISS completo
- Integração com RNDS
- IA para transcrição de consultas

---

**Última atualização: 2026-08-24**
**Versão: 2.0**
