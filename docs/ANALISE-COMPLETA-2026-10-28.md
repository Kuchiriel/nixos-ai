# Análise Completa do Projeto nixos-ai

Data: 2026-10-28  
Objetivo: Identificar problemas, oportunidades e recomendações baseadas em melhores práticas de mercado e papers recentes.

## 1. Visão Geral

- **Total de arquivos .nix**: 104
- **Total de scripts (.py/.sh)**: 419
- **Arquitetura**: NixOS flake com múltiplos pins, home-manager, sistema modular complexo
- **Componentes principais**: JARVIS AI stack (llama.cpp/router, Qdrant, MCP, duplex voice), Opencode, vários serviços

## 2. Problemas Identificados

### 2.1 Gerenciamento de Secrets
**Estado atual:**
- Usa `/etc/litellm.env` como fonte única (recentemente consolidado) - bom progresso
- Alguns segredos em `/etc/jarvis-secrets/` (tavily.env, hackmd.env, chaves Fernet, etc.)
- Arquivo `/etc/litellm.env` com permissões `644` (legível por todos) - não ideal
- `keys-wrapper.sh` agora só lê de `/etc/litellm.env` - melhorou

**Problemas:**
- Secrets ainda em arquivos plaintext em `/etc/` ao invés de sistema declarativo criptografado
- Permissões muito abertas em `/etc/litellm.env` (644)
- Múltiplas formas de gerenciar secrets historicamente (tavily.env separado, keys.env gerado por activation)

**Melhores práticas (sops-nix/agenix):**
- Migrar para [sops-nix](https://github.com/Mic92/sops-nix) ou [agenix](https://github.com/ryantm/agenix)
- Secrets devem ser criptografados no repo, descriptografados apenas no host com chaves SSH/age
- Evitar secrets no store do Nix
- Usar `EnvironmentFile` com arquivos com permissão 600, propriedade do usuário do serviço
- Princípio do menor privilégio para acesso a secrets

**Papers/Referências:**
- [NixOS Wiki - Secrets Management](https://wiki.nixos.org/wiki/Comparison_of_secret_managing_schemes)
- [sops-nix documentation](https://github.com/Mic92/sops-nix)

### 2.2 Hardening de systemd
**Estado atual:**
- Alguns serviços bem hardenizados: `jarvis-webui`, `jarvis-idle`, `nightwatch-timer`, `jarvis-watchdog` têm `ProtectSystem=strict`, `PrivateTmp`, `NoNewPrivileges`
- Outros com hardening mínimo: `llama-cpp` só tem limites de memória
- `qdrant` sem hardening aparente
- Muitos serviços podem carecer de hardening

**Problemas:**
- Inconsistência entre serviços
- Serviços com acesso GPU (llama-cpp) precisam de configuração cuidadosa mas ainda podem ter hardening adicional
- Falta uso sistemático de `SystemCallFilter`, `CapabilityBoundingSet`, `RestrictNamespaces`, `ReadOnlyPaths`

**Melhores práticas:**
- Usar `systemd-analyze security <service>` para auditar
- Aplicar hardening por padrão onde possível
- Para serviços com GPU: cuidado com `PrivateDevices` (precisa acesso a /dev/nvidia*)
- Usar `DynamicUser` quando possível
- Aplicar `RestrictAddressFamilies`, `RestrictRealtime`, `LockPersonality`, etc.

**Referências:**
- [NixOS Wiki - Systemd Hardening](https://wiki.nixos.org/wiki/Systemd/Hardening)
- [systemd.exec man page - sandboxing options](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)

### 2.3 Arquitetura Flake
**Estado atual:**
- Múltiplos pins de nixpkgs (nixos-26.05, master, unstable, nixos-25.11 para wine)
- Overlays complexos
- Hacks para drivers NVIDIA (overlay do master)
- Dependências cruzadas complexas

**Problemas:**
- Complexidade alta dificulta manutenção
- Múltiplos canais podem causar conflitos de versão
- Tempo de avaliação/build pode ser maior
- Difícil de entender fluxo de dependências

**Oportunidades:**
- Considerar consolidar onde possível
- Documentar melhor por que cada pin é necessário
- Usar `flake-utils` ou estruturas mais padronizadas
- Avaliar uso de `npins` ou alternativas para gerenciamento mais simples

### 2.4 MCP Security
**Estado atual:**
- MCP do JARVIS configurado via launcher customizado
- Fonte única de keys corrigida
- Timeout aumentado para 180000ms

**Riscos (baseado em pesquisas recentes):**
- **Tool Poisoning**: Descrições de tools maliciosas podem injetar instruções
- **Prompt Injection**: Via conteúdo retornado por tools
- **Excessive Permissions**: Tools com muito acesso
- **Credential Sprawl**: Múltiplas chaves compartilhadas

**Melhores práticas (OWASP MCP Top 10, CSA):**
- **Least Privilege**: Cada tool/MCP deve ter apenas permissões necessárias
- **Tool Allowlisting**: Restringir quais tools podem ser usados
- **Input/Output Validation**: Validar todas as entradas/saídas
- **Sandboxing**: Isolar MCP servers
- **Credential Management**: Usar secrets por MCP, rotação
- **Human-in-the-loop**: Para ações destrutivas/sensíveis
- **Audit Logging**: Logar todas as chamadas de tool
- **Network Segmentation**: Restringir acesso de rede

**Referências:**
- [OWASP MCP Top 10](https://owasp.org/www-project-mcp-top-10/)
- [Cloud Security Alliance - MCP Security](https://cloudsecurityalliance.org/blog/2025/06/02/model-context-protocol-mcp-security-what-you-need-to-know)
- [Invariant Labs - MCP Security](https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks)

### 2.5 Serviços LLM/AI
**Estado atual:**
- Arquitetura complexa com múltiplos backends (prism, upstream, ik)
- Router com presets
- Múltiplos provedores cloud configurados no opencode
- Gerenciamento de VRAM com apenas 1 modelo residente

**Oportunidades:**
- Melhorar observabilidade (métricas, tracing)
- Implementar rate limiting mais granular
- Adicionar health checks mais robustos
- Considerar model caching/loading strategies
- Melhorar isolamento entre componentes

## 3. Oportunidades de Melhoria

### 3.1 Segurança
1. **Migrar secrets para sops-nix**
   - Criptografar secrets no git
   - Usar age/SSH keys
   - Eliminar arquivos plaintext em `/etc/`

2. **Melhorar hardening systemd**
   - Aplicar template de hardening padronizado
   - Usar `systemd-analyze security` em CI
   - Adicionar `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6` onde aplicável
   - Considerar `ReadOnlyPaths`, `ReadWritePaths` explícitos

3. **Reforçar MCP security**
   - Implementar allowlist de tools
   - Adicionar validação de schemas
   - Logging auditável
   - Considerar sandboxing com containers/nspawn

### 3.2 Manutenibilidade
1. **Documentação**
   - Melhorar documentação de arquitetura
   - Documentar decisões (ADRs)
   - Criar runbooks para troubleshooting

2. **Testes**
   - Aumentar cobertura de testes
   - Adicionar testes de integração
   - Validar configurações Nix em CI

3. **Refatoração**
   - Simplificar estrutura de overlays
   - Consolidar configuração de providers
   - Melhorar modularização

### 3.3 Performance/Observabilidade
1. **Métricas**
   - Adicionar Prometheus exporters
   - Dashboards para monitoramento
   - Alerting

2. **Logging**
   - Centralizar logs
   - Structured logging
   - Log rotation

## 4. Plano de Ação Recomendado

### Curto Prazo (Alta Prioridade)
- [ ] **Secrets**: Planejar migração para sops-nix (avaliar esforço vs benefício)
- [ ] **Hardening**: Aplicar hardening básico nos serviços sem proteção (llama-cpp, qdrant)
- [ ] **MCP**: Revisar permissões e adicionar logging
- [ ] **Auditoria**: Rodar `systemd-analyze security` em serviços críticos

### Médio Prazo
- [ ] **sops-nix**: Implementar migração gradual
- [ ] **Systemd hardening**: Template padronizado + aplicação sistemática
- [ ] **Observabilidade**: Adicionar métricas básicas
- [ ] **Documentação**: Atualizar diagramas e runbooks

### Longo Prazo
- [ ] **Refatoração flake**: Simplificar estrutura
- [ ] **CI/CD**: Melhorar validação
- [ ] **Security scanning**: Integrar ferramentas de análise

## 5. Referências

### NixOS/Security
- [NixOS Security](https://nixos.org/manual/nixos/stable/#sec-security)
- [sops-nix](https://github.com/Mic92/sops-nix)
- [agenix](https://github.com/ryantm/agenix)
- [systemd hardening guide](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#Sandboxing)

### MCP Security (Papers/Research 2025-2026)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [OWASP MCP Top 10](https://owasp.org/www-project-mcp-top-10/) (em desenvolvimento)
- [CSA Agentic AI Security](https://cloudsecurityalliance.org/research/working-groups/agentic-ai)
- [Invariant Labs Research](https://invariantlabs.ai/research)

### AI Infrastructure
- [llama.cpp documentation](https://github.com/ggml-org/llama.cpp)
- [vLLM security considerations](https://docs.vllm.ai/)
- [Open WebUI security](https://docs.openwebui.com/)

## Conclusão

O projeto nixos-ai é bastante ambicioso e bem estruturado em muitos aspectos. Os principais pontos de melhoria estão em:
1. **Gerenciamento de secrets** - migrar para solução declarativa criptografada
2. **Hardening de systemd** - aplicar consistentemente em todos os serviços
3. **Segurança MCP** - implementar controles mais rigorosos conforme melhores práticas emergentes

O trabalho recente de consolidar chaves para `/etc/litellm.env` foi um passo na direção certa. Continuar nessa linha com sops-nix seria o próximo passo natural.
